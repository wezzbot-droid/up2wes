# scripts/smoke.py
from __future__ import annotations

import sys
from pathlib import Path

import _bootstrap  # noqa: F401

def main() -> int:
    print("[smoke] python:", sys.executable)
    try:
        import uptowes  # noqa: F401
        p = Path(uptowes.__file__).resolve()
        print("[smoke] import uptowes: OK")
        print("[smoke] uptowes.__file__:", str(p))
        return 0
    except Exception as e:
        print("[smoke][FATAL] import uptowes failed:", repr(e))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
