from __future__ import annotations

import json
from pathlib import Path

import pytest

from uptowes.lexicon.build_from_spec import build_lexicon_from_spec
from uptowes.lexicon.qa import load_lexicon_module
from uptowes.validate import validate_lexicon_output, validate_raw_spec


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_validate_raw_spec_fails_on_accented_alias() -> None:
    issues = validate_raw_spec(FIXTURES / "lexicon_spec_accented_alias_bad.json")
    assert issues
    assert any(
        "GATE_ALIAS_KEYS_NORMALIZED failed" in msg and "colelitíase" in msg
        for msg in issues
    )


def test_build_from_spec_sanitizes_and_passes(local_tmp_path: Path) -> None:
    spec = FIXTURES / "lexicon_spec_good.json"
    banned = FIXTURES / "banned_minimal.json"
    out_py = local_tmp_path / "ptbr_core_v1_fixture.py"
    out_report = local_tmp_path / "ptbr_core_v1_build_report.json"

    build_lexicon_from_spec(spec, banned, out_py, out_report)

    issues = validate_lexicon_output(out_py, banned)
    assert issues == []

    mod = load_lexicon_module(out_py)
    aliases = mod["LEX_ALIASES"]
    assert "colelitiase" in aliases
    assert "colelitíase" not in aliases
    assert "thead" not in aliases
    assert "nodulo" not in aliases

    report = json.loads(out_report.read_text(encoding="utf-8"))
    assert report["groups"]["total_emitted"] == 2
    assert report["aliases"]["total_emitted"] >= 4


def test_alias_collision_error_is_auditable(local_tmp_path: Path) -> None:
    spec = FIXTURES / "lexicon_spec_alias_collision_bad.json"
    banned = FIXTURES / "banned_minimal.json"
    out_py = local_tmp_path / "collision_out.py"
    out_report = local_tmp_path / "collision_report.json"

    with pytest.raises(ValueError) as excinfo:
        build_lexicon_from_spec(spec, banned, out_py, out_report)

    msg = str(excinfo.value)
    assert "ALIAS_COLLISION alias=" in msg
    assert "group_a=" in msg and "group_b=" in msg
    assert "source_path=" in msg
    assert "g_a" in msg and "g_b" in msg


def test_group_empty_after_ban_is_hard_error(local_tmp_path: Path) -> None:
    spec = FIXTURES / "lexicon_spec_group_empty_bad.json"
    banned = FIXTURES / "banned_minimal.json"
    out_py = local_tmp_path / "empty_out.py"
    out_report = local_tmp_path / "empty_report.json"

    with pytest.raises(ValueError) as excinfo:
        build_lexicon_from_spec(spec, banned, out_py, out_report)

    msg = str(excinfo.value)
    assert "GROUP_EMPTY_AFTER_BAN" in msg
    assert 'group_id="g_empty"' in msg
    assert "variants_orig_count=" in msg
    assert "removed_tokens_count=" in msg

    report = json.loads(out_report.read_text(encoding="utf-8"))
    assert report["groups"]["groups_failed_empty"]
    assert report["groups"]["groups_failed_empty"][0]["group_id"] == "g_empty"


def test_short_allowlist_is_2_to_3_only(local_tmp_path: Path) -> None:
    spec = FIXTURES / "lexicon_spec_good.json"
    banned = FIXTURES / "banned_minimal.json"
    out_py = local_tmp_path / "allow_out.py"
    out_report = local_tmp_path / "allow_report.json"

    build_lexicon_from_spec(spec, banned, out_py, out_report)

    mod = load_lexicon_module(out_py)
    short_allow = mod["SHORT_TOKEN_ALLOWLIST"]
    assert isinstance(short_allow, set)
    assert short_allow == {"ab", "abc"}
    assert "a" not in short_allow
    assert all(2 <= len(tok) <= 3 for tok in short_allow)


def test_canonical_promotion_when_canonical_banned_but_variants_remain(local_tmp_path: Path) -> None:
    spec = FIXTURES / "lexicon_spec_canonical_promotion.json"
    banned = FIXTURES / "banned_canonical_promotion.json"
    out_py = local_tmp_path / "promotion_out.py"
    out_report = local_tmp_path / "promotion_report.json"

    build_lexicon_from_spec(spec, banned, out_py, out_report)

    mod = load_lexicon_module(out_py)
    assert mod["LEX_GROUPS"]["g_obstrucao"]["canonical"] == "ileo"

    report = json.loads(out_report.read_text(encoding="utf-8"))
    promoted = report.get("canonical_promoted") or []
    assert promoted
    assert promoted[0]["group_id"] == "g_obstrucao"
    assert promoted[0]["from"] == "obstrucao"
    assert promoted[0]["to"] == "ileo"
