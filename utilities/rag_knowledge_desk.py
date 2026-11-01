"""Lightweight Streamlit document-RAG demo inspired by Kotaemon's user experience.

This is an independent implementation optimized for session-based workflows:
in-memory TF-IDF retrieval by default and optional Ollama generation.
Accepts text-based PDFs, TXT, and Markdown files.
"""
from __future__ import annotations

import hashlib
import io
import re
import time
from typing import Any

import streamlit as st
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

TITLE = "Knowledge Desk (RAG)"
ICON = "📚"
DESCRIPTION = "Chat with your documents, inspect retrieved passages, and test a local RAG workflow."

APP_TITLE = "MechXcel Knowledge Desk"
SUPPORTED = {"pdf", "txt", "md"}

CUSTOM_CSS = """
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1500px;}
[data-testid="stSidebar"] {border-right: 1px solid rgba(128,128,128,.22);}
.brand-title {font-size:1.45rem; font-weight:750; letter-spacing:-.03em; margin-bottom:0;}
.brand-sub {font-size:.86rem; opacity:.70; margin-top:.15rem; margin-bottom:1.1rem;}
.source-box {border:1px solid rgba(128,128,128,.30); border-radius:12px; padding: .8rem 1rem; margin:.45rem 0;}
.source-meta {font-size:.82rem; opacity:.72;}
div[data-testid="stChatMessage"] {border-radius:14px;}
</style>
"""

DEFAULT_PROMPT = """You are a careful document assistant. Answer the question using only the supplied context.
If the context does not contain enough information, say so clearly. Do not invent code clauses, values, or citations.
Cite claims with [Source 1], [Source 2], etc. Sources are shown below.

CONTEXT:
{context}

QUESTION:
{question}

ANSWER:"""


def extract_file(name: str, data: bytes) -> list[tuple[int | None, str]]:
    ext = ("." + name.split(".")[-1]).lower() if "." in name else ""
    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        out = []
        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                out.append((i, text))
        return out
    if ext in {".txt", ".md"}:
        return [(None, data.decode("utf-8", errors="replace"))]
    raise ValueError("Supported formats: PDF, TXT and Markdown (.md).")


def split_text(text: str, chunk_size: int = 900, overlap: int = 140) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        if end < len(text):
            boundary = text.rfind(" ", start + chunk_size // 2, end)
            if boundary > start:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def process_uploaded_files(files: list[Any], chunk_size: int, overlap: int) -> tuple[int, list[str]]:
    existing_hashes = {d["sha256"] for d in st.session_state.indexed_docs}
    new_chunks = []
    indexed_names = []

    for f in files:
        data = f.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        if digest in existing_hashes:
            continue

        pages = extract_file(f.name, data)
        if not pages:
            continue

        doc_chunk_count = 0
        for page_no, page_text in pages:
            for piece in split_text(page_text, chunk_size, overlap):
                new_chunks.append({
                    "name": f.name,
                    "sha256": digest,
                    "chunk_no": doc_chunk_count,
                    "page_no": page_no,
                    "text": piece
                })
                doc_chunk_count += 1

        if doc_chunk_count > 0:
            st.session_state.indexed_docs.append({
                "name": f.name,
                "sha256": digest,
                "chunks": doc_chunk_count,
                "time": time.strftime("%H:%M:%S")
            })
            existing_hashes.add(digest)
            indexed_names.append(f.name)

    if new_chunks:
        st.session_state.chunks.extend(new_chunks)

    return len(indexed_names), indexed_names


def retrieve(query: str, top_k: int, min_score: float) -> list[dict[str, Any]]:
    chunks = st.session_state.chunks
    if not chunks:
        return []

    corpus = [c["text"] for c in chunks]
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=60000)
    matrix = vectorizer.fit_transform(corpus + [query])
    scores = cosine_similarity(matrix[-1], matrix[:-1]).ravel()
    ranked = scores.argsort()[::-1][:top_k]

    results = []
    for ix in ranked:
        score = float(scores[ix])
        if score < min_score:
            continue
        c = chunks[int(ix)]
        results.append({
            "score": score,
            "chunk_no": c["chunk_no"],
            "page_no": c["page_no"],
            "text": c["text"],
            "name": c["name"],
            "sha256": c["sha256"]
        })
    return results


def ollama_generate(prompt: str, model: str, base_url: str, timeout: int = 120) -> str:
    import requests
    url = base_url.rstrip("/") + "/api/generate"
    response = requests.post(
        url,
        json={"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.1, "num_ctx": 2048}},
        timeout=timeout,
    )
    response.raise_for_status()
    return str(response.json().get("response", "")).strip()


def make_prompt(question: str, sources: list[dict[str, Any]], template: str) -> str:
    context = "\n\n".join(
        f"[Source {i+1}: {s['name']}, page {s['page_no'] or 'N/A'}, chunk {s['chunk_no']+1}]\n{s['text']}"
        for i, s in enumerate(sources)
    )
    return template.replace("{context}", context).replace("{question}", question)


def run():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # Session storage setup
    st.session_state.setdefault("indexed_docs", [])
    st.session_state.setdefault("chunks", [])
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("events", [])
    st.session_state.setdefault("last_sources", [])

    # Sidebar
    with st.sidebar:
        st.markdown(f"<div class='brand-title'>📚 {APP_TITLE}</div>", unsafe_allow_html=True)
        st.markdown("<div class='brand-sub'>In-memory document RAG · Session workspace</div>", unsafe_allow_html=True)
        page = st.radio("Workspace", ["Chat", "Documents", "Settings", "Activity"], label_visibility="collapsed", key="rag_workspace")
        st.divider()

        st.subheader("Add documents")
        uploaded = st.file_uploader(
            "Drop PDF, TXT or Markdown files",
            type=sorted(SUPPORTED),
            accept_multiple_files=True,
            key="rag_uploader"
        )

        with st.expander("Chunking controls", expanded=False):
            chunk_size = st.slider("Chunk size (characters)", 400, 1600, 900, 100)
            overlap = st.slider("Chunk overlap", 0, 300, 140, 20)

        if st.button("Index files", type="primary", use_container_width=True, disabled=not uploaded):
            with st.spinner("Extracting and vectorizing passages into memory..."):
                count, names = process_uploaded_files(uploaded, chunk_size, overlap)
                if count > 0:
                    st.success(f"Indexed {count} file(s): {', '.join(names)}")
                else:
                    st.info("Files are already indexed or contain no extractable text.")
            st.rerun()

        st.divider()
        st.caption(f"Currently active: **{len(st.session_state.indexed_docs)}** document(s) · **{len(st.session_state.chunks)}** chunks")

    # Workspace Views
    if page == "Chat":
        top_left, top_right = st.columns([7, 2])
        with top_left:
            doc_count = len(st.session_state.indexed_docs)
            st.caption(f"**{doc_count}** document(s) ready in memory. Ask questions grounded in your uploaded files.")

        with top_right:
            if st.button("＋ New chat", use_container_width=True):
                st.session_state.messages = []
                st.session_state.last_sources = []
                st.rerun()

        with st.expander("Retrieval controls", expanded=False):
            c1, c2, c3 = st.columns(3)
            with c1:
                top_k = st.slider("Retrieved chunks", 1, 8, 4)
            with c2:
                min_score = st.slider("Minimum lexical score", 0.0, 0.3, 0.015, 0.005, help="Raise to filter weak keyword matches.")
            with c3:
                answer_mode = st.selectbox("Answer mode", ["Context extract (no LLM)", "Ollama local model"])
            if answer_mode == "Ollama local model":
                ollama_url = st.text_input("Ollama URL", "http://localhost:11434")
                ollama_model = st.text_input("Ollama model name", "qwen2.5:1.5b")
            else:
                ollama_url, ollama_model = "", ""

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("sources"):
                    with st.expander(f"Sources ({len(msg['sources'])})", expanded=False):
                        for i, src in enumerate(msg["sources"], 1):
                            st.markdown(f"**[{i}] {src['name']}** — page {src['page_no'] or 'N/A'} · score `{src['score']:.3f}`")
                            st.write(src["text"])

        question = st.chat_input("Ask a question about the uploaded documents…")
        if question:
            if not st.session_state.chunks:
                st.warning("Please upload and index at least one document from the sidebar first.")
                return

            st.session_state.messages.append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question)

            with st.chat_message("assistant"):
                try:
                    started = time.perf_counter()
                    with st.status("Retrieving relevant passages…", expanded=True) as status:
                        st.write("1. Query received")
                        sources = retrieve(question, top_k, min_score)
                        st.write("2. TF-IDF memory scan completed")
                        st.write(f"3. Retrieval complete: **{len(sources)}** passage(s) passed score threshold")

                        if not sources:
                            answer = "I couldn't find sufficiently relevant passages in your uploaded files. Try rephrasing or lower the minimum lexical score."
                        elif answer_mode == "Ollama local model":
                            prompt = make_prompt(question, sources, st.session_state.get("prompt_template", DEFAULT_PROMPT))
                            st.write(f"4. Sending context to Ollama model `{ollama_model}`")
                            answer = ollama_generate(prompt, ollama_model, ollama_url)
                        else:
                            answer = "**Relevant passages found** (LLM generation is disabled).\n\n" + "\n\n".join(
                                f"> **[{i}] {s['name']}** — page {s['page_no'] or 'N/A'}\n>\n> {s['text']}"
                                for i, s in enumerate(sources, 1)
                            )
                        status.update(label="Retrieval and response complete", state="complete", expanded=False)

                    st.markdown(answer)
                    elapsed = time.perf_counter() - started
                    with st.expander(f"Sources & retrieval trace ({len(sources)} passages · {elapsed:.2f}s)", expanded=True):
                        for i, src in enumerate(sources, 1):
                            st.markdown(
                                f"<div class='source-box'><b>[{i}] {src['name']}</b><br>"
                                f"<span class='source-meta'>Page {src['page_no'] or 'N/A'} · Chunk {src['chunk_no']+1} · TF-IDF score {src['score']:.3f}</span>"
                                f"<br><br>{src['text']}</div>",
                                unsafe_allow_html=True,
                            )
                        st.caption("Trace: query → session memory chunks → TF-IDF ranking → context assembly → optional Ollama generation.")

                    st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources})
                    st.session_state.events.append({
                        "time": time.strftime("%H:%M:%S"),
                        "question": question,
                        "retrieved": len(sources),
                        "seconds": round(elapsed, 2),
                    })
                except Exception as exc:
                    error_text = f"Request failed: {exc}"
                    st.error(error_text)
                    st.session_state.messages.append({"role": "assistant", "content": error_text})

    elif page == "Documents":
        st.title("Active session documents")
        st.caption("Inspect and manage documents loaded in the current browser memory.")

        if not st.session_state.indexed_docs:
            st.info("No documents indexed in this session yet. Upload files from the sidebar.")
        else:
            if st.button("Clear all documents", type="secondary"):
                st.session_state.indexed_docs = []
                st.session_state.chunks = []
                st.session_state.messages = []
                st.success("All documents cleared from memory.")
                st.rerun()

            for doc in list(st.session_state.indexed_docs):
                c1, c2, c3 = st.columns([6, 2, 1])
                c1.markdown(f"**{doc['name']}**\n\n{doc['chunks']} chunks · loaded at {doc['time']}")
                c2.caption(f"SHA: `{doc['sha256'][:8]}...`")
                if c3.button("Remove", key=f"del_{doc['sha256']}"):
                    st.session_state.indexed_docs = [d for d in st.session_state.indexed_docs if d["sha256"] != doc["sha256"]]
                    st.session_state.chunks = [c for c in st.session_state.chunks if c["sha256"] != doc["sha256"]]
                    st.success(f"Removed {doc['name']}")
                    st.rerun()

    elif page == "Settings":
        st.title("Retrieval & generation settings")
        st.caption("Adjust generation parameters and prompt formats.")
        st.subheader("Default answer prompt")
        prompt_template = st.text_area("Prompt template", DEFAULT_PROMPT, height=240, help="Available placeholders: {context} and {question}.")
        st.session_state["prompt_template"] = prompt_template
        st.subheader("Current configuration")
        st.json({
            "storage": "In-memory session state (per user)",
            "retrieval": "TF-IDF lexical baseline",
            "generation": "Extractive or optional Ollama",
            "supported_files": sorted(SUPPORTED),
            "database_required": False
        })

    elif page == "Activity":
        st.title("Query activity")
        events = st.session_state.events
        if not events:
            st.info("Queries run during this session will appear here.")
        else:
            st.dataframe(list(reversed(events)), use_container_width=True, hide_index=True)
            st.metric("Queries this session", len(events))
            st.metric("Passages retrieved", sum(x["retrieved"] for x in events))

    st.divider()
    st.caption("MechXcel Knowledge Desk · In-memory session demo.")
