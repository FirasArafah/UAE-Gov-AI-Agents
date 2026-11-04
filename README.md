# Mathuq · موثوق

**Multi-agent AI governance simulation — ITU AI for Good Lab Hackathon 2026 (UAE)**

Mathuq puts AI agents with different institutional mandates into a staged incident and
watches how they reason, disagree and coordinate under real legislation. The reference
scenario, *The Golden Gate Anomaly*, is an AI visa-screening system that starts rejecting
applicants of one nationality at almost three times the baseline rate. Events are
released one at a time, each agent sees only what its role would see, every legal claim
is cited to a retrieved excerpt, and the Coordinator reconciles the independent
assessments into a policy gap report mapped to international practice.

Everything runs locally: no data leaves the machine and no external AI API is used.

---

## What it does

| Hackathon requirement | How Mathuq meets it |
|---|---|
| Knowledge base of national policy, mapped to global practice | 17 files (14 documents) / 2,083 chunks: UAE PDPL (EN + AR), Decree-Law 29/2021 (EN + AR), Cabinet Resolution 65/2022 (EN), National AI Strategy 2031, AI Charter, AI Ethics Guidelines, National Cybersecurity Strategy 2019 (TDRA deck and official summary), Digital Government Strategy 2025; ITU-T Y.3172, ITU AI Ready report, OECD Recommendation on AI (full text), UNESCO Recommendation (EN + AR), EU AI Act. Chunked by article or section, with page numbers, in pgvector. |
| Policy and legal adviser | Every agent answers in Arabic and English from retrieved excerpts only; citations are checked automatically and flagged when an article is not in the sources. |
| Institutional participants | ICP Representative (system operator), AI Auditor, Privacy Consultant (PDPL), Coordinator — each with its own mandate, temperature and retrieval domain. |
| Multi-agent coordination | An orchestrator releases each event to its target agents. They assess **independently**; on events flagged *sequential* each agent receives the previous one's assessment; the **Coordinator synthesizes** every multi-agent event (agreements, conflicting mandates, responsible authority, escalation). |
| Progressive, uneven information | Events are released one at a time; unreleased event text is never sent to the UI; each event reaches only its target agents. |
| Controversy, not only the happy path | Event 5: ICP invokes sovereign and national-security grounds and the PDPL Article (2) government exclusion to refuse the fix, and no source names a body that can suspend the system. |
| Audit logging and chain-of-thought | Every retrieval, reasoning trace, decision, hand-off and gap extraction is stored in `audit_logs` with its sources; per-agent assessments in `agent_assessments`; gaps in `policy_gaps`. |
| Gap identification with global examples | `POST /api/sessions/{id}/gaps` turns the assessments into typed, severity-ranked gaps, each linked only to international excerpts that were actually retrieved. |
| ITU-T Y.3172 and AI Readiness alignment | See [docs/itu-alignment.md](docs/itu-alignment.md). |

## Architecture

```
 SRC            C · PP                    M                         P                       D · SINK
 UAE law,  ─▶  extraction, article  ─▶  role agents on local  ─▶  citation checks,   ─▶  audit log, assessments,
 strategies,   chunking, bge-m3         LLM (qwen2.5 7B),         coordinator           policy gap report,
 ITU, OECD,    embeddings, pgvector     each retrieving its       synthesis, human      UI and JSON export
 UNESCO, EU                             own legal domain first    escalation
                         ▲                                                    │
                         └──────────── Orchestrator (MLFO role) ──────────────┘
```

| Layer | Technology |
|---|---|
| API | FastAPI, SSE streaming |
| Storage | PostgreSQL 17 + pgvector (schema in `docker/postgres/init/`) |
| LLM | Ollama, `qwen2.5:7b-instruct`, 8k context per request |
| Embeddings | `bge-m3` (1024-dim, multilingual Arabic/English) |
| UI | Vanilla JS + Vite (`ui/`) |

## Quick start

Requirements: Docker with Compose, ~10 GB free disk for the models and **at least 10 GB of
memory for Docker** (the 7B model with an 8k context plus the embedding model use ~7 GB). With
less memory, set `OLLAMA_NUM_CTX=4096` in `.env`. A GPU is optional; on CPU each agent answer
takes one to four minutes.

```bash
cp .env.example .env
docker compose up -d postgres ollama
docker compose up ollama-init          # pulls qwen2.5:7b-instruct and bge-m3 (once)
docker compose up -d backend ui
make seed                              # agents + scenarios
make seed-kb                           # ingest data/knowledge_base/raw (takes a while)
```

Open http://localhost:5173 — it lands on **Chat**, the team conversation. API docs: http://localhost:8000/docs.

If port 5432 is taken, set `POSTGRES_PORT` in `.env`.

**NVIDIA GPU (recommended).** Add the GPU override so Ollama runs on the GPU (a 6 GB laptop GPU
answers in seconds instead of minutes):

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

or set `COMPOSE_FILE` in `.env` as shown in `.env.example`. On Windows, give Docker Desktop at
least 10 GB of memory (`memory=10GB` in `%USERPROFILE%\.wslconfig`, then `wsl --shutdown`).

## Using the UI

The interface is available in **English and Arabic** (button at the bottom of the sidebar) and in
light and dark themes; both choices are remembered by the browser. Every address has the form
`http://localhost:5173/<page>`.

- **Chat** (`/`): ask the whole team or one agent. Agents answer in the language of the
  question. In team mode the ICP Representative, AI Auditor and Privacy Consultant assess the
  question independently and the Coordinator writes the final answer; each agent's chain of
  thought streams live in the collapsible panel above it, with its sources and any citation
  warnings. Past conversations are listed under *Recent*.
- **Simulations** (`/simulations`): start a scenario and reopen previous runs.
- **Simulation** (`/simulation/<id>`): release events one at a time, read each agency's
  assessment with its reasoning and sources, the Coordinator's synthesis, and build the policy
  gap report. An event interrupted part-way can be completed from the page.
- **Audit log** (`/audit/<id>`): every retrieval, reasoning trace, decision, hand-off and gap
  report of a run, filterable and exportable as JSON.
- **Agents** (`/agents`): each agency's role, mandate and primary sources, and how a team
  answer is made.
- **Knowledge base** (`/kb`): search the passages the agents retrieve from, and browse the
  national and international documents.

## Running the scenario

Open **Simulations**, start *The Golden Gate Anomaly* and release the events in order. The same
flow is available through the API:

```bash
curl -s localhost:8000/api/scenarios
curl -s -X POST localhost:8000/api/sessions -H 'Content-Type: application/json' -d '{"scenario_id": "<id>"}'
curl -s -X POST localhost:8000/api/sessions/<session>/start
curl -s -X POST localhost:8000/api/sessions/<session>/advance -H 'Content-Type: application/json' -d '{"auto_run": true, "language": "en"}'
curl -s -X POST "localhost:8000/api/sessions/<session>/gaps?language=en"
curl -s localhost:8000/api/sessions/<session>/audit
```

Repeat `advance` for each event; `language` may be `en` or `ar`.

| # | Event | Agents | Flow |
|---|---|---|---|
| 1 | Anomaly reported | Auditor | single |
| 2 | Model audit request | Privacy → ICP | sequential: ICP answers Privacy's findings |
| 3 | Proxy variables discovered | Privacy, Auditor | independent + synthesis |
| 4 | Coordinated response decision | Coordinator | decides on the specialists' earlier assessments |
| 5 | Contested authority (controversy) | ICP, Privacy, Auditor | independent + synthesis |
| 6 | Policy gap report | Auditor, Privacy | independent + synthesis |

## Knowledge base export (ITU reference layout)

`make export-kb` writes the knowledge base in the layout of the ITU AI Readiness reference code
([CrashingGuru/ITUAIReadiness](https://github.com/CrashingGuru/ITUAIReadiness),
`simulation/server/knowledge`) to `kb_export/`:

- `InputDocs/UAE_Laws_Regulations`, `InputDocs/UAE_AI_Strategies`,
  `InputDocs/International_References`: the source documents, which the reference `ingest.py`
  ingests as they are (the folder becomes `document_category`)
- `chunks.jsonl`: every indexed chunk with the reference metadata (`source_file`,
  `source_type`, `country`, `chunk_index`, `total_chunks`, `ingested_at`, `document_category`)
  plus `title`, `section` (article), `page`, `language`, `domain` and `doc_type`
- `manifest.json`: per-document coverage and the chunking and embedding settings

Add `--with-embeddings` to the command in the Makefile to include the bge-m3 vectors.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | DB, LLM and loaded agents |
| GET | `/api/agents` | Agent roster |
| GET | `/api/scenarios` | Published scenarios |
| GET/POST | `/api/sessions` | List / create sessions |
| GET | `/api/chats` | Recent free-chat conversations |
| POST | `/api/sessions/{id}/start` | Start a scenario session |
| POST | `/api/sessions/{id}/advance` | Release the next event and run the coordination protocol |
| POST | `/api/sessions/{id}/events/{seq}/run` | Re-run a released event that has no recorded assessments |
| GET | `/api/sessions/{id}/timeline` | Events, with text only once released |
| GET | `/api/sessions/{id}/messages` | Event and agent messages |
| GET | `/api/sessions/{id}/assessments` | Structured per-agent assessments |
| GET/POST | `/api/sessions/{id}/gaps` | Read / build the policy gap report |
| GET | `/api/sessions/{id}/audit` | Full audit trail |
| POST | `/api/sessions/{id}/stream` | Free-chat answers over SSE |
| GET | `/api/documents` | Knowledge base coverage |
| GET | `/api/kb/search?q=` | Run retrieval directly |

## Development

```bash
make build-dev          # image with pytest/ruff (INSTALL_DEV=true)
make test-fast          # unit + API tests, no LLM
make test-all           # includes the full six-event scenario against the LLM (slow)
```

- Scenario JSON lives in `data/scenarios/`; `make seed` reloads it with `--force`.
- `python -m synora.cli.seed_knowledge_base --refresh-metadata` corrects document titles and
  classification without re-embedding.
- The database schema lives in `docker/postgres/init/*.sql`. Docker Compose applies it when the
  database volume is created, and `alembic upgrade head` applies the same files to an empty
  database outside Docker (an existing one is only stamped).
- Fast tests use a separate `synora_test` database that they create and seed themselves.

```
src/synora/
  agents/      base agent, orchestrator, gap analyst, citation checks, LLM client
  api/         FastAPI routes
  audit/       audit logger
  rag/         ingestion, embeddings, pgvector store and retriever
  scenarios/   scenario loader and event engine
  cli/         seeding commands
ui/src/        pages and shared rendering
data/          knowledge base sources and scenarios
```

## Known limitations

- On CPU a full six-event run takes roughly 45–60 minutes; on a 6 GB laptop GPU, a few minutes.
- The law establishing ICP (Federal Decree-Law No. 14 of 2021) is not in the knowledge base:
  the UAE legislation portal does not allow automated downloads. Save it from
  uaelegislation.gov.ae into `data/knowledge_base/raw` and run `make seed-kb`.
- Sessions are kept as immutable audit records; there is no delete endpoint.

## License

MIT — see [LICENSE](LICENSE).
