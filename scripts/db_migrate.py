from __future__ import annotations

import hashlib
import sys
from pathlib import Path

# Bootstrap: permite `from uptowes...` sem precisar instalar pacote
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from uptowes.db import connect


def sha1_file(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest()


def main() -> int:
    migrations_dir = REPO_ROOT / "migrations"
    if not migrations_dir.exists():
        print(f"[FATAL] migrations/ not found at {migrations_dir}")
        return 2

    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        print("[FATAL] No migrations found.")
        return 2

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                  filename TEXT PRIMARY KEY,
                  sha1 TEXT NOT NULL,
                  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            conn.commit()

        applied = 0
        skipped = 0

        for f in files:
            digest = sha1_file(f)

            with conn.cursor() as cur:
                cur.execute("SELECT sha1 FROM schema_migrations WHERE filename=%s;", (f.name,))
                row = cur.fetchone()

            if row and row[0] == digest:
                print(f"[SKIP] {f.name}")
                skipped += 1
                continue

            sql = f.read_text(encoding="utf-8")
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        """
                        INSERT INTO schema_migrations(filename, sha1)
                        VALUES (%s, %s)
                        ON CONFLICT (filename) DO UPDATE SET sha1=EXCLUDED.sha1, applied_at=now();
                        """,
                        (f.name, digest),
                    )
                conn.commit()
                print(f"[APPLY] {f.name}")
                applied += 1
            except Exception as e:
                conn.rollback()
                print(f"[FATAL] migration failed: {f.name}")
                print(str(e)[:800])
                return 1

        print(f"[OK] applied={applied} skipped={skipped}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
