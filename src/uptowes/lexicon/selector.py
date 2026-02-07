from __future__ import annotations

import os
from pathlib import Path


DEFAULT_AREA = "cirurgia"
AREA_TO_LEXICON_REL = {
    "cirurgia": "src/uptowes/lexicon/ptbr_surgery_v1.py",
    "core": "src/uptowes/lexicon/ptbr_core_v1.py",
    # Placeholders intentionally not implemented yet.
    "clinica": None,
    "go": None,
    "pediatria": None,
    "preventiva": None,
}


def normalize_area(area: str | None) -> str:
    return (area or "").strip().lower()


def infer_area_from_lexicon_path(path: str) -> str:
    stem = Path(path).stem.strip().lower()
    if stem == "ptbr_surgery_v1":
        return "cirurgia"
    if stem == "ptbr_core_v1":
        return "core"
    return "explicit"


def resolve_lexicon_path(area: str | None, explicit_path: str | None) -> str:
    explicit = (explicit_path or "").strip()
    if explicit:
        return explicit

    chosen_area = normalize_area(area) or normalize_area(os.environ.get("UPTOWES_AREA")) or DEFAULT_AREA
    mapped = AREA_TO_LEXICON_REL.get(chosen_area, "__missing__")
    if mapped == "__missing__":
        options = ", ".join(sorted(AREA_TO_LEXICON_REL.keys()))
        raise ValueError(f"Unknown area='{chosen_area}'. Options: {options}")
    if mapped is None:
        implemented = ", ".join(sorted(k for k, v in AREA_TO_LEXICON_REL.items() if v))
        raise ValueError(
            f"Area='{chosen_area}' is recognized but not implemented yet. Implemented: {implemented}"
        )
    return mapped

