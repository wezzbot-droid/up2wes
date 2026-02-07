from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


def _load_ask_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "ask.py"
    spec = importlib.util.spec_from_file_location("ask_test_mod", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class _FakeHit:
    source_table: str
    chunk_id: str
    doc_id: str
    source_path: str
    locator: str
    title: str
    chunk_type: str
    text: str
    score_vec: float
    score_lex: float
    score: float
    lex_mode: str


class _FakeConnCtx:
    def __enter__(self):  # noqa: ANN201
        return object()

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False


def test_ask_no_llm_prints_evidence_and_writes_json(
    local_tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _load_ask_module()

    def _fake_hybrid_search(*_args, **kwargs):  # noqa: ANN001
        assert kwargs.get("source_prefix") == "cirurgia/"
        return [
            _FakeHit(
                source_table="chunks_text",
                chunk_id="DOC#L1-L1#1",
                doc_id="DOC",
                source_path="cirurgia/doc.md",
                locator="L1-L1",
                title="Titulo",
                chunk_type="text",
                text="texto 1",
                score_vec=0.0,
                score_lex=1.0,
                score=1.0,
                lex_mode="STRICT_GROUPS",
            ),
            _FakeHit(
                source_table="table_rows",
                chunk_id="DOC#L2-L2#2",
                doc_id="DOC",
                source_path="cirurgia/doc.md",
                locator="L2-L2",
                title="Tabela",
                chunk_type="table_row",
                text="dose 10 mg/kg",
                score_vec=0.0,
                score_lex=0.9,
                score=0.9,
                lex_mode="STRICT_GROUPS",
            ),
        ]

    out_json = local_tmp_path / "ask_no_llm.json"
    monkeypatch.setattr(mod, "connect", lambda: _FakeConnCtx())
    monkeypatch.setattr(mod, "hybrid_search", _fake_hybrid_search)

    rc = mod.main(
        [
            "--q",
            "apendicite alvarado",
            "--area",
            "cirurgia",
            "--no-llm",
            "--out-json",
            str(out_json),
        ]
    )
    assert rc == 0
    assert out_json.exists()

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["question"] == "apendicite alvarado"
    assert len(payload["evidence"]) == 2
    assert payload["evidence"][1]["source_table"] == "table_rows"
    assert "table_row" in payload["evidence"][1]

    stdout = capsys.readouterr().out
    assert "[ASK] area=cirurgia source_prefix=cirurgia/" in stdout
    assert "DOC#L1-L1#1" in stdout

