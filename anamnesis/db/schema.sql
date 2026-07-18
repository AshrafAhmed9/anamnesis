-- Anamnesis memory schema for CockroachDB.
-- Embedding dimension is 1024 (Amazon Titan Text Embeddings v2).

CREATE TABLE IF NOT EXISTS episodic_memory (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL,
    role            STRING NOT NULL,               -- 'user' | 'agent'
    content         STRING NOT NULL,
    embedding       VECTOR(1024),
    salience        FLOAT8 NOT NULL DEFAULT 0.5,    -- decays over time, consolidation candidate below threshold
    consolidated    BOOL NOT NULL DEFAULT false,    -- true once folded into a semantic belief
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE VECTOR INDEX IF NOT EXISTS episodic_embedding_idx
    ON episodic_memory (embedding);

CREATE INDEX IF NOT EXISTS episodic_session_idx
    ON episodic_memory (session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS semantic_memory (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    belief            STRING NOT NULL,              -- e.g. "user prefers vegetarian food"
    embedding         VECTOR(1024),
    confidence        FLOAT8 NOT NULL DEFAULT 0.8,
    valid_from        TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to          TIMESTAMPTZ,                  -- NULL = currently believed
    superseded_by     UUID REFERENCES semantic_memory(id),
    source_episodes   UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE VECTOR INDEX IF NOT EXISTS semantic_embedding_idx
    ON semantic_memory (embedding);

CREATE INDEX IF NOT EXISTS semantic_active_idx
    ON semantic_memory (valid_to) STORING (belief, confidence);

CREATE TABLE IF NOT EXISTS memory_audit (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action      STRING NOT NULL,                    -- WRITE / CONSOLIDATE / DECAY / SUPERSEDE / RETRY
    memory_id   UUID,
    reason      STRING,
    metadata    JSONB NOT NULL DEFAULT '{}'::JSONB,
    at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Hash-sharded: `at` is monotonically increasing, so a plain B-tree index
-- on it would concentrate every audit write on one hot range. Sharding
-- distributes writes across ranges while still supporting ORDER BY at DESC.
CREATE INDEX IF NOT EXISTS memory_audit_at_idx
    ON memory_audit (at DESC)
    USING HASH WITH (bucket_count = 8);

CREATE TABLE IF NOT EXISTS ops_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source      STRING NOT NULL,                    -- 'ccloud'
    summary     STRING NOT NULL,
    raw         JSONB NOT NULL DEFAULT '{}'::JSONB,
    at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
