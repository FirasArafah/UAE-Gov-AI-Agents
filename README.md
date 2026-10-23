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

```text
UAE-Gov-AI-Agents/
├── data/
│   ├── raw/                 # Official PDFs (UAE laws & ITU standards)
│   ├── index/               # FAISS vector index & metadata.pkl
│   └── audit_logs/          # Generated RAG audit logs (JSON)
├── kb_store/                # Backup KB store
├── ingest.py                # PDF ingestion, chunking, and FAISS indexing script
├── retrieve_and_generate_2.py # End-to-end RAG retrieval, Ollama generation & audit logging
├── requirements.txt         # Project dependencies
└── README.md                # Project documentation
```
