# scripts/doctor.py
from __future__ import annotations

import os
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

def _exists(p: Path) -> str:
    return "OK" if p.exists() else "MISSING"

def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]

    print("[doctor] cwd:", os.getcwd())
    print("[doctor] repo_root:", str(repo_root))
    print("[doctor] python:", sys.executable)
    print("[doctor] version:", sys.version.replace("\n", " "))

    venv_py = repo_root / ".venv" / "Scripts" / "python.exe"
    print("[doctor] .venv python:", str(venv_py), f"({_exists(venv_py)})")

    print("[doctor] UPTOWES_LEXICON:", os.getenv("UPTOWES_LEXICON") or "(not set)")
    print("[doctor] UPTOWES_DB_DSN:", os.getenv("UPTOWES_DB_DSN") or "(default)")

    checks = [
        ("scripts/_bootstrap.py", repo_root / "scripts" / "_bootstrap.py"),
        ("src/uptowes/__init__.py", repo_root / "src" / "uptowes" / "__init__.py"),
        ("migrations/001_init.sql", repo_root / "migrations" / "001_init.sql"),
        ("docker-compose.yml", repo_root / "docker-compose.yml"),
    ]
    for label, path in checks:
        print(f"[doctor] check {label}:", _exists(path), "-", str(path))

    try:
        import uptowes  # noqa: F401
        print("[doctor] import uptowes: OK")
        print("[doctor] uptowes.__file__:", str(Path(uptowes.__file__).resolve()))
        return 0
    except Exception as e:
        print("[doctor][FATAL] import uptowes failed:", repr(e))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
