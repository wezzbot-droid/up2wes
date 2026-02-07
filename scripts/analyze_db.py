from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from uptowes.db import connect


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--tables",
        nargs="*",
        default=["documents", "chunks_text", "table_rows"],
        help="Tables to ANALYZE (default: documents chunks_text table_rows)",
    )
    args = ap.parse_args()

    tables = [str(t).strip() for t in args.tables if str(t).strip()]
    if not tables:
        print("[FATAL] no tables provided")
        return 2
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t) for t in tables):
        print("[FATAL] invalid table name; allowed pattern: [A-Za-z_][A-Za-z0-9_]*")
        return 2

    with connect() as conn:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(f"ANALYZE {table};")
                print(f"[OK] ANALYZE {table}")
        conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
