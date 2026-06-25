CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(200) NOT NULL,
    type VARCHAR(30) NOT NULL,
    summary TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8,
    source_message_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    memory_metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT ck_memories_type CHECK (type IN ('preferences', 'info', 'extra')),
    CONSTRAINT ck_memories_status CHECK (
        status IN ('active', 'superseded', 'deleted', 'uncertain')
    ),
    CONSTRAINT ck_memories_confidence CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE TABLE IF NOT EXISTS memory_embeddings (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(200) NOT NULL,
    memory_id VARCHAR(36) NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_memories_user_id
    ON memories(user_id);

CREATE INDEX IF NOT EXISTS ix_memories_type
    ON memories(type);

CREATE INDEX IF NOT EXISTS ix_memories_status
    ON memories(status);

CREATE INDEX IF NOT EXISTS ix_memories_user_status_type
    ON memories(user_id, status, type);

CREATE INDEX IF NOT EXISTS ix_memory_embeddings_user_id
    ON memory_embeddings(user_id);

CREATE INDEX IF NOT EXISTS ix_memory_embeddings_memory_id
    ON memory_embeddings(memory_id);

CREATE INDEX IF NOT EXISTS ix_memory_embeddings_vector_hnsw
    ON memory_embeddings
    USING hnsw (embedding vector_cosine_ops);
