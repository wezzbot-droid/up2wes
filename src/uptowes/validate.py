# src/uptowes/validate.py
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from jsonschema import Draft202012Validator

from uptowes.lexicon.qa import (
    Issue,
    iter_dataset_tokens,
    load_lexicon_module,
    validate_lexicon,
)


def load_schema(schema_path: Path) -> Dict[str, Any]:
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_chunks(chunks: Iterable[Dict[str, Any]], schema: Dict[str, Any]) -> List[Tuple[str, str]]:
    v = Draft202012Validator(schema)
    errors: List[Tuple[str, str]] = []
    for ch in chunks:
        for e in v.iter_errors(ch):
            errors.append((ch.get("chunk_id", "<no_chunk_id>"), e.message))
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
            print(f"[INVALID] {cid}: {msg}")
        print(f"\nTotal errors: {len(errors)}")
        return 2
    print("[OK] dataset.jsonl válido no schema.")
    return 0


def validate_lexicon_file(lexicon_path: Path, dataset_jsonl: Path, max_variants: int) -> int:
    mod = load_lexicon_module(lexicon_path)
    lex_groups = mod["LEX_GROUPS"]
    short_allowlist = mod["SHORT_TOKEN_ALLOWLIST"]

    print(f"[INFO] building dataset token set from: {dataset_jsonl}")
    ds_tokens = iter_dataset_tokens(dataset_jsonl)
    print(f"[INFO] dataset_tokens size={len(ds_tokens)}")

    issues: List[Issue] = validate_lexicon(
        lex_groups,
        short_allowlist,
        dataset_tokens=ds_tokens,
        max_variants=max_variants,
    )

    if issues:
        print(f"[INVALID] lexicon={lexicon_path} issues={len(issues)}")
        for it in sorted(issues, key=lambda x: (x.code, x.message))[:200]:
            print(f"- {it.code}: {it.message}")
        return 2

    print(f"[OK] lexicon válido: {lexicon_path}")
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
