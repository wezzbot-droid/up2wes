# RUNBOOK Full Rollout (UpToWes v2)

## 0) Pre-checks (must pass)
Use `Windows PowerShell` in repo root `C:\Users\wesle\Desktop\uptowes_v2`.

### 0.1 Activate venv
```powershell
.\.venv\Scripts\Activate.ps1
python -c "import sys; print(sys.executable)"
```
Expected:
- `...\.venv\Scripts\python.exe`

### 0.2 Set required env vars
```powershell
$env:UPTOWES_DB_DSN='postgresql://uptowes:uptowes@localhost:5432/uptowes'
$env:UPTOWES_LEXICON='src\uptowes\lexicon\ptbr_surgery_v1.py'
$env:UPTOWES_RETRIEVAL_REQUIRE_LEXICON='1'
```

### 0.3 Docker/Compose health
```powershell
docker compose ps
```
If this fails with `Access is denied`, follow `docs/DOCKER_COMPOSE_FIX_WINDOWS.md` first.

## 1) Ingest full (513 docs)
Use deterministic selection and idempotent cleanup by `doc_id`:

```powershell
python scripts\ingest_pilot.py --chunks dataset\chunks.jsonl --limit-docs 513
```

Expected logs:
- `selected_doc_ids_sha1=...`
- `deleted_existing: documents=... chunks_text=... table_rows=...`
- `inserted_total: documents=513 ...`

## 2) Backfill full embeddings (checkpoint strategy)
Run in repeated batches. You can stop/resume safely (`WHERE embedding IS NULL`).

Recommended batch command:
```powershell
python scripts\embed_backfill.py --table chunks_text --limit 5000 --batch-size 200
python scripts\embed_backfill.py --table table_rows --limit 5000 --batch-size 200
```

Repeat until null counts are zero (use `scripts/check_db_counts.py`).

Checkpoint validation:
```powershell
python scripts\check_db_counts.py
```

## 3) ANALYZE for planner stats
Option A (script):
```powershell
python scripts\analyze_db.py
```

Option B (psql):
```sql
ANALYZE documents;
ANALYZE chunks_text;
ANALYZE table_rows;
```

## 4) Benchmark / harness gates
### 4.1 Unit tests and gates
```powershell
pytest -q
```

### 4.2 Custom benchmark in strict lexicon-required mode
```powershell
python scripts\run_queries_custom.py --lex-only --require-lexicon
```

Acceptance:
- exit code `0`
- summary line with `PASS total`
- `require_lexicon_violations=0`

## 5) Operational validation queries
```powershell
python scripts\check_db_counts.py
```

Acceptance:
- `chunks_text_canonical_null_or_empty=0`
- `table_rows_canonical_null_or_empty=0`
- embedding null counts trend down to zero after full backfill

## 6) Rollback (known-safe SQL)
Use only in pilot/test rollback scenarios.

### 6.1 Rollback docs/chunks for a known doc_id set
```sql
BEGIN;
DELETE FROM table_rows WHERE doc_id = ANY(ARRAY['DOC_A','DOC_B']);
DELETE FROM chunks_text WHERE doc_id = ANY(ARRAY['DOC_A','DOC_B']);
DELETE FROM documents WHERE doc_id = ANY(ARRAY['DOC_A','DOC_B']);
COMMIT;
```

### 6.2 Rollback embeddings only
```sql
UPDATE chunks_text SET embedding = NULL WHERE embedding IS NOT NULL;
UPDATE table_rows SET embedding = NULL WHERE embedding IS NOT NULL;
```

## 7) Full rollout acceptance checklist
- Pre-checks passed (venv + env vars + compose healthy).
- Full ingest completed with deterministic doc set hash and idempotent cleanup.
- Backfill completed in resumable batches with no fatal errors.
- `ANALYZE` executed.
- `pytest -q` passed.
- `run_queries_custom --lex-only --require-lexicon` passed with zero contract violations.
