#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


SEVERITY_RANK: Dict[str, int] = {
    "TABLE_CRITICAL_DEGRADED": 100,
    "TABLE_UNPARSED": 95,
    "TABLE_EMPTY_CELL": 85,
    "MERMAID_UNPARSED": 80,
    "OCR_SUSPECT": 75,
    "ENCODING_ARTIFACT": 70,
    "LOW_CONTEXT": 65,
    "DUPLICATE": 60,
    "CODE_BLOCK": 30,
}


def iter_jsonl(path: Path) -> Iterable[dict]:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        yield json.loads(line)


def norm_flag(flag: str) -> str:
    return str(flag or "").strip().upper()


def flag_severity(flag: str) -> int:
    return SEVERITY_RANK.get(norm_flag(flag), 50)


def short_snippet(chunk: dict, limit: int = 140) -> str:
    text = str(chunk.get("text_canonical") or chunk.get("text_raw") or "")
    text = " ".join(text.replace("\n", " ").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def escape_md_cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


def build_report(dataset_path: Path) -> Tuple[List[str], int]:
    findings: List[Tuple[str, str, str, str, str]] = []
    flag_counts: Counter[str] = Counter()
    doc_counts: Counter[str] = Counter()

    for chunk in iter_jsonl(dataset_path):
        qflags = [norm_flag(f) for f in (chunk.get("quality_flags") or []) if str(f).strip()]
        if not qflags:
            continue

        chunk_id = str(chunk.get("chunk_id") or "")
        src = chunk.get("source") or {}
        path = str(src.get("path") or "")
        loc = str(src.get("locator") or "")
        snippet = short_snippet(chunk)
        doc_id = str(chunk.get("doc_id") or "")

        for flag in sorted(set(qflags)):
            flag_counts[flag] += 1
            if doc_id:
                doc_counts[doc_id] += 1
            findings.append((flag, chunk_id, path, loc, snippet))

    # Ordenação determinística: severidade (desc) -> frequência do flag (desc) -> flag -> chunk_id.
    findings.sort(
        key=lambda x: (
            -flag_severity(x[0]),
            -flag_counts[x[0]],
            x[0],
            x[1],
        )
    )

    lines: List[str] = []
    lines.append("# QA Report\n\n")
    lines.append(f"- dataset: `{dataset_path.as_posix()}`\n")
    lines.append(f"- findings_total: `{len(findings)}`\n\n")

    lines.append("## A) Summary\n\n")
    lines.append("### Flags\n\n")
    if flag_counts:
        lines.append("| quality_flag | count | severity |\n")
        lines.append("| --- | ---: | ---: |\n")
        for flag, count in sorted(flag_counts.items(), key=lambda kv: (-flag_severity(kv[0]), -kv[1], kv[0])):
            lines.append(f"| `{escape_md_cell(flag)}` | {count} | {flag_severity(flag)} |\n")
    else:
        lines.append("_No quality flags found._\n")

    lines.append("\n### Top docs with flags\n\n")
    if doc_counts:
        lines.append("| doc_id | flags_count |\n")
        lines.append("| --- | ---: |\n")
        for doc_id, count in sorted(doc_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:20]:
            lines.append(f"| `{escape_md_cell(doc_id)}` | {count} |\n")
    else:
        lines.append("_No flagged docs._\n")

    lines.append("\n## B) Findings\n\n")
    if findings:
        lines.append("| flag | chunk_id | path | loc | snippet |\n")
        lines.append("| --- | --- | --- | --- | --- |\n")
        for flag, chunk_id, path, loc, snippet in findings:
            lines.append(
                f"| `{escape_md_cell(flag)}` | `{escape_md_cell(chunk_id)}` | "
                f"`{escape_md_cell(path)}` | `{escape_md_cell(loc)}` | {escape_md_cell(snippet)} |\n"
            )
    else:
        lines.append("_No findings._\n")

    return lines, len(findings)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="dataset/chunks.jsonl")
    ap.add_argument("--out", default="dataset/out/reports/qa.md")
    args = ap.parse_args()

    dataset_path = Path(args.dataset).resolve()
    out_path = Path(args.out).resolve()

    if not dataset_path.exists():
        print(f"[FATAL] dataset not found: {dataset_path}")
        return 2

    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines, total = build_report(dataset_path)
    out_path.write_text("".join(lines), encoding="utf-8")
    print(f"[OK] wrote report: {out_path}")
    print(f"[OK] findings_total={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

