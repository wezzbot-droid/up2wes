#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_CONNECT_IMPORT_ERROR: Exception | None = None
try:
    from uptowes.db import connect
except ModuleNotFoundError as exc:  # pragma: no cover - depends on local optional deps
    connect = None  # type: ignore[assignment]
    _CONNECT_IMPORT_ERROR = exc
from uptowes.llm.ollama_client import generate
from uptowes.llm.prompting import build_answer_prompt
from uptowes.llm.validator import AnswererValidationError, validate_answerer_output

_RETRIEVAL_IMPORT_ERROR: Exception | None = None
try:
    from uptowes.retrieval import hybrid_search
except ModuleNotFoundError as exc:  # pragma: no cover - depends on local optional deps
    hybrid_search = None  # type: ignore[assignment]
    _RETRIEVAL_IMPORT_ERROR = exc


AREA_SOURCE_PREFIX = {
    "cirurgia": "cirurgia/",
    "clinica": "clinica/",
    "go": "go/",
    "pediatria": "pediatria/",
    "preventiva": "preventiva/",
    "core": None,
}
LAST_RAW_PATH = REPO_ROOT / "dataset" / "out" / "answers" / "last_raw.txt"


def normalize_source_prefix(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw or raw.upper() == "NONE":
        return None
    return raw


def to_repo_path(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    p = Path(path_str)
    return p if p.is_absolute() else (REPO_ROOT / p).resolve()


def _evidence_text_for_quote(item: Dict[str, Any]) -> str:
    if str(item.get("chunk_type") or "") == "table_row":
        tr = item.get("table_row") if isinstance(item.get("table_row"), dict) else {}
        row_text = str(tr.get("row_text") or "").strip()
        if row_text:
            return row_text
    return str(item.get("text") or item.get("text_canonical") or "").strip()


def _build_evidence_items(hits: List[Any], top_k: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for h in list(hits)[:top_k]:
        item: Dict[str, Any] = {
            "chunk_id": str(h.chunk_id),
            "path": str(h.source_path),
            "locator": str(h.locator),
            "source_table": str(h.source_table),
            "chunk_type": str(h.chunk_type),
            "title": str(h.title),
            "text": str(h.text),
            "score": float(h.score),
            "lex_mode": str(h.lex_mode),
        }
        if str(h.source_table) == "table_rows":
            item["table_row"] = {"row_text": str(h.text)}
        item["quote_source_text"] = _evidence_text_for_quote(item)
        item["evidence_text_for_quote"] = item["quote_source_text"]
        out.append(item)
    return out


def _save_last_raw(raw: str) -> None:
    LAST_RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_RAW_PATH.write_text(raw, encoding="utf-8")


def _validate_answer_payload(
    payload: Dict[str, Any], evidence_items: List[Dict[str, Any]]
) -> str | None:
    try:
        validate_answerer_output(json.dumps(payload, ensure_ascii=False), evidence_items)
        return None
    except AnswererValidationError as exc:
        return str(exc)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--q", required=True)
    ap.add_argument(
        "--area",
        choices=["cirurgia", "clinica", "go", "pediatria", "preventiva", "core"],
        default="cirurgia",
    )
    ap.add_argument("--source-prefix", default=None)
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--out-json", default=None)
    args = ap.parse_args(argv)

    if args.top_k <= 0:
        print("[FATAL] --top-k must be > 0")
        return 2

    source_prefix = (
        normalize_source_prefix(args.source_prefix)
        if args.source_prefix is not None
        else normalize_source_prefix(AREA_SOURCE_PREFIX.get(args.area))
    )
    print(
        f"[ASK] area={args.area} source_prefix={source_prefix if source_prefix else 'NONE'} "
        f"top_k={args.top_k} no_llm={str(bool(args.no_llm)).lower()}"
    )

    if connect is None:
        print(f"[FATAL] database dependency unavailable: {_CONNECT_IMPORT_ERROR}")
        return 2
    if hybrid_search is None:
        print(f"[FATAL] retrieval dependency unavailable: {_RETRIEVAL_IMPORT_ERROR}")
        return 2

    with connect() as conn:
        hits = hybrid_search(
            conn,
            args.q,
            top=int(args.top_k),
            enable_vector=False,
            source_prefix=source_prefix,
        )

    evidence_items = _build_evidence_items(hits, int(args.top_k))
    if args.no_llm:
        payload = {"question": args.q, "evidence": evidence_items}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        out_path = to_repo_path(args.out_json)
        if out_path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[OK] wrote json: {out_path}")
        return 0

    constraints = {"evidence_only": True, "citation_required": True, "max_evidence": int(args.top_k)}
    prompt = build_answer_prompt(args.q, evidence_items, constraints=constraints)
    raw = generate(prompt)

    try:
        parsed = validate_answerer_output(raw, evidence_items)
    except AnswererValidationError as exc:
        _save_last_raw(raw)
        print(f"[ERROR] invalid answer payload: {exc}. raw saved to {LAST_RAW_PATH}")
        return 2

    print(json.dumps(parsed, ensure_ascii=False, indent=2))
    out_path = to_repo_path(args.out_json)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] wrote json: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
