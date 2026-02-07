from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from uptowes.db import connect


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5, help="Top doc_ids by chunk volume")
    args = ap.parse_args()

    with connect() as conn:
        with conn.cursor() as cur:
            queries = [
                ("documents", "SELECT count(*) FROM documents;"),
                ("chunks_text", "SELECT count(*) FROM chunks_text;"),
                ("table_rows", "SELECT count(*) FROM table_rows;"),
                (
                    "chunks_text_canonical_null_or_empty",
                    "SELECT count(*) FROM chunks_text WHERE text_canonical IS NULL OR btrim(text_canonical) = '';",
                ),
                (
                    "table_rows_canonical_null_or_empty",
                    "SELECT count(*) FROM table_rows WHERE row_text_canonical IS NULL OR btrim(row_text_canonical) = '';",
                ),
                ("chunks_text_embedding_not_null", "SELECT count(*) FROM chunks_text WHERE embedding IS NOT NULL;"),
                ("chunks_text_embedding_null", "SELECT count(*) FROM chunks_text WHERE embedding IS NULL;"),
                ("table_rows_embedding_not_null", "SELECT count(*) FROM table_rows WHERE embedding IS NOT NULL;"),
                ("table_rows_embedding_null", "SELECT count(*) FROM table_rows WHERE embedding IS NULL;"),
            ]

            print("[DB_COUNTS]")
            for label, sql in queries:
                cur.execute(sql)
                val = cur.fetchone()[0]
                print(f"{label}={val}")

            cur.execute(
                """
                WITH all_rows AS (
                  SELECT doc_id, count(*)::bigint AS n FROM chunks_text GROUP BY doc_id
                  UNION ALL
                  SELECT doc_id, count(*)::bigint AS n FROM table_rows GROUP BY doc_id
                )
                SELECT doc_id, sum(n)::bigint AS chunks_total
                FROM all_rows
                GROUP BY doc_id
                ORDER BY chunks_total DESC, doc_id ASC
                LIMIT %s;
                """,
                (int(args.top),),
            )
            rows = cur.fetchall()
            print(f"[TOP_DOC_IDS_BY_CHUNKS top={args.top}]")
            if not rows:
                print("(empty)")
            else:
                for doc_id, chunks_total in rows:
                    print(f"doc_id={doc_id} chunks_total={chunks_total}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
