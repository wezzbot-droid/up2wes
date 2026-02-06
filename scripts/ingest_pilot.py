from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

# Bootstrap: permite `from uptowes...` sem precisar instalar pacote
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psycopg.types.json import Json
from tqdm import tqdm

from uptowes.db import connect
from uptowes.embeddings import ollama_embed


def iter_jsonl(path: Path) -> Iterable[dict]:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        yield json.loads(line)


def pick_doc_ids(chunks_path: Path, limit_docs: int, doc_ids_file: Optional[Path]) -> List[str]:
    if doc_ids_file:
        ids = [ln.strip() for ln in doc_ids_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        ids = sorted(set(ids))
        if not ids:
            raise ValueError("doc_ids_file is empty.")
        return ids[:limit_docs] if limit_docs > 0 else ids

    seen: Set[str] = set()
    for ch in iter_jsonl(chunks_path):
        seen.add(ch["doc_id"])
    ids = sorted(seen)
    return ids[:limit_docs] if limit_docs > 0 else ids


def upsert_document(cur, doc_id: str, source_path: str) -> None:
    cur.execute(
        """
        INSERT INTO documents(doc_id, source_path)
        VALUES (%s, %s)
        ON CONFLICT (doc_id) DO UPDATE
        SET source_path = EXCLUDED.source_path,
            updated_at = now();
        """,
        (doc_id, source_path),
    )


def ingest_text_chunk(cur, ch: dict, embedding: Optional[List[float]]) -> None:
    cur.execute(
        """
        INSERT INTO chunks_text(
          chunk_id, doc_id,
          source_path, locator,
          section_path, title,
          chunk_type, subtype, tags,
          text_raw, text_canonical,
          bold_spans, quality_flags, priority,
          raw_sha1, canonical_sha1,
          embedding
        ) VALUES (
          %s, %s,
          %s, %s,
          %s, %s,
          %s, %s, %s,
          %s, %s,
          %s, %s, %s,
          %s, %s,
          %s
        )
        ON CONFLICT (chunk_id) DO UPDATE SET
          doc_id = EXCLUDED.doc_id,
          source_path = EXCLUDED.source_path,
          locator = EXCLUDED.locator,
          section_path = EXCLUDED.section_path,
          title = EXCLUDED.title,
          chunk_type = EXCLUDED.chunk_type,
          subtype = EXCLUDED.subtype,
          tags = EXCLUDED.tags,
          text_raw = EXCLUDED.text_raw,
          text_canonical = EXCLUDED.text_canonical,
          bold_spans = EXCLUDED.bold_spans,
          quality_flags = EXCLUDED.quality_flags,
          priority = EXCLUDED.priority,
          raw_sha1 = EXCLUDED.raw_sha1,
          canonical_sha1 = EXCLUDED.canonical_sha1,
          embedding = COALESCE(EXCLUDED.embedding, chunks_text.embedding);
        """,
        (
            ch["chunk_id"], ch["doc_id"],
            ch["source"]["path"], ch["source"]["locator"],
            ch["section_path"], ch["title"],
            ch["chunk_type"], ch.get("subtype"), ch.get("tags"),
            ch["text_raw"], ch["text_canonical"],
            Json(ch["bold_spans"]), ch["quality_flags"], ch["priority"],
            ch["hash"]["raw_sha1"], ch["hash"]["canonical_sha1"],
            embedding,
        ),
    )


def ingest_table_row(cur, ch: dict, embedding: Optional[List[float]]) -> None:
    t = ch.get("table") or {}
    cur.execute(
        """
        INSERT INTO table_rows(
          chunk_id, doc_id,
          source_path, locator,
          section_path, title,
          chunk_type, subtype, tags,
          table_id, row_key, cells,
          text_raw, row_text_canonical,
          bold_spans, quality_flags, priority,
          raw_sha1, canonical_sha1,
          embedding
        ) VALUES (
          %s, %s,
          %s, %s,
          %s, %s,
          %s, %s, %s,
          %s, %s, %s,
          %s, %s,
          %s, %s, %s,
          %s, %s,
          %s
        )
        ON CONFLICT (chunk_id) DO UPDATE SET
          doc_id = EXCLUDED.doc_id,
          source_path = EXCLUDED.source_path,
          locator = EXCLUDED.locator,
          section_path = EXCLUDED.section_path,
          title = EXCLUDED.title,
          chunk_type = EXCLUDED.chunk_type,
          subtype = EXCLUDED.subtype,
          tags = EXCLUDED.tags,
          table_id = EXCLUDED.table_id,
          row_key = EXCLUDED.row_key,
          cells = EXCLUDED.cells,
          text_raw = EXCLUDED.text_raw,
          row_text_canonical = EXCLUDED.row_text_canonical,
          bold_spans = EXCLUDED.bold_spans,
          quality_flags = EXCLUDED.quality_flags,
          priority = EXCLUDED.priority,
          raw_sha1 = EXCLUDED.raw_sha1,
          canonical_sha1 = EXCLUDED.canonical_sha1,
          embedding = COALESCE(EXCLUDED.embedding, table_rows.embedding);
        """,
        (
            ch["chunk_id"], ch["doc_id"],
            ch["source"]["path"], ch["source"]["locator"],
            ch["section_path"], ch["title"],
            ch.get("chunk_type") or "table_row", ch.get("subtype"), ch.get("tags"),
            t.get("table_id") or "",
            t.get("row_key") or "",
            Json(t.get("cells") or []),
            ch["text_raw"],
            t.get("row_text_canonical") or ch["text_canonical"],
            Json(ch["bold_spans"]), ch["quality_flags"], ch["priority"],
            ch["hash"]["raw_sha1"], ch["hash"]["canonical_sha1"],
            embedding,
        ),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", required=True, help="Path to dataset/out/chunks.jsonl")
    ap.add_argument("--limit-docs", type=int, default=20, help="How many doc_ids to ingest (deterministic)")
    ap.add_argument("--doc-ids-file", default=None, help="Optional file with doc_ids, one per line")
    ap.add_argument("--max-chunks", type=int, default=0, help="Optional cap of chunks ingested (0 = no cap)")
    ap.add_argument("--embed", action="store_true", help="Compute embeddings during ingest (requires Ollama)")
    ap.add_argument("--embed-model", default="nomic-embed-text")
    ap.add_argument("--commit-every", type=int, default=500, help="Commit every N inserts")
    args = ap.parse_args()

    chunks_path = Path(args.chunks).resolve()
    if not chunks_path.exists():
        print(f"[FATAL] chunks jsonl not found: {chunks_path}")
        return 2

    doc_ids_file = Path(args.doc_ids_file).resolve() if args.doc_ids_file else None
    doc_ids = pick_doc_ids(chunks_path, args.limit_docs, doc_ids_file)
    doc_set = set(doc_ids)

    print(f"[OK] Pilot doc_ids selected: {len(doc_ids)}")
    print("  " + "\n  ".join(doc_ids[:10]) + ("" if len(doc_ids) <= 10 else "\n  ..."))

    inserted = 0
    inserted_text = 0
    inserted_table = 0

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.documents'), to_regclass('public.chunks_text'), to_regclass('public.table_rows');")
            reg = cur.fetchone()
            if not reg or any(x is None for x in reg):
                print("[FATAL] DB tables not found. Run: python scripts/db_migrate.py")
                return 1

        pending = 0
        pbar = tqdm(total=None, desc="ingest", unit="chunk")

        try:
            with conn.cursor() as cur:
                for ch in iter_jsonl(chunks_path):
                    if ch["doc_id"] not in doc_set:
                        continue

                    if args.max_chunks and inserted >= args.max_chunks:
                        break

                    upsert_document(cur, ch["doc_id"], ch["source"]["path"])

                    embedding = None
                    if args.embed:
                        if ch.get("chunk_type") == "table_row" and ch.get("table"):
                            embedding = ollama_embed(ch["table"].get("row_text_canonical") or ch["text_canonical"], model=args.embed_model)
                        else:
                            embedding = ollama_embed(ch["text_canonical"], model=args.embed_model)

                    if ch.get("chunk_type") == "table_row" and ch.get("table"):
                        ingest_table_row(cur, ch, embedding)
                        inserted_table += 1
                    else:
                        ingest_text_chunk(cur, ch, embedding)
                        inserted_text += 1

                    inserted += 1
                    pending += 1
                    pbar.update(1)

                    if pending >= args.commit_every:
                        conn.commit()
                        pending = 0

                if pending:
                    conn.commit()

        except Exception as e:
            conn.rollback()
            print("[FATAL] ingest failed:", str(e)[:900])
            return 1
        finally:
            pbar.close()

    print(f"[OK] inserted_total={inserted} text={inserted_text} table_rows={inserted_table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
