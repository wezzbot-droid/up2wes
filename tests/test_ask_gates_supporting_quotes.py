from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_ask_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "ask.py"
    spec = importlib.util.spec_from_file_location("ask_quotes_test_mod", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _base_evidence():
    return [
        {
            "chunk_id": "C1",
            "path": "cirurgia/doc.md",
            "locator": "L1-L1",
            "chunk_type": "text",
            "text": "Escala de Alvarado indica pontuação para apendicite.",
            "evidence_text_for_quote": "Escala de Alvarado indica pontuação para apendicite.",
        },
        {
            "chunk_id": "C2",
            "path": "cirurgia/doc.md",
            "locator": "L2-L2",
            "chunk_type": "text",
            "text": "Score maior que 7 pode sugerir cirurgia.",
            "evidence_text_for_quote": "Score maior que 7 pode sugerir cirurgia.",
        },
    ]


def _base_payload():
    return {
        "answer_markdown": "A escala de Alvarado ajuda na estratificação clínica.",
        "citations": [{"chunk_id": "C1", "path": "cirurgia/doc.md", "locator": "L1-L1"}],
        "supporting_quotes": [{"chunk_id": "C1", "quote": "Escala de Alvarado"}],
        "limits": ["A resposta depende apenas dos trechos recuperados."],
        "confidence": "medium",
    }


def test_quotes_required_when_answer_present() -> None:
    mod = _load_ask_module()
    payload = _base_payload()
    payload["supporting_quotes"] = []
    err = mod._validate_answer_payload(payload, _base_evidence())
    assert err is not None
    assert "supporting_quotes" in err


def test_quote_must_be_substring_of_evidence_text() -> None:
    mod = _load_ask_module()
    payload = _base_payload()
    payload["supporting_quotes"] = [{"chunk_id": "C1", "quote": "texto inexistente"}]
    err = mod._validate_answer_payload(payload, _base_evidence())
    assert err is not None
    assert "substring" in err


def test_quote_length_is_hard_limited() -> None:
    mod = _load_ask_module()
    payload = _base_payload()
    payload["supporting_quotes"] = [{"chunk_id": "C1", "quote": "x" * 301}]
    err = mod._validate_answer_payload(payload, _base_evidence())
    assert err is not None
    assert "300" in err


def test_quote_chunk_id_must_exist_in_evidence_pack() -> None:
    mod = _load_ask_module()
    payload = _base_payload()
    payload["supporting_quotes"] = [{"chunk_id": "C999", "quote": "qualquer"}]
    err = mod._validate_answer_payload(payload, _base_evidence())
    assert err is not None
    assert "chunk_id" in err


def test_each_cited_chunk_requires_quote() -> None:
    mod = _load_ask_module()
    payload = _base_payload()
    payload["citations"] = [
        {"chunk_id": "C1", "path": "cirurgia/doc.md", "locator": "L1-L1"},
        {"chunk_id": "C2", "path": "cirurgia/doc.md", "locator": "L2-L2"},
    ]
    payload["supporting_quotes"] = [{"chunk_id": "C1", "quote": "Escala de Alvarado"}]
    err = mod._validate_answer_payload(payload, _base_evidence())
    assert err is not None
    assert "supporting_quotes" in err


def test_insufficient_evidence_allows_empty_citations_and_quotes_and_confidence_low() -> None:
    mod = _load_ask_module()
    payload = {
        "answer_markdown": "EVIDÊNCIA INSUFICIENTE: não há detalhes suficientes no corpus recuperado.",
        "citations": [],
        "supporting_quotes": [],
        "limits": ["Faltam trechos com critérios completos para responder com segurança."],
        "confidence": "low",
    }
    err = mod._validate_answer_payload(payload, _base_evidence())
    assert err is None
