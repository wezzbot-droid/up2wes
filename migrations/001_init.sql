BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS schema_migrations (
  filename TEXT PRIMARY KEY,
  sha1 TEXT NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY,
  source_path TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- chunk_type != table_row
CREATE TABLE IF NOT EXISTS chunks_text (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,

  source_path TEXT NOT NULL,
  locator TEXT NOT NULL,

  section_path TEXT[] NOT NULL,
  title TEXT NOT NULL,

  chunk_type TEXT NOT NULL,
  subtype TEXT NULL,
  tags TEXT[] NULL,

  text_raw TEXT NOT NULL,
  text_canonical TEXT NOT NULL,

  bold_spans JSONB NOT NULL,
  quality_flags TEXT[] NOT NULL,
  priority TEXT NOT NULL,

  raw_sha1 CHAR(40) NOT NULL,
  canonical_sha1 CHAR(40) NOT NULL,

  content_tsv TSVECTOR GENERATED ALWAYS AS (
    to_tsvector('portuguese', coalesce(text_canonical,''))
  ) STORED,

  -- IMPORTANT: pgvector precisa de dimensão fixa
  embedding VECTOR(768) NULL,

  inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- chunk_type == table_row
CREATE TABLE IF NOT EXISTS table_rows (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,

  source_path TEXT NOT NULL,
  locator TEXT NOT NULL,

  section_path TEXT[] NOT NULL,
  title TEXT NOT NULL,

  chunk_type TEXT NOT NULL DEFAULT 'table_row',
  subtype TEXT NULL,
  tags TEXT[] NULL,

  table_id TEXT NOT NULL,
  row_key TEXT NOT NULL,
  cells JSONB NOT NULL,

  text_raw TEXT NOT NULL,
  row_text_canonical TEXT NOT NULL,

  bold_spans JSONB NOT NULL,
  quality_flags TEXT[] NOT NULL,
  priority TEXT NOT NULL,

  raw_sha1 CHAR(40) NOT NULL,
  canonical_sha1 CHAR(40) NOT NULL,

  content_tsv TSVECTOR GENERATED ALWAYS AS (
    to_tsvector('portuguese', coalesce(row_text_canonical,''))
  ) STORED,

  -- IMPORTANT: pgvector precisa de dimensão fixa
  embedding VECTOR(768) NULL,

  inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Basic indexes
CREATE INDEX IF NOT EXISTS idx_chunks_text_doc_id ON chunks_text(doc_id);
CREATE INDEX IF NOT EXISTS idx_table_rows_doc_id ON table_rows(doc_id);

-- Lexical search indexes
CREATE INDEX IF NOT EXISTS idx_chunks_text_tsv ON chunks_text USING GIN(content_tsv);
CREATE INDEX IF NOT EXISTS idx_table_rows_tsv ON table_rows USING GIN(content_tsv);

-- Vector indexes (ivfflat)
CREATE INDEX IF NOT EXISTS idx_chunks_text_embedding
  ON chunks_text USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_table_rows_embedding
  ON table_rows USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

COMMIT;
