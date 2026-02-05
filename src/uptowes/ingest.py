# src/uptowes/ingest.py
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from .chunk import chunk_markdown
from .normalize import normalize_text
from .validate import load_schema, validate_chunks


def list_md_files(root: Path) -> List[Path]:
    if root.is_file() and root.suffix.lower() == ".md":
        return [root]
    return sorted([p for p in root.rglob("*.md") if p.is_file()])


def ingest(input_path: Path, output_jsonl: Path, schema_path: Path) -> int:
    schema = load_schema(schema_path)

    files = list_md_files(input_path)
    if not files:
        print(f"Nenhum .md encontrado em: {input_path}")
        return 2

    all_chunks = []
    for fp in files:
        raw = fp.read_text(encoding="utf-8", errors="replace")
        norm = normalize_text(raw)

        # path relativo “bonito” para source.path
        try:
            rel = fp.as_posix()
        except Exception:
            rel = str(fp)

        chunks = chunk_markdown(norm, rel)
        all_chunks.extend(chunks)

    errors = validate_chunks(all_chunks, schema)
    if errors:
        for cid, msg in errors[:50]:
            print(f"[INVALID] {cid}: {msg}")
        print(f"\nTotal errors: {len(errors)}")
        return 2

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8") as f:
        for ch in all_chunks:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")

    print(f"OK: gerado {output_jsonl} com {len(all_chunks)} chunks.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Arquivo .md ou pasta com .md")
    ap.add_argument("--out", required=True, help="Saída dataset.jsonl")
    ap.add_argument("--schema", required=True, help="Schema JSON")
    args = ap.parse_args()
    raise SystemExit(ingest(Path(args.input), Path(args.out), Path(args.schema)))


if __name__ == "__main__":
    main()
