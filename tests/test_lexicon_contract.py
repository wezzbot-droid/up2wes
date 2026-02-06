from __future__ import annotations

from pathlib import Path

from uptowes.lexicon_runtime import build_tsquery_from_groups, load_lexicon


def test_lexicon_fixture_loads_and_builds_tsquery() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    lexicon_path = repo_root / "fixtures" / "lexicon_ok.py"

    lex = load_lexicon(str(lexicon_path))
    anchor_token, must_groups, rare_group_ids = lex.expand_query(
        "apendicite complicacoes antibioticoterapia"
    )
    tsquery_str = build_tsquery_from_groups(must_groups)

    assert anchor_token is not None
    assert isinstance(must_groups, list)
    assert isinstance(rare_group_ids, set)
    assert isinstance(tsquery_str, str)
    assert tsquery_str.strip()


def test_retrieval_no_legacy_lexicon_contract_calls() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    retrieval_path = repo_root / "src" / "uptowes" / "retrieval.py"
    content = retrieval_path.read_text(encoding="utf-8")

    assert "build_tsquery_from_groups(q, lex)" not in content
    assert "_relax_gate_rows" not in content
