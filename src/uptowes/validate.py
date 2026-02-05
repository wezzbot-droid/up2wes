# src/uptowes/validate.py
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import jsonschema
from jsonschema import Draft202012Validator


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
    print("OK: dataset.jsonl válido no schema.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True, help="Caminho do dataset.jsonl")
    ap.add_argument("--schema", required=True, help="Caminho do dataset_chunk.schema.json")
    args = ap.parse_args()
    raise SystemExit(validate_jsonl(Path(args.jsonl), Path(args.schema)))


if __name__ == "__main__":
    main()
