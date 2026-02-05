#!/usr/bin/env python3
# scripts/build_dataset.py
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Tuple, Optional, Dict, Any

import jsonschema  # pip install jsonschema
from jsonschema import Draft202012Validator

# -------------------------
# Regex
# -------------------------
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_CODE_FENCE_RE = re.compile(r"^\s*```")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+)(.+\S)\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


# -------------------------
# Helpers (deterministic)
# -------------------------
def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def normalize_ascii_slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text.upper() or "DOC"


def strip_clean_suffix(stem: str) -> str:
    return re.sub(r"_CLEAN$", "", stem.upper())


def canonicalize_symbols(s: str) -> str:
    # HTML entities comuns de OCR
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def extract_bold_spans(text_raw: str) -> List[Dict[str, Any]]:
    spans = []
    for m in _BOLD_RE.finditer(text_raw):
        spans.append({"text": m.group(1), "start": m.start(1), "end": m.end(1)})
    return spans


def classify_chunk_type(text: str, section_path: List[str], is_table_row: bool) -> str:
    if is_table_row:
        return "table_row"

    t = text.strip().lower()
    if re.search(r"\b(defini[cç][aã]o|define-se|conceito)\b", t):
        return "definition"
    if re.search(r"\bcrit[eé]ri[oa]s?\b", t) or re.search(r"\bdiagn[oó]stic[oa]\b", t):
        return "criteria"
    if re.search(r"\bclassifica[cç][aã]o\b|\btipos?\b|\bestadiamento\b", t):
        return "classification"
    if re.search(r"\bcontraindica[cç][aã]o\b|\bn[aã]o usar\b|\bevitar\b", t):
        return "contraindication"
    if re.search(r"\bdose\b|\bposologia\b|\bmg\b|\bmcg\b|\bui\b|/kg\b|\bvo\b|\bev\b|\bim\b|\bq\d+h\b", t):
        return "dose"
    if re.search(r"\bconduta\b|\bmanejo\b|\btratamento\b|\bprocedimento\b|\bindica[rç][aã]o\b|\brealizar\b", t):
        return "procedure"
    if re.search(r"\bse\b.*\b(ent[aã]o)\b", t) or re.search(r"\bpasso\b|\betapa\b", t):
        return "algorithm_step"

    sp = " ".join(section_path).lower()
    if "dose" in sp:
        return "dose"
    if "crit" in sp:
        return "criteria"
    if "class" in sp:
        return "classification"

    return "text"


def derive_priority(chunk_type: str) -> str:
    # simples e determinístico. Evolui depois.
    if chunk_type in {"dose", "criteria", "procedure", "contraindication", "algorithm_step"}:
        return "high"
    return "normal"


# -------------------------
# Markdown parsing
# -------------------------
@dataclass(frozen=True)
class Block:
    kind: str  # paragraph | list_item | table | code
    start_line: int  # 1-indexed
    end_line: int    # 1-indexed inclusive
    text: str
    table: Optional[Dict[str, Any]] = None


def is_table_header(lines: List[str], i: int) -> bool:
    if i + 1 >= len(lines):
        return False
    if "|" not in lines[i]:
        return False
    return bool(_TABLE_SEP_RE.match(lines[i + 1]))


def split_table_row(line: str) -> List[str]:
    raw = line.strip().strip("|")
    return [p.strip() for p in raw.split("|")]


def iter_blocks(lines: List[str]) -> Iterator[Tuple[Optional[Tuple[int, str]], Optional[Block]]]:
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            yield ((level, title), None)
            i += 1
            continue

        if line.strip() == "":
            i += 1
            continue

        if _CODE_FENCE_RE.match(line):
            start = i
            i += 1
            while i < n and not _CODE_FENCE_RE.match(lines[i]):
                i += 1
            if i < n:
                i += 1
            text = "\n".join(lines[start:i]).rstrip()
            yield (None, Block(kind="code", start_line=start + 1, end_line=i, text=text))
            continue

        # TABLE (cada linha vira um Block(kind="table"))
        if is_table_header(lines, i):
            table_header_line = i + 1  # 1-indexed
            header = split_table_row(lines[i])
            j = i + 2  # pula separador
            row_idx = 0
            while j < n and ("|" in lines[j]) and lines[j].strip() != "":
                row = split_table_row(lines[j])
                if len(row) < len(header):
                    row = row + [""] * (len(header) - len(row))
                payload = {
                    "header": header,
                    "cells": row,
                    "row_index": row_idx,
                    "table_start_line": table_header_line,  # <- ID estável por tabela
                }
                yield (
                    None,
                    Block(
                        kind="table",
                        start_line=j + 1,
                        end_line=j + 1,
                        text=lines[j].rstrip(),
                        table=payload,
                    ),
                )
                row_idx += 1
                j += 1
            i = j
            continue

        if _LIST_ITEM_RE.match(line):
            start = i
            yield (None, Block(kind="list_item", start_line=start + 1, end_line=start + 1, text=line.rstrip()))
            i += 1
            continue

        # paragraph
        start = i
        buf = []
        while i < n:
            l = lines[i]
            if l.strip() == "":
                break
            if _HEADING_RE.match(l):
                break
            if _CODE_FENCE_RE.match(l):
                break
            if _LIST_ITEM_RE.match(l):
                break
            if is_table_header(lines, i):
                break
            buf.append(l.rstrip())
            i += 1
        text = "\n".join(buf).rstrip()
        yield (None, Block(kind="paragraph", start_line=start + 1, end_line=i, text=text))


def split_long_text(text: str, max_chars: int = 1400) -> List[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    parts = re.split(r"(?<=[\.\!\?])\s+", text)
    out = []
    cur = []
    cur_len = 0
    for p in parts:
        p = p.strip()
        if not p:
            continue
        add = p if not cur else " " + p
        if cur_len + len(add) <= max_chars:
            cur.append(p)
            cur_len += len(add)
        else:
            out.append(" ".join(cur).strip())
            cur = [p]
            cur_len = len(p)
    if cur:
        out.append(" ".join(cur).strip())
    final = []
    for x in out:
        if len(x) <= max_chars:
            final.append(x)
        else:
            for k in range(0, len(x), max_chars):
                final.append(x[k:k + max_chars].strip())
    return [f for f in final if f]


# -------------------------
# Dataset build
# -------------------------
def build_doc_id(input_root: Path, file_path: Path) -> str:
    rel = file_path.relative_to(input_root).as_posix()
    stem = Path(rel).with_suffix("").name
    stem_slug = strip_clean_suffix(normalize_ascii_slug(stem))
    parent = Path(rel).parent.as_posix().replace("/", "_")
    parent_slug = normalize_ascii_slug(parent) if parent and parent != "." else ""
    return f"{parent_slug}_{stem_slug}" if parent_slug else stem_slug


def make_chunk_id(doc_id: str, line_start: int, line_end: int, ordinal: int) -> str:
    return f"{doc_id}#L{line_start}-L{line_end}#{ordinal}"


def build_anchor(doc_id: str, section_path: List[str]) -> str:
    return f"{doc_id} > " + " > ".join(section_path) if section_path else doc_id


def table_row_text_canonical(anchor: str, header: List[str], cells: List[str]) -> str:
    pairs = []
    for h, c in zip(header, cells):
        h = canonicalize_symbols(h)
        c = canonicalize_symbols(c)
        if h == "" and c == "":
            continue
        if h == "":
            pairs.append(c)
        else:
            pairs.append(f"{h}: {c}")
    body = "; ".join([p for p in pairs if p.strip()]).strip()
    if not body:
        body = canonicalize_symbols(" | ".join(cells))
    return f"{anchor}\n{body}".strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()

    # -------------------------
    # Hygiene: garante dirs padrão do repo (artifacts não versionados)
    # -------------------------
    repo_root = Path(__file__).resolve().parents[1]
    (repo_root / "dataset").mkdir(parents=True, exist_ok=True)
    (repo_root / "dataset" / "out").mkdir(parents=True, exist_ok=True)

    input_root = Path(args.input).resolve()
    schema_path = Path(args.schema).resolve()
    out_path = Path(args.out).resolve()
    report_path = Path(args.report).resolve()

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_version = schema["properties"]["schema_version"]["const"]

    # Compila validador UMA vez (muito mais rápido)
    validator = Draft202012Validator(schema)

    md_files = sorted([p for p in input_root.rglob("*.md") if p.is_file()])
    if not md_files:
        print(f"[FATAL] No .md files found under {input_root}")
        return 2

    out_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    counts_by_type = Counter()
    counts_by_doc = defaultdict(int)
    errors: List[Dict[str, Any]] = []

    # Write to temp first, then replace -> evita "arquivo vazio" se falhar
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")

    fatal_error: Optional[Dict[str, Any]] = None

    try:
        with tmp_path.open("w", encoding="utf-8") as f_out:
            for fp in md_files:
                rel_path = fp.relative_to(input_root).as_posix()

                try:
                    text = fp.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    text = fp.read_text(encoding="utf-8-sig")

                lines = text.splitlines()
                doc_id = build_doc_id(input_root, fp)

                section_stack: List[Tuple[int, str]] = []
                ordinal_counter = 0

                for heading_update, block in iter_blocks(lines):
                    if heading_update is not None:
                        lvl, title = heading_update
                        while section_stack and section_stack[-1][0] >= lvl:
                            section_stack.pop()
                        section_stack.append((lvl, title))
                        continue
                    if block is None:
                        continue

                    section_path = [t for _, t in section_stack] or [doc_id]  # schema exige minItems=1
                    title = section_path[-1]
                    anchor = build_anchor(doc_id, section_path)

                    # ----------------
                    # TABLE ROW
                    # ----------------
                    if block.kind == "table" and block.table:
                        header: List[str] = block.table["header"]
                        cells: List[str] = block.table["cells"]

                        text_raw = block.text.strip()
                        text_canonical = table_row_text_canonical(anchor, header, cells)

                        chunk_type = "table_row"
                        priority = derive_priority(chunk_type)

                        # REQUIRED pelo schema (mesmo vazio)
                        quality_flags: List[str] = []
                        if any((c is None) or (str(c).strip() == "") for c in cells):
                            quality_flags.append("table_empty_cell")

                        # row_key opcional: 1ª célula útil (sem **)
                        row_key = canonicalize_symbols((cells[0] if cells else "")).replace("**", "").strip() or "ROW"

                        ordinal_counter += 1
                        table_start_line = int(block.table.get("table_start_line", block.start_line))

                        # cells com value_raw (schema exige)
                        max_len = max(len(header), len(cells))
                        table_cells = []
                        for i in range(max_len):
                            col_name = header[i].strip() if i < len(header) else ""
                            if not col_name:
                                col_name = f"COL_{i+1}"
                            value = cells[i] if i < len(cells) else ""
                            table_cells.append({"col": col_name, "value_raw": value})

                        chunk = {
                            "schema_version": schema_version,
                            "chunk_id": make_chunk_id(doc_id, block.start_line, block.end_line, ordinal_counter),
                            "doc_id": doc_id,
                            "source": {
                                "path": rel_path,
                                "locator": f"L{block.start_line}-L{block.end_line}",
                            },
                            "section_path": section_path,
                            "title": title,
                            "chunk_type": chunk_type,
                            "text_raw": text_raw,
                            "text_canonical": text_canonical,
                            "bold_spans": extract_bold_spans(text_raw),
                            "quality_flags": quality_flags,
                            "priority": priority,
                            "hash": {
                                "raw_sha1": sha1_text(text_raw),
                                "canonical_sha1": sha1_text(text_canonical),
                            },
                            "table": {
                                "table_id": f"{doc_id}#T{table_start_line}",  # <- estável
                                "row_key": row_key,
                                "cells": table_cells,
                                "row_text_canonical": text_canonical,
                            },
                        }

                        try:
                            validator.validate(chunk)
                        except Exception as e:
                            fatal_error = {
                                "file": rel_path,
                                "locator": f"L{block.start_line}-L{block.end_line}",
                                "chunk_id": chunk.get("chunk_id"),
                                "error": str(e),
                            }
                            errors.append(fatal_error)
                            raise

                        f_out.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                        counts_by_type[chunk_type] += 1
                        counts_by_doc[doc_id] += 1
                        continue

                    # ----------------
                    # NON-TABLE
                    # ----------------
                    raw = block.text.strip()
                    if not raw:
                        continue

                    pieces = split_long_text(raw)
                    for piece in pieces:
                        ordinal_counter += 1
                        chunk_type = classify_chunk_type(piece, section_path, is_table_row=False)
                        priority = derive_priority(chunk_type)

                        quality_flags: List[str] = []  # REQUIRED pelo schema (mesmo vazio)
                        if "�" in piece:
                            quality_flags.append("encoding_artifact")

                        text_raw = piece
                        text_canonical = canonicalize_symbols(f"{anchor}\n{piece}")

                        chunk = {
                            "schema_version": schema_version,
                            "chunk_id": make_chunk_id(doc_id, block.start_line, block.end_line, ordinal_counter),
                            "doc_id": doc_id,
                            "source": {
                                "path": rel_path,
                                "locator": f"L{block.start_line}-L{block.end_line}",
                            },
                            "section_path": section_path,
                            "title": title,
                            "chunk_type": chunk_type,
                            "text_raw": text_raw,
                            "text_canonical": text_canonical,
                            "bold_spans": extract_bold_spans(text_raw),
                            "quality_flags": quality_flags,
                            "priority": priority,
                            "hash": {
                                "raw_sha1": sha1_text(text_raw),
                                "canonical_sha1": sha1_text(text_canonical),
                            },
                        }

                        try:
                            validator.validate(chunk)
                        except Exception as e:
                            fatal_error = {
                                "file": rel_path,
                                "locator": f"L{block.start_line}-L{block.end_line}",
                                "chunk_id": chunk.get("chunk_id"),
                                "error": str(e),
                            }
                            errors.append(fatal_error)
                            raise

                        f_out.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                        counts_by_type[chunk_type] += 1
                        counts_by_doc[doc_id] += 1

    except Exception:
        # Fail-fast, mas com relatório e sem destruir dataset existente
        pass

    # Sempre escreve report (mesmo em falha)
    report = {
        "input_root": str(input_root),
        "schema": str(schema_path),
        "out": str(out_path),
        "docs": len(counts_by_doc),
        "chunks_total": int(sum(counts_by_type.values())),
        "chunks_by_type": dict(counts_by_type),
        "top_docs_by_chunk_count": sorted(counts_by_doc.items(), key=lambda x: x[1], reverse=True)[:20],
        "errors_count": len(errors),
        "fatal_error": fatal_error,
        "errors": errors[:50],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if fatal_error is not None:
        print("[FATAL] Validation failed. Dataset not replaced.")
        print(f"[FATAL] First error in: {fatal_error['file']} {fatal_error['locator']} chunk_id={fatal_error['chunk_id']}")
        print(f"[FATAL] report={report_path}")
        # remove tmp se quiser limpeza dura
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        return 1

    # Atomic replace (só se OK)
    tmp_path.replace(out_path)

    print(f"[OK] docs={report['docs']} chunks={report['chunks_total']} out={out_path}")
    print(f"[OK] report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
