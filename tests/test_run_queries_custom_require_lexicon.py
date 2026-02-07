from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from uptowes.retrieval import Hit


def _load_run_queries_custom_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "run_queries_custom.py"
    spec = importlib.util.spec_from_file_location("run_queries_custom_test_mod", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_queries_custom_require_lexicon_fails_on_legacy_mode(
    monkeypatch,
    local_tmp_path: Path,
) -> None:
    mod = _load_run_queries_custom_module()

    seed_path = local_tmp_path / "seed.jsonl"
    out_path = local_tmp_path / "out.md"
    seed_path.write_text(
        json.dumps(
            {
                "id": "Q-LEGACY",
                "bucket": "A",
                "query": "apendicite aguda",
                "expect_hit": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    repo_root = Path(__file__).resolve().parents[1]
    lexicon_fixture = repo_root / "fixtures" / "lexicon_ok.py"
    monkeypatch.setenv("UPTOWES_LEXICON", str(lexicon_fixture))

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_hybrid_search(*_args, **_kwargs):
        return [
            Hit(
                source_table="chunks_text",
                chunk_id="c1",
                doc_id="DOC_1",
                source_path="md_norm/example.md",
                locator="L1",
                title="Title",
                chunk_type="text",
                text="apendicite aguda com sinal clinico classico",
                score_vec=0.0,
                score_lex=1.0,
                score=1.0,
                lex_mode="STRICT",
            )
        ]

    monkeypatch.setattr(mod, "connect", lambda: FakeConn())
    monkeypatch.setattr(mod, "hybrid_search", fake_hybrid_search)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_queries_custom.py",
            "--seed",
            str(seed_path),
            "--out",
            str(out_path),
            "--lex-only",
            "--require-lexicon",
        ],
    )

    rc = mod.main()
    report = out_path.read_text(encoding="utf-8")

    assert rc == 1
    assert "require_lexicon_gate: `FAIL`" in report


def test_run_queries_custom_requires_scope_for_non_core_area(
    monkeypatch,
    local_tmp_path: Path,
    capsys,
) -> None:
    mod = _load_run_queries_custom_module()

    seed_path = local_tmp_path / "seed_scope.jsonl"
    out_path = local_tmp_path / "out_scope.md"
    seed_path.write_text(
        json.dumps(
            {
                "id": "Q-SCOPE",
                "bucket": "A",
                "query": "apendicite aguda",
                "expect_hit": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("UPTOWES_LEXICON", raising=False)
    monkeypatch.delenv("UPTOWES_AREA", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_queries_custom.py",
            "--seed",
            str(seed_path),
            "--out",
            str(out_path),
            "--lex-only",
            "--require-lexicon",
            "--area",
            "cirurgia",
            "--source-prefix",
            "",
        ],
    )

    rc = mod.main()
    out = capsys.readouterr().out

    assert rc == 2
    assert "requires non-empty source_prefix" in out
