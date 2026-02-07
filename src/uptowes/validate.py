# src/uptowes/validate.py
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from jsonschema import Draft202012Validator

from uptowes.lexicon.qa import (
    Issue,
    iter_dataset_tokens,
    load_lexicon_module,
    validate_lexicon,
)
from uptowes.lexicon_runtime import norm_text as runtime_norm_text


REQUIRE_LEXICON_ALLOWED_MODES = {"STRICT_GROUPS", "RELAX_GROUPS", "GROUPS_QUERY_POOR", "NONE"}
REQUIRE_LEXICON_BLOCKED_MODES = {"STRICT", "RELAX", "LEGACY_NO_LEXICON"}


def _safe_print(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.buffer.write((msg + "\n").encode(enc, errors="backslashreplace"))


def validate_lex_mode_contract(lex_mode: str, require_lexicon: bool) -> str | None:
    mode = str(lex_mode or "").strip().upper()
    if not require_lexicon:
        return None
    if mode in REQUIRE_LEXICON_ALLOWED_MODES:
        return None
    if mode in REQUIRE_LEXICON_BLOCKED_MODES:
        return f"legacy lex_mode blocked under require-lexicon: {mode}"
    return f"unknown lex_mode under require-lexicon: {mode or '<empty>'}"


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_banned_sets(banned_path: Path) -> Dict[str, set[str]]:
    obj = _load_json(banned_path)
    cats = dict(obj.get("banned_categories") or {})

    def _tokens(name: str) -> set[str]:
        raw = ((cats.get(name) or {}).get("tokens") or [])
        out: set[str] = set()
        for t in raw:
            tok = runtime_norm_text(str(t or ""))
            if tok:
                out.add(tok)
        return out

    stopwords = _tokens("stopwords_pt")
    html = _tokens("html_artifacts")
    units = _tokens("units_numbers")
    ambiguous = _tokens("ambiguous_cross_area")
    return {
        "stopwords_pt": stopwords,
        "html_artifacts": html,
        "units_numbers": units,
        "ambiguous_cross_area": ambiguous,
        "hard_banned_union": stopwords | html | units,
    }


def _iter_group_tokens(lex_groups: Dict[str, Any]) -> Iterable[Tuple[str, str]]:
    for gid, g in (lex_groups or {}).items():
        g_obj = g if isinstance(g, dict) else {}
        canonical = str(g_obj.get("canonical") or "")
        if canonical:
            yield canonical, f"canonical:{gid}"
        for v in (g_obj.get("variants") or []):
            tok = str(v or "")
            if tok:
                yield tok, f"variant:{gid}"


def validate_raw_spec(spec_or_path: Dict[str, Any] | Path) -> List[str]:
    spec_obj = _load_json(spec_or_path) if isinstance(spec_or_path, Path) else dict(spec_or_path or {})
    issues: List[str] = []
    aliases = dict(spec_obj.get("LEX_ALIASES") or {})
    groups = dict(spec_obj.get("LEX_GROUPS") or {})

    for alias in aliases.keys():
        alias_s = str(alias or "")
        normalized = runtime_norm_text(alias_s)
        if alias_s != normalized:
            issues.append(
                f"GATE_ALIAS_KEYS_NORMALIZED failed: alias_key={alias_s!r} normalized={normalized!r}"
            )

    for token, context in _iter_group_tokens(groups):
        normalized = runtime_norm_text(token)
        if token != normalized:
            issues.append(
                f"GATE_VARIANTS_NORMALIZED failed: token={token!r} normalized={normalized!r} context={context}"
            )
    return issues


def validate_lexicon_output(lexicon_path: Path, banned_path: Path) -> List[str]:
    mod = load_lexicon_module(lexicon_path)
    lex_groups = mod["LEX_GROUPS"]
    aliases = mod["LEX_ALIASES"]
    short_allowlist = mod["SHORT_TOKEN_ALLOWLIST"]
    banned = _collect_banned_sets(banned_path)
    issues: List[str] = []

    if not isinstance(aliases, dict):
        return ["GATE_ALIAS_KEYS_NORMALIZED failed: LEX_ALIASES is not dict"]
    if not isinstance(lex_groups, dict):
        return ["GATE_VARIANTS_NORMALIZED failed: LEX_GROUPS is not dict"]
    if not isinstance(short_allowlist, set):
        return ["GATE_SHORT_TOKEN_ALLOWLIST_DERIVED failed: SHORT_TOKEN_ALLOWLIST is not set"]

    # GATE_ALIAS_KEYS_NORMALIZED
    for alias in aliases.keys():
        alias_s = str(alias or "")
        normalized = runtime_norm_text(alias_s)
        if alias_s != normalized:
            issues.append(
                f"GATE_ALIAS_KEYS_NORMALIZED failed: alias_key={alias_s!r} normalized={normalized!r}"
            )

    # GATE_VARIANTS_NORMALIZED + GATE_GROUP_VARIANTS_NONEMPTY
    for gid, g in lex_groups.items():
        g_obj = g if isinstance(g, dict) else {}
        canonical = str(g_obj.get("canonical") or "")
        variants = [str(v or "") for v in (g_obj.get("variants") or [])]
        if not variants:
            issues.append(f"GATE_GROUP_VARIANTS_NONEMPTY failed: group_id={gid!r} variants=[]")
        if canonical != runtime_norm_text(canonical):
            issues.append(
                f"GATE_VARIANTS_NORMALIZED failed: canonical={canonical!r} group_id={gid!r}"
            )
        for v in variants:
            if v != runtime_norm_text(v):
                issues.append(
                    f"GATE_VARIANTS_NORMALIZED failed: variant={v!r} group_id={gid!r}"
                )

    # GATE_NO_BANNED_TOKENS + GATE_NO_AMBIGUOUS_TOKENS_TEMP
    for tok, context in _iter_group_tokens(lex_groups):
        norm_tok = runtime_norm_text(tok)
        if norm_tok in banned["hard_banned_union"]:
            issues.append(
                f"GATE_NO_BANNED_TOKENS failed: token={norm_tok!r} context={context}"
            )
        if norm_tok in banned["ambiguous_cross_area"]:
            issues.append(
                f"GATE_NO_AMBIGUOUS_TOKENS_TEMP failed: token={norm_tok!r} context={context}"
            )
    for alias in aliases.keys():
        norm_alias = runtime_norm_text(str(alias or ""))
        if norm_alias in banned["hard_banned_union"]:
            issues.append(
                f"GATE_NO_BANNED_TOKENS failed: token={norm_alias!r} context=alias_key"
            )
        if norm_alias in banned["ambiguous_cross_area"]:
            issues.append(
                f"GATE_NO_AMBIGUOUS_TOKENS_TEMP failed: token={norm_alias!r} context=alias_key"
            )

    # GATE_SHORT_TOKEN_ALLOWLIST_DERIVED
    expected_short = sorted({str(k) for k in aliases.keys() if 2 <= len(str(k)) <= 3})
    actual_short = sorted({str(t) for t in short_allowlist})
    if expected_short != actual_short:
        issues.append(
            f"GATE_SHORT_TOKEN_ALLOWLIST_DERIVED failed: expected={expected_short!r} actual={actual_short!r}"
        )

    return issues


def load_schema(schema_path: Path) -> Dict[str, Any]:
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_chunks(chunks: Iterable[Dict[str, Any]], schema: Dict[str, Any]) -> List[Tuple[str, str]]:
    v = Draft202012Validator(schema)
    errors: List[Tuple[str, str]] = []
    for ch in chunks:
        for e in v.iter_errors(ch):
            errors.append((ch.get("chunk_id", "<no_chunk_id>"), e.message))
    return errors


_T_STAGE_CRITICAL_RE = re.compile(r"\bt\s*[23](?:[a-z])?\b", re.IGNORECASE)
_TABLE_DEGRADED_FLAGS = {
    "TABLE_UNPARSED",
    "TABLE_DEGRADED",
    "TABLE_CRITICAL_DEGRADED",
    "TABLE_EMPTY_CELL",
}
_ROW_KEY_CRITICAL_RE = re.compile(r"^t[23][a-z]?$", re.IGNORECASE)


def _norm_text(s: Any) -> str:
    txt = unicodedata.normalize("NFKD", str(s or ""))
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    txt = re.sub(r"[^a-z0-9]+", " ", txt.lower())
    return re.sub(r"\s+", " ", txt).strip()


def _is_table_row_critical_t2_t3(chunk: Dict[str, Any]) -> bool:
    if str(chunk.get("chunk_type") or "") != "table_row":
        return False

    table = chunk.get("table") if isinstance(chunk.get("table"), dict) else {}
    qflags = {str(f).strip().upper() for f in (chunk.get("quality_flags") or [])}
    if {"TABLE_CRITICAL", "TABLE_T2_T3_CRITICAL"}.intersection(qflags):
        return True

    row_key_norm = _norm_text(table.get("row_key") or "").replace(" ", "")
    return bool(_ROW_KEY_CRITICAL_RE.match(row_key_norm))


def _critical_table_row_issues(chunk: Dict[str, Any]) -> List[str]:
    issues: List[str] = []

    qflags = {str(f).strip().upper() for f in (chunk.get("quality_flags") or [])}
    degraded_present = sorted(_TABLE_DEGRADED_FLAGS.intersection(qflags))
    if degraded_present:
        issues.append(f"degradation flags present: {', '.join(degraded_present)}")

    table = chunk.get("table")
    if not isinstance(table, dict):
        issues.append("table payload missing or invalid")
        return issues

    cells = table.get("cells")
    if not isinstance(cells, list) or not cells:
        issues.append("table.cells missing or empty")
        return issues

    if len(cells) < 2:
        issues.append("table.cells has less than 2 columns")

    non_empty_values: List[str] = []
    stage_markers: List[str] = []
    for c in cells:
        if not isinstance(c, dict):
            issues.append("table.cells entry invalid")
            continue

        col_raw = str(c.get("col") or "").strip()
        val_raw = str(c.get("value_raw") or "").strip()
        col_norm = _norm_text(col_raw).replace(" ", "")

        if not col_raw:
            issues.append("empty column name in table.cells")
        if col_norm.startswith("col_"):
            issues.append(f"generic column name detected: '{col_raw}'")
        if not val_raw:
            issues.append(f"empty value_raw for col='{col_raw or '<empty>'}'")
        else:
            non_empty_values.append(val_raw)
            if _T_STAGE_CRITICAL_RE.search(val_raw):
                stage_markers.append(val_raw)

    row_key = str(table.get("row_key") or "").strip()
    if _T_STAGE_CRITICAL_RE.search(row_key):
        stage_markers.append(row_key)
    if not stage_markers:
        issues.append("T stage marker not preserved (expected T2/T3)")

    descriptive_values = [
        v for v in non_empty_values if not _ROW_KEY_CRITICAL_RE.match(_norm_text(v).replace(" ", ""))
    ]
    if not descriptive_values:
        issues.append("missing descriptive cell for critical T2/T3 row")
    elif max(len(v.strip()) for v in descriptive_values) < 8:
        issues.append("descriptive cell collapsed/too short")

    return issues


def validate_no_go_table_critical(chunks: Iterable[Dict[str, Any]]) -> List[Tuple[str, str]]:
    errors: List[Tuple[str, str]] = []
    for ch in chunks:
        if not _is_table_row_critical_t2_t3(ch):
            continue
        for issue in _critical_table_row_issues(ch):
            errors.append((str(ch.get("chunk_id") or "<no_chunk_id>"), issue))
    return errors


def validate_jsonl(jsonl_path: Path, schema_path: Path) -> int:
    schema = load_schema(schema_path)
    chunks = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            chunks.append(json.loads(line))

    errors = validate_chunks(chunks, schema)
    if errors:
        for cid, msg in errors[:50]:
            _safe_print(f"[INVALID] {cid}: {msg}")
        _safe_print(f"\nTotal errors: {len(errors)}")
        return 2

    no_go_errors = validate_no_go_table_critical(chunks)
    if no_go_errors:
        for cid, msg in no_go_errors[:50]:
            _safe_print(f"[NO_GO_TABLE_CRITICAL] {cid}: {msg}")
        _safe_print(f"\nTotal NO_GO_TABLE_CRITICAL errors: {len(no_go_errors)}")
        return 2

    _safe_print("[OK] dataset.jsonl válido no schema.")
    return 0


def validate_lexicon_file(lexicon_path: Path, dataset_jsonl: Path, max_variants: int) -> int:
    mod = load_lexicon_module(lexicon_path)
    lex_groups = mod["LEX_GROUPS"]
    short_allowlist = mod["SHORT_TOKEN_ALLOWLIST"]

    _safe_print(f"[INFO] building dataset token set from: {dataset_jsonl}")
    ds_tokens = iter_dataset_tokens(dataset_jsonl)
    _safe_print(f"[INFO] dataset_tokens size={len(ds_tokens)}")

    issues: List[Issue] = validate_lexicon(
        lex_groups,
        short_allowlist,
        dataset_tokens=ds_tokens,
        max_variants=max_variants,
    )

    if issues:
        _safe_print(f"[INVALID] lexicon={lexicon_path} issues={len(issues)}")
        for it in sorted(issues, key=lambda x: (x.code, x.message))[:200]:
            _safe_print(f"- {it.code}: {it.message}")
        return 2

    _safe_print(f"[OK] lexicon válido: {lexicon_path}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", help="Caminho do dataset.jsonl (chunks.jsonl)")
    ap.add_argument("--schema", help="Caminho do dataset_chunk.schema.json")
    ap.add_argument("--lexicon", help="Caminho do lexicon .py (ex.: src/uptowes/lexicon/ptbr_surgery_v1.py)")
    ap.add_argument("--max-variants", type=int, default=6)

    args = ap.parse_args()

    # modo 1: valida schema do dataset
    if args.jsonl and args.schema and not args.lexicon:
        raise SystemExit(validate_jsonl(Path(args.jsonl), Path(args.schema)))

    # modo 2: valida lexicon contra dataset tokens
    if args.lexicon and args.jsonl:
        raise SystemExit(
            validate_lexicon_file(
                lexicon_path=Path(args.lexicon),
                dataset_jsonl=Path(args.jsonl),
                max_variants=args.max_variants,
            )
        )

    ap.print_help()
    raise SystemExit(2)


if __name__ == "__main__":
    main()
