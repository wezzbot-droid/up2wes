BEGIN;

-- Accent-insensitive search
CREATE EXTENSION IF NOT EXISTS unaccent;

-- 1) Add columns (NOT generated — generated requires IMMUTABLE expression)
ALTER TABLE chunks_text
  ADD COLUMN IF NOT EXISTS content_tsv_u tsvector;

ALTER TABLE table_rows
  ADD COLUMN IF NOT EXISTS content_tsv_u tsvector;

-- 2) Builder function (can be STABLE; used by triggers)
CREATE OR REPLACE FUNCTION uptowes_make_tsv_u(input_text text)
RETURNS tsvector
LANGUAGE sql
STABLE
STRICT
PARALLEL SAFE
AS $$
  SELECT to_tsvector('portuguese', unaccent(coalesce(input_text, '')));
$$;

-- 3) Trigger function for chunks_text
CREATE OR REPLACE FUNCTION uptowes_chunks_text_tsv_u_trg()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.content_tsv_u := uptowes_make_tsv_u(NEW.text_canonical);
  RETURN NEW;
END;
$$;

-- 4) Trigger function for table_rows
CREATE OR REPLACE FUNCTION uptowes_table_rows_tsv_u_trg()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.content_tsv_u := uptowes_make_tsv_u(NEW.row_text_canonical);
  RETURN NEW;
END;
$$;

-- 5) Create triggers (idempotent)
DROP TRIGGER IF EXISTS trg_chunks_text_tsv_u ON chunks_text;
CREATE TRIGGER trg_chunks_text_tsv_u
BEFORE INSERT OR UPDATE OF text_canonical
ON chunks_text
FOR EACH ROW
EXECUTE FUNCTION uptowes_chunks_text_tsv_u_trg();

DROP TRIGGER IF EXISTS trg_table_rows_tsv_u ON table_rows;
CREATE TRIGGER trg_table_rows_tsv_u
BEFORE INSERT OR UPDATE OF row_text_canonical
ON table_rows
FOR EACH ROW
EXECUTE FUNCTION uptowes_table_rows_tsv_u_trg();

-- 6) Backfill existing rows (safe to rerun)
UPDATE chunks_text
SET content_tsv_u = uptowes_make_tsv_u(text_canonical)
WHERE content_tsv_u IS NULL;

UPDATE table_rows
SET content_tsv_u = uptowes_make_tsv_u(row_text_canonical)
WHERE content_tsv_u IS NULL;

-- 7) Indexes
CREATE INDEX IF NOT EXISTS idx_chunks_text_tsv_u ON chunks_text USING GIN(content_tsv_u);
CREATE INDEX IF NOT EXISTS idx_table_rows_tsv_u  ON table_rows  USING GIN(content_tsv_u);

COMMIT;
