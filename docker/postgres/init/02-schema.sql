BEGIN;

-- -----------------------------------------------------------------------------
-- 0. Extensions
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;         -- pgvector: vector(1024)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";    -- uuid_generate_v4() fallback
-- gen_random_uuid() is built-in since PostgreSQL 13 — no pgcrypto needed.

-- -----------------------------------------------------------------------------
-- Helper: auto-update `updated_at` on UPDATE (production-grade)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- 1. agents — competition Req #4 (multi-agent roles & mandates)
--    Each row = one agent persona (ICP rep, AI Auditor, Privacy, Coordinator).
-- =============================================================================
CREATE TABLE IF NOT EXISTS agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            VARCHAR(50)  NOT NULL,
    name            VARCHAR(200) NOT NULL,
    role            VARCHAR(50)  NOT NULL,
    mandate         TEXT         NOT NULL,
    system_prompt   TEXT         NOT NULL,
    model_name      VARCHAR(100) NOT NULL DEFAULT 'qwen2.5:7b-instruct',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    agent_metadata  JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- slug must be unique per agent; unique index serves both purposes.
CREATE UNIQUE INDEX IF NOT EXISTS ix_agents_slug
    ON agents (slug);

CREATE INDEX IF NOT EXISTS ix_agents_role
    ON agents (role);

CREATE TRIGGER trg_agents_updated_at
    BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- 2. documents — competition Req #2 (UAE published documents)
--    One row = one source file (law, strategy, guideline, report…).
-- =============================================================================
CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           VARCHAR(500) NOT NULL,
    source_uri      VARCHAR(1000),
    country_code    VARCHAR(3)   NOT NULL DEFAULT 'AE',
    language        VARCHAR(10)  NOT NULL DEFAULT 'en',
    domain          VARCHAR(50)  NOT NULL,
    doc_type        VARCHAR(50)  NOT NULL,
    published_at    DATE,
    version         VARCHAR(50),
    content_hash    VARCHAR(64)  NOT NULL,
    raw_text        TEXT         NOT NULL,
    doc_metadata    JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_documents_content_hash
    ON documents (content_hash);

CREATE INDEX IF NOT EXISTS ix_documents_country_code
    ON documents (country_code);

CREATE INDEX IF NOT EXISTS ix_documents_domain
    ON documents (domain);

CREATE INDEX IF NOT EXISTS ix_documents_doc_type
    ON documents (doc_type);

-- =============================================================================
-- 3. chunks — competition Req #3 (vectorized, distributed KB)
--    Slices of documents with a 1024-dim embedding (bge-m3).
-- =============================================================================
CREATE TABLE IF NOT EXISTS chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID         NOT NULL
                    REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER      NOT NULL,
    content         TEXT         NOT NULL,
    embedding       vector(1024) NOT NULL,
    section         VARCHAR(300),
    token_count     INTEGER,
    chunk_metadata  JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_chunks_document_id
    ON chunks (document_id);

-- Composite index for ordered retrieval inside a document.
CREATE INDEX IF NOT EXISTS ix_chunks_document_order
    ON chunks (document_id, chunk_index);

-- HNSW index for fast approximate nearest-neighbor search.
-- cosine distance is standard for bge-m3 embeddings.
CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- =============================================================================
-- 4. ingestion_jobs — competition Req #3 (ITU reference ingestion pipeline)
--    Tracks each run of extract → structure → embed.
-- =============================================================================
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_path        VARCHAR(1000) NOT NULL,
    status             VARCHAR(30)   NOT NULL DEFAULT 'pending',
    documents_created  INTEGER       NOT NULL DEFAULT 0,
    chunks_created     INTEGER       NOT NULL DEFAULT 0,
    error_message      TEXT,
    started_at         TIMESTAMPTZ,
    finished_at        TIMESTAMPTZ,
    job_metadata       JSONB         NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_status
    ON ingestion_jobs (status);

-- =============================================================================
-- 5. scenarios — competition Req #5 (interactive error scenarios)
-- =============================================================================
CREATE TABLE IF NOT EXISTS scenarios (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug               VARCHAR(100) NOT NULL,
    title              VARCHAR(300) NOT NULL,
    description        TEXT         NOT NULL,
    domain             VARCHAR(50)  NOT NULL,
    is_published       BOOLEAN      NOT NULL DEFAULT FALSE,
    scenario_metadata  JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_scenarios_slug
    ON scenarios (slug);

CREATE INDEX IF NOT EXISTS ix_scenarios_domain
    ON scenarios (domain);

CREATE TRIGGER trg_scenarios_updated_at
    BEFORE UPDATE ON scenarios
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- 6. scenario_events — competition Req #5 (chunked, progressive release)
--    Each event is released after `release_after_seconds` to specific agents.
-- =============================================================================
CREATE TABLE IF NOT EXISTS scenario_events (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id            UUID         NOT NULL
                           REFERENCES scenarios(id) ON DELETE CASCADE,
    sequence               INTEGER      NOT NULL,
    release_after_seconds  INTEGER      NOT NULL DEFAULT 0,
    title                  VARCHAR(300) NOT NULL,
    content                TEXT         NOT NULL,
    target_agent_roles     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    event_metadata         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT uq_scenario_event_seq UNIQUE (scenario_id, sequence)
);

CREATE INDEX IF NOT EXISTS ix_scenario_events_scenario_id
    ON scenario_events (scenario_id);

-- =============================================================================
-- 7. simulation_sessions — one run of a scenario
-- =============================================================================
CREATE TABLE IF NOT EXISTS simulation_sessions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scenario_id        UUID         NOT NULL
                       REFERENCES scenarios(id) ON DELETE RESTRICT,
    status             VARCHAR(30)  NOT NULL DEFAULT 'pending',
    current_sequence   INTEGER      NOT NULL DEFAULT 0,
    human_in_loop      BOOLEAN      NOT NULL DEFAULT TRUE,
    started_at         TIMESTAMPTZ,
    ended_at           TIMESTAMPTZ,
    session_metadata   JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_simulation_sessions_scenario_id
    ON simulation_sessions (scenario_id);

CREATE INDEX IF NOT EXISTS ix_simulation_sessions_status
    ON simulation_sessions (status);

-- =============================================================================
-- 8. messages — competition Req #6 (chain-of-thought stored separately)
--    `thinking_trace` holds the CoT; `content` holds the final answer.
-- =============================================================================
CREATE TABLE IF NOT EXISTS messages (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID        NOT NULL
                     REFERENCES simulation_sessions(id) ON DELETE CASCADE,
    agent_id         UUID
                     REFERENCES agents(id) ON DELETE SET NULL,
    role             VARCHAR(20) NOT NULL,
    content          TEXT        NOT NULL,
    thinking_trace   TEXT,
    sequence         INTEGER     NOT NULL,
    parent_id        UUID
                     REFERENCES messages(id) ON DELETE SET NULL,
    message_metadata JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_messages_session_id
    ON messages (session_id);

CREATE INDEX IF NOT EXISTS ix_messages_session_seq
    ON messages (session_id, sequence);

-- =============================================================================
-- 9. agent_assessments — competition Req #4 (independent assessments)
--    Each agent produces one assessment per event; unique to prevent dupes.
-- =============================================================================
CREATE TABLE IF NOT EXISTS agent_assessments (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID        NOT NULL
                     REFERENCES simulation_sessions(id) ON DELETE CASCADE,
    agent_id         UUID        NOT NULL
                     REFERENCES agents(id) ON DELETE RESTRICT,
    event_sequence   INTEGER     NOT NULL,
    assessment       TEXT        NOT NULL,
    confidence       DOUBLE PRECISION,
    references_used  JSONB       NOT NULL DEFAULT '[]'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_assessment_per_event
        UNIQUE (session_id, agent_id, event_sequence)
);

CREATE INDEX IF NOT EXISTS ix_agent_assessments_session_id
    ON agent_assessments (session_id);

CREATE INDEX IF NOT EXISTS ix_agent_assessments_agent_id
    ON agent_assessments (agent_id);

-- =============================================================================
-- 10. audit_logs — competition Req #6 (audit logging + CoT tracing)
--     Every reasoning step, decision, and policy reference is logged here.
-- =============================================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id           UUID        NOT NULL
                         REFERENCES simulation_sessions(id) ON DELETE CASCADE,
    agent_id             UUID
                         REFERENCES agents(id) ON DELETE SET NULL,
    message_id           UUID
                         REFERENCES messages(id) ON DELETE SET NULL,
    action               VARCHAR(30) NOT NULL,
    reasoning            TEXT,
    policy_references    JSONB       NOT NULL DEFAULT '[]'::jsonb,
    source_attributions  JSONB       NOT NULL DEFAULT '[]'::jsonb,
    confidence           DOUBLE PRECISION,
    audit_metadata       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_audit_logs_session_id
    ON audit_logs (session_id);

CREATE INDEX IF NOT EXISTS ix_audit_logs_agent_id
    ON audit_logs (agent_id);

CREATE INDEX IF NOT EXISTS ix_audit_logs_action
    ON audit_logs (action);

CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at
    ON audit_logs (created_at);

-- =============================================================================
-- 11. policy_gaps — evaluation criterion: gap identification + global mapping
--     Matches: "Gaps and mappings to the global best practices may be
--     described by the agent."
-- =============================================================================
CREATE TABLE IF NOT EXISTS policy_gaps (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id             UUID        NOT NULL
                           REFERENCES simulation_sessions(id) ON DELETE CASCADE,
    agent_id               UUID
                           REFERENCES agents(id) ON DELETE SET NULL,
    gap_type               VARCHAR(30) NOT NULL,
    description            TEXT        NOT NULL,
    affected_domain        VARCHAR(50) NOT NULL,
    global_best_practice   TEXT,
    global_references      JSONB       NOT NULL DEFAULT '[]'::jsonb,
    severity               VARCHAR(20) NOT NULL DEFAULT 'medium',
    status                 VARCHAR(30) NOT NULL DEFAULT 'identified',
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_policy_gaps_session_id
    ON policy_gaps (session_id);

CREATE INDEX IF NOT EXISTS ix_policy_gaps_gap_type
    ON policy_gaps (gap_type);

COMMIT;