# SYNORA

**ITU AI for Good Lab Hackathon 2026 — UAE**

Multi-agent system for detecting algorithmic bias in government AI
(visa & Golden Residency screening).

# UAE Government AI Bias & Policy Auditing System (TrustMed RAG)

A localized Retrieval-Augmented Generation (RAG) framework designed for auditing algorithmic bias in UAE screening systems (such as Golden Residency and visa processing), fully compliant with **ITU-T Y.3172** and the **ITU AI Readiness Framework**.

---

## 🚀 Key Features

- **Strict Legal Grounding:** Uses official UAE legislation (e.g., Federal Decree-Law No. 45 of 2021 on Personal Data Protection, AI Charter, National AI Strategy 2031) and ITU international standards.
- **Local RAG Pipeline:** FAISS vector index (`IndexFlatIP`) paired with `sentence-transformers/all-MiniLM-L6-v2` for semantic retrieval.
- **Local LLM Generation:** Powered locally via **Ollama (Llama 3.2)** ensuring complete data privacy and local execution.
- **Auditability & Traceability:** Every generated answer includes exact file citations, Article references, page numbers, and generates automated JSON audit logs.

---

## 📂 Project Structure

````text
## Project Structure

```text
UAE-Gov-AI-Agents/
├── data/
│   ├── kb_manifest.json          # Metadata and configuration for KB documents
│   └── raw_docs/                 # Storage for all raw Arabic and English PDFs
│
├── src/
│   └── synora/                   # Main Application Package
│       ├── db/                   # Database connection and async sessions
│       ├── models/               # SQLAlchemy ORM models (Agents, Chunks, etc.)
│       │
│       ├── rag/                  # Core RAG Engine (Legal & Policy)
│       │   ├── __init__.py
│       │   ├── enums.py          # Enums for LLM models and supported languages
│       │   ├── providers/        # LLM Factory Pattern Implementation
│       │   │   ├── __init__.py
│       │   │   ├── base.py       # Base Interface for LLM providers
│       │   │   ├── ollama_provider.py # Ollama integration for embedding/generation
│       │   │   └── factory.py    # Factory to manage multi-model routing
│       │   ├── vector_store.py   # PostgreSQL pgvector integration (replaces FAISS)
│       │   ├── ingester.py       # Document ingestion, chunking, and database logging
│       │   └── engine.py         # Main RAG Engine API for Agents
│       │
│       └── main.py               # FastAPI application entry point
````
