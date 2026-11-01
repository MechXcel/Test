"""Lightweight Streamlit document-RAG demo inspired by Kotaemon's user experience.

This is an independent implementation, not a port of Kotaemon's internal code.
Optimized for a small Windows machine: SQLite + TF-IDF retrieval by default and
optional Ollama generation. It ingests text-based PDFs and TXT/MD files.
"""
TITLE = "Knowledge Desk (RAG)"
ICON = "📚"
DESCRIPTION = "Chat with your documents, inspect retrieved passages, and test a local RAG workflow."

from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import streamlit as st
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

APP_TITLE = "MechXcel Knowledge Desk"
# Keep persistent RAG data in the repository-level data directory.
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "rag_demo.sqlite3"
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
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, collection TEXT NOT NULL,
        sha256 TEXT NOT NULL, added_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(sha256, collection))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL, chunk_no INTEGER NOT NULL,
        page_no INTEGER, text TEXT NOT NULL,
        FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE)""")
    conn.commit()
    return conn


def extract_file(name: str, data: bytes) -> list[tuple[int | None, str]]:
    ext = Path(name).suffix.lower()
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


def add_document(name: str, data: bytes, collection: str, chunk_size: int, overlap: int) -> tuple[bool, str]:
    digest = hashlib.sha256(data).hexdigest()
    conn = db()
    try:
        existing = conn.execute("SELECT id FROM documents WHERE sha256=? AND collection=?", (digest, collection)).fetchone()
        if existing:
            return False, f"Already indexed in collection '{collection}'."
        pages = extract_file(name, data)
        if not pages:
            return False, "No extractable text found. This may be a scanned PDF; OCR is not included in this lightweight demo."
        cur = conn.execute("INSERT INTO documents(name, collection, sha256) VALUES(?,?,?)", (name, collection, digest))
        doc_id = cur.lastrowid
        chunk_no = 0
        for page_no, page_text in pages:
            for chunk in split_text(page_text, chunk_size, overlap):
                conn.execute("INSERT INTO chunks(document_id, chunk_no, page_no, text) VALUES(?,?,?,?)",
                             (doc_id, chunk_no, page_no, chunk))
                chunk_no += 1
        conn.commit()
        return True, f"Indexed {chunk_no} chunks from {name}."
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def collections() -> list[str]:
    conn = db()
    try:
        rows = conn.execute("SELECT DISTINCT collection FROM documents ORDER BY collection").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def list_docs(collection: str | None = None) -> list[sqlite3.Row]:
    conn = db()
    try:
        if collection:
            return conn.execute("""SELECT d.id,d.name,d.collection,d.added_at,COUNT(c.id) AS chunks
                FROM documents d LEFT JOIN chunks c ON c.document_id=d.id
                WHERE d.collection=? GROUP BY d.id ORDER BY d.added_at DESC""", (collection,)).fetchall()
        return conn.execute("""SELECT d.id,d.name,d.collection,d.added_at,COUNT(c.id) AS chunks
            FROM documents d LEFT JOIN chunks c ON c.document_id=d.id
            GROUP BY d.id ORDER BY d.added_at DESC""").fetchall()
    finally:
        conn.close()


def delete_document(doc_id: int) -> None:
    conn = db()
    try:
        conn.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.commit()
    finally:
        conn.close()


def retrieve(query: str, collection: str, top_k: int, min_score: float) -> list[dict[str, Any]]:
    conn = db()
    try:
        rows = conn.execute("""SELECT c.id,c.chunk_no,c.page_no,c.text,d.name,d.collection,d.id AS doc_id
            FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.collection=?""", (collection,)).fetchall()
    finally:
        conn.close()
    if not rows:
        return []
    corpus = [r["text"] for r in rows]
    # Lightweight lexical retrieval, no model download or vector DB required.
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=60000)
    matrix = vectorizer.fit_transform(corpus + [query])
    scores = cosine_similarity(matrix[-1], matrix[:-1]).ravel()
    ranked = scores.argsort()[::-1][:top_k]
    results = []
    for ix in ranked:
        score = float(scores[ix])
        if score < min_score:
            continue
        r = rows[int(ix)]
        results.append({"score": score, "chunk_id": r["id"], "chunk_no": r["chunk_no"],
                        "page_no": r["page_no"], "text": r["text"], "name": r["name"],
                        "collection": r["collection"], "doc_id": r["doc_id"]})
    return results


def ollama_generate(prompt: str, model: str, base_url: str, timeout: int = 120) -> str:
    import requests
    url = base_url.rstrip("/") + "/api/generate"
    response = requests.post(url, json={"model": model, "prompt": prompt, "stream": False,
                                        "options": {"temperature": 0.1, "num_ctx": 2048}}, timeout=timeout)
    response.raise_for_status()
    return str(response.json().get("response", "")).strip()


def make_prompt(question: str, sources: list[dict[str, Any]], template: str) -> str:
    context = "\n\n".join(
        f"[Source {i+1}: {s['name']}, page {s['page_no'] or 'N/A'}, chunk {s['chunk_no']+1}]\n{s['text']}"
        for i, s in enumerate(sources)
    )
    return template.replace("{context}", context).replace("{question}", question)

DEFAULT_PROMPT = """You are a careful document assistant. Answer the question using only the supplied context.
If the context does not contain enough information, say so clearly. Do not invent code clauses, values, or citations.
Cite claims with [Source 1], [Source 2], etc. Sources are shown below.

CONTEXT:
{context}

QUESTION:
{question}

ANSWER:"""


def run():
    # Initial DB setup
    with db() as _conn:
        pass

    # Sidebar: branding, data ingestion and configuration
    with st.sidebar:
        st.markdown(f"<div class='brand-title'>📚 {APP_TITLE}</div>", unsafe_allow_html=True)
        st.markdown("<div class='brand-sub'>Local document RAG · Streamlit edition</div>", unsafe_allow_html=True)
        page = st.radio("Workspace", ["Chat", "Documents", "Settings", "Activity"], label_visibility="collapsed", key="rag_workspace")
        st.divider()
        st.subheader("Knowledge collection")
        current_collections = collections()
        collection_choice = st.selectbox("Select collection", current_collections + ["+ New collection"], key="collection_pick")
        if collection_choice == "+ New collection":
            new_collection = st.text_input("New collection name", placeholder="e.g. ASME VIII Demo", key="new_collection")
            if st.button("Create / select", use_container_width=True) and new_collection.strip():
                st.session_state["active_collection"] = new_collection.strip()
                st.rerun()
            active_collection = st.session_state.get("active_collection", "General")
        else:
            active_collection = collection_choice
            st.session_state["active_collection"] = active_collection
        st.caption(f"Active collection: **{active_collection}**")
        st.divider()
        st.subheader("Add documents")
        uploaded = st.file_uploader("Drop PDF, TXT or Markdown", type=sorted(SUPPORTED), accept_multiple_files=True)
        with st.expander("Indexing options", expanded=False):
            chunk_size = st.slider("Chunk size (characters)", 400, 1600, 900, 100)
            overlap = st.slider("Chunk overlap", 0, 300, 140, 20)
        if st.button("Index uploaded files", type="primary", use_container_width=True, disabled=not uploaded):
            with st.spinner("Extracting text and indexing chunks..."):
                for file in uploaded or []:
                    try:
                        ok, msg = add_document(file.name, file.getvalue(), active_collection, chunk_size, overlap)
                        (st.success if ok else st.info)(msg)
                    except Exception as exc:
                        st.error(f"{file.name}: {exc}")
            st.rerun()
        st.divider()
        st.caption("Lightweight mode uses SQLite + TF-IDF retrieval. No embedding model download required.")

    # Defaults/session state
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("events", [])
    st.session_state.setdefault("last_sources", [])

    if page == "Chat":
        top_left, top_right = st.columns([7, 2])
        with top_left:
            st.title("Chat with your documents")
            st.caption(f"Collection: **{active_collection}** · Ask questions grounded in your indexed files.")
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

        question = st.chat_input("Ask a question about the selected collection…")
        if question:
            st.session_state.messages.append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                try:
                    started = time.perf_counter()
                    with st.status("Retrieving relevant passages…", expanded=True) as status:
                        st.write("1. Query received")
                        sources = retrieve(question, active_collection, top_k, min_score)
                        st.write(f"2. SQLite read: searched indexed chunks in **{active_collection}**")
                        st.write(f"3. Retrieval complete: **{len(sources)}** passage(s) passed the score threshold")
                        if not sources:
                            answer = "I couldn't find sufficiently relevant passages in this collection. Try different wording or lower the minimum lexical score."
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
                            st.markdown(f"<div class='source-box'><b>[{i}] {src['name']}</b><br><span class='source-meta'>Page {src['page_no'] or 'N/A'} · Chunk {src['chunk_no']+1} · TF-IDF score {src['score']:.3f}</span><br><br>{src['text']}</div>", unsafe_allow_html=True)
                        st.caption("Trace: query → SQLite chunks → TF-IDF ranking → context assembly → optional Ollama generation.")
                    st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources})
                    st.session_state.events.append({"time": time.strftime("%H:%M:%S"), "question": question, "collection": active_collection, "retrieved": len(sources), "seconds": round(elapsed, 2)})
                except Exception as exc:
                    error_text = f"Request failed: {exc}"
                    st.error(error_text)
                    st.session_state.messages.append({"role": "assistant", "content": error_text})

    elif page == "Documents":
        st.title("Document library")
        st.caption("Manage the files indexed into each collection.")
        filter_collection = st.selectbox("Show collection", ["All collections"] + collections())
        docs = list_docs(None if filter_collection == "All collections" else filter_collection)
        if not docs:
            st.info("No documents indexed yet. Upload a PDF, TXT, or Markdown file from the sidebar.")
        else:
            for d in docs:
                c1, c2, c3 = st.columns([6, 2, 1])
                c1.markdown(f"**{d['name']}**\n\n`{d['collection']}` · {d['chunks']} chunks · added {d['added_at']}")
                c2.caption(f"Document ID: {d['id']}")
                if c3.button("Delete", key=f"del_{d['id']}"):
                    delete_document(int(d["id"]))
                    st.success(f"Deleted {d['name']}")
                    st.rerun()

    elif page == "Settings":
        st.title("Retrieval & generation settings")
        st.caption("Settings are deliberately visible and easy to change for demonstrations.")
        st.subheader("Default answer prompt")
        prompt_template = st.text_area("Prompt template", DEFAULT_PROMPT, height=240, help="Available placeholders: {context} and {question}.")
        st.session_state["prompt_template"] = prompt_template
        st.subheader("Current configuration")
        st.json({"UI": "Streamlit", "metadata_and_chunks": "SQLite", "retrieval": "TF-IDF lexical baseline", "generation": "Extractive or optional Ollama", "supported_files": sorted(SUPPORTED), "vector_database": False, "embedding_model": False})
        st.warning("This starter is a lightweight RAG demo, not a feature-complete Kotaemon port. It currently does not include vector embeddings, hybrid search, reranking, OCR, multimodal parsing, GraphRAG, PDF highlighting or multi-user authentication.")

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
    st.caption("MechXcel Knowledge Desk · Independent Streamlit demo inspired by public RAG UI concepts in Kotaemon. Not affiliated with the Kotaemon project.")
