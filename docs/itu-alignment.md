# Alignment with ITU standards

This document maps Mawthuq's components to **ITU-T Y.3172** (*Architectural framework for
machine learning in future networks including IMT-2020*, 06/2019) and to the perspectives of
the **ITU AI Readiness Framework** listed in the hackathon brief.

## ITU-T Y.3172

Y.3172 describes a machine learning pipeline as a chain of logical nodes, managed by a
machine learning function orchestrator (MLFO), with an ML sandbox in which models are trained,
tested and evaluated without affecting the live network. Mawthuq applies the same structure to
a governance setting: the "network" is the set of public institutions, and the sandbox is the
simulated incident.

| Y.3172 element | Definition (summarised) | Mawthuq component |
|---|---|---|
| **SRC** — source | Node that produces the data | National and international documents in `data/knowledge_base/raw/`; scenario events in `data/scenarios/` |
| **C** — collector | Collects data from sources | `rag/ingest.py` reads PDF, HTML and text with page spans; failed jobs are recorded in `ingestion_jobs` |
| **PP** — preprocessor | Prepares data for the model | Text normalisation, sectioning by article, heading or numbered paragraph (Arabic and English), sentence-aware chunking with overlap, removal of contents pages and reference lists, `bge-m3` embeddings into pgvector |
| **M** — model | Produces the output | Role agents (`agents/base.py`) on a local LLM; each retrieves articles and sources the question names, its mandate article, its own domain and then the whole corpus, by embeddings and exact words |
| **P** — policy | Applies policy to the model output | Citation repair and verification (`agents/citations.py`), the output contract (`agents/language.py`), Coordinator synthesis and escalation of conflicts to a human |
| **D** — distributor | Routes output to sinks | API responses, SSE streams, structured assessments and gap records |
| **SINK** — target of the output | Consumes the output | Chat, simulation and audit log pages, gap report, JSON export |
| **MLFO** — ML function orchestrator | Manages and orchestrates pipeline nodes | `agents/orchestrator.py` decides which agents receive each event, whether they work independently or sequentially, and when the Coordinator synthesizes; `scenarios/engine.py` controls event release |
| **ML sandbox** | Environment to train, test and evaluate effects safely | The scenario simulation: agents act on a staged incident; nothing they decide touches a real system |
| Data correlation across multiple sources (REQ-ML-COR-001) | Combine heterogeneous sources | Each answer combines domain-scoped and general retrieval over UAE and international documents, in both languages |

## ITU AI Readiness Framework perspectives

| Perspective | Mawthuq |
|---|---|
| Open data and open-source management | MIT-licensed code; the corpus is public legislation and international instruments; local open-weight models (`qwen2.5`, `bge-m3`) |
| Generative AI content ecosystem | Generated answers are grounded only in retrieved excerpts, cited inline, checked automatically, and flagged when unsupported |
| Contextualization and regional development | Arabic and English editions of UAE law, answers and interface in both languages, agents modelled on UAE institutions |
| AI integration in domains and cross-domain analysis | Government services (immigration), data protection and AI governance meet in one incident; gaps are mapped to cross-domain international practice |
| Human interaction and supervision | Events are released by a human; the Coordinator escalates decisions it cannot settle; every step is reviewable in the audit log |
| AI policy and implementation opportunity identification | Structured policy gap report: type, severity, affected domain, evidence and the global practice that addresses each gap |
| AI for social inclusion | The scenario is a discrimination incident; agents assess proxy variables (postal code, mobile prefix) for indirect nationality bias |
| Digital infrastructure and energy | Runs on a single machine without a GPU or external API; the context window and retrieval depth are bounded and configurable |

## Gap categories

The gap analyst classifies each gap with the `GapType` values used in the database:
`policy`, `legal`, `standards`, `implementation` and `coordination`, ranked `low` to
`critical`. A gap may cite only international excerpts that were retrieved for that report, so
every global example in the report can be traced to a page of a source document.
