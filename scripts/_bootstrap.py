# scripts/_bootstrap.py
# Deterministic bootstrap: ensure src/ is importable for scripts executed as:
#   python scripts\whatever.py
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # repo root
SRC = ROOT / "src"

if SRC.exists():
    s = str(SRC)
    if s not in sys.path:
        sys.path.insert(0, s)
