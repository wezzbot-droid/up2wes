from __future__ import annotations

import argparse
import sys
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
        sql = "SELECT chunk_id, text_canonical FROM chunks_text WHERE embedding IS NULL LIMIT %s;"
    else:
        sql = "SELECT chunk_id, row_text_canonical FROM table_rows WHERE embedding IS NULL LIMIT %s;"

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
    ap.add_argument("--commit-every", type=int, default=200)
    args = ap.parse_args()

    with connect() as conn:
        missing = fetch_missing(conn, args.table, args.limit)
        if not missing:
            print("[OK] No missing embeddings.")
            return 0

        pbar = tqdm(total=len(missing), desc=f"embed_backfill:{args.table}", unit="row")
        pending = 0
        try:
            for chunk_id, text in missing:
                emb = ollama_embed(text, model=args.embed_model)
                update_embedding(conn, args.table, chunk_id, emb)
                pending += 1
                pbar.update(1)

                if pending >= args.commit_every:
                    conn.commit()
                    pending = 0

            if pending:
                conn.commit()

        except Exception as e:
            conn.rollback()
            print("[FATAL] backfill failed:", str(e)[:900])
            return 1
        finally:
            pbar.close()

    print("[OK] backfill completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
