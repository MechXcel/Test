# MechXcel Engineering Utilities

The main page is now a simple landing page; individual applications appear only in the left sidebar to avoid duplicated app listings.

## Applications

- Nozzle Cutout Generator
- Tubesheet Tube Status
- Drawing Revision Comparator
- Knowledge Desk (RAG)

## Run on Windows

Activate the existing virtual environment, then from the repository root run:

```bat
python -m pip install -r requirements.txt
streamlit run app.py
```

## Knowledge Desk (RAG)

The RAG utility is an independent, lightweight Streamlit implementation inspired by the general document-chat workflow of Kotaemon. It is not a feature-complete port and does not include Kotaemon's internal code.

- PDF, TXT and Markdown ingestion
- SQLite persistence under `data/rag_demo.sqlite3`
- TF-IDF lexical retrieval; no embedding model or vector database download
- Source passages, page references and retrieval trace
- Optional generation through a locally running Ollama instance
- Editable prompt and retrieval parameters

Ollama is optional. Choose **Context extract (no LLM)** to test retrieval without an LLM. Scanned PDF OCR, dense vector embeddings, hybrid search, reranking and PDF highlight preview are not included in this lightweight version.
