from __future__ import annotations

import pytest

from uptowes.lexicon.selector import resolve_lexicon_path


def test_resolve_lexicon_default_area_cirurgia(monkeypatch) -> None:
    monkeypatch.delenv("UPTOWES_AREA", raising=False)
    path = resolve_lexicon_path(area=None, explicit_path=None)
    assert path == "src/uptowes/lexicon/ptbr_surgery_v1.py"


def test_resolve_lexicon_area_core(monkeypatch) -> None:
    monkeypatch.setenv("UPTOWES_AREA", "core")
    path = resolve_lexicon_path(area=None, explicit_path=None)
    assert path == "src/uptowes/lexicon/ptbr_core_v1.py"


def test_resolve_lexicon_explicit_priority_over_area(monkeypatch) -> None:
    monkeypatch.setenv("UPTOWES_AREA", "core")
    explicit = "src/uptowes/lexicon/ptbr_surgery_v1.py"
    path = resolve_lexicon_path(area=None, explicit_path=explicit)
    assert path == explicit


def test_resolve_lexicon_invalid_area_is_auditable(monkeypatch) -> None:
    monkeypatch.delenv("UPTOWES_AREA", raising=False)
    with pytest.raises(ValueError) as exc:
        resolve_lexicon_path(area="invalid-area", explicit_path=None)
    msg = str(exc.value)
    assert "Unknown area=" in msg
    assert "cirurgia" in msg
    assert "core" in msg

