from __future__ import annotations

from pathlib import Path

from uptowes.llm.validator import quote_is_from_source


def test_quote_literal_passes() -> None:
    src = "Tabela | **Escala de Alvarado** | Critério"
    q = "**Escala de Alvarado**"
    assert quote_is_from_source(q, src) is True


def test_quote_canon_passes_when_llm_strips_formatting() -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "quote_gate_alvarado_like.md"
    src = fixture.read_text(encoding="utf-8")
    # LLM frequentemente remove pipes/negrito e colapsa espacos
    q = "cada 1 - 4 pontos ALTA"
    assert quote_is_from_source(q, src) is True


def test_quote_rejects_unrelated_text() -> None:
    src = "foo bar baz"
    q = "alvarado 7-10 cirurgia"
    assert quote_is_from_source(q, src) is False


def test_quote_rejects_too_short_after_canon() -> None:
    src = "Apontando o desvio | **1 ponto**\ncada | **1 - 4**\npontos | **ALTA** |"
    q = "pontos"
    assert quote_is_from_source(q, src) is False
