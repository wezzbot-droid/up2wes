from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List, Tuple

# Bootstrap: permite `from uptowes...` sem precisar instalar pacote
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tqdm import tqdm

from uptowes.db import connect
from uptowes.embeddings import ollama_embed


def fetch_missing(conn, table: str, limit: int) -> List[Tuple[str, str]]:
    if table == "chunks_text":
        sql = (
            "SELECT chunk_id, text_canonical "
            "FROM chunks_text "
            "WHERE embedding IS NULL "
            "ORDER BY chunk_id ASC "
            "LIMIT %s;"
        )
    else:
        sql = (
            "SELECT chunk_id, row_text_canonical "
            "FROM table_rows "
            "WHERE embedding IS NULL "
            "ORDER BY chunk_id ASC "
            "LIMIT %s;"
        )

    with conn.cursor() as cur:
        cur.execute(sql, (limit,))
        return [(r[0], r[1]) for r in cur.fetchall()]


def update_embedding(conn, table: str, chunk_id: str, emb: list[float]) -> None:
    if table == "chunks_text":
        sql = "UPDATE chunks_text SET embedding=%s WHERE chunk_id=%s;"
    else:
        sql = "UPDATE table_rows SET embedding=%s WHERE chunk_id=%s;"
    with conn.cursor() as cur:
        cur.execute(sql, (emb, chunk_id))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", choices=["chunks_text", "table_rows"], required=True)
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--embed-model", default="nomic-embed-text")
    ap.add_argument("--batch-size", type=int, default=200)
    args = ap.parse_args()

    with connect() as conn:
        remaining = max(0, int(args.limit))
        if remaining == 0:
            print("[OK] Nothing to do (--limit=0).")
            return 0

        first_batch = fetch_missing(conn, args.table, min(args.batch_size, remaining))
        if not first_batch:
            print("[OK] No missing embeddings.")
            return 0

        pbar = tqdm(total=remaining, desc=f"embed_backfill:{args.table}", unit="row")
        total_updated = 0
        total_errors = 0
        batch_num = 0

        try:
            while remaining > 0:
                batch_limit = min(args.batch_size, remaining)
                rows = fetch_missing(conn, args.table, batch_limit)
                if not rows:
                    break

                batch_num += 1
                batch_started = time.perf_counter()
                updated_rows = 0
                batch_errors = 0

                for chunk_id, text in rows:
                    try:
                        emb = ollama_embed(text, model=args.embed_model)
                        update_embedding(conn, args.table, chunk_id, emb)
                        updated_rows += 1
                        total_updated += 1
                    except Exception as exc:
                        batch_errors += 1
                        total_errors += 1
                        print(f"[WARN] table={args.table} chunk_id={chunk_id} error={str(exc)[:240]}")

                conn.commit()
                elapsed = max(time.perf_counter() - batch_started, 1e-9)
                rows_per_s = float(updated_rows) / elapsed
                remaining = max(0, remaining - len(rows))
                pbar.update(len(rows))

                print(
                    f"[BATCH {batch_num}] table={args.table} scanned={len(rows)} "
                    f"updated_rows={updated_rows} errors={batch_errors} "
                    f"elapsed_s={elapsed:.2f} rows_per_s={rows_per_s:.2f}"
                )

        except Exception as e:
            conn.rollback()
            print("[FATAL] backfill failed:", str(e)[:900])
            return 1
        finally:
            pbar.close()

    print(
        f"[OK] backfill completed table={args.table} "
        f"updated_total={total_updated} errors_total={total_errors}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
