# src/uptowes/chunk.py
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .normalize import extract_bold_spans

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CODE_FENCE_RE = re.compile(r"^```(\w+)?\s*$")


def _sha1_text(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _doc_id_from_path(path: str) -> str:
    name = Path(path).stem.upper()
    name = re.sub(r"[^A-Z0-9]+", "_", name).strip("_")
    return name or "DOC"


def _parse_table(lines_block: List[str]) -> Optional[Dict[str, Any]]:
    if len(lines_block) < 2:
        return None

    header = [c.strip() for c in lines_block[0].strip().strip("|").split("|")]
    sep = lines_block[1]
    if not re.search(r"-{3,}", sep):
        return None

    rows = []
    for ln in lines_block[2:]:
        if "|" not in ln:
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        row = {header[i]: cells[i] for i in range(len(header))}
        rows.append(row)

    return {"header": header, "rows": rows}


def _mermaid_to_steps(lines: List[str]) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    arrow_re = re.compile(r"^\s*([A-Za-z0-9_]+)\s*-->\s*(?:\|([^|]+)\|\s*)?([A-Za-z0-9_]+).*$")

    for ln in lines:
        m = arrow_re.match(ln)
        if not m:
            continue
        a, cond, b = m.group(1), m.group(2), m.group(3)
        sid = f"S{len(steps)+1:03d}"
        text = f"Se {a} então {b}."
        step: Dict[str, Any] = {"step_id": sid, "text": text, "action": f"Ir para {b}"}
        if cond:
            step["condition"] = cond.strip()
        steps.append(step)

    return steps


def _make_chunk(
    *,
    doc_id: str,
    ordinal: int,
    start_line: int,
    end_line: int,
    source_path: str,
    section_path: List[str],
    title: str,
    chunk_type: str,
    text_raw: str,
    text_canonical: str,
    bold_spans: List[Dict[str, Any]],
    quality_flags: List[str],
    priority: str,
    subtype: Optional[str] = None,
    table: Optional[Dict[str, Any]] = None,
    algorithm: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    chunk_id = f"{doc_id}#L{start_line}-L{end_line}#{ordinal}"

    ch: Dict[str, Any] = {
        "schema_version": "0.1",
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "source": {"path": source_path.replace("\\", "/"), "locator": f"L{start_line}-L{end_line}"},
        "section_path": section_path,
        "title": title,
        "chunk_type": chunk_type,
        "text_raw": text_raw,
        "text_canonical": text_canonical,
        "bold_spans": bold_spans,
        "quality_flags": quality_flags,
        "priority": priority,
        "hash": {"raw_sha1": _sha1_text(text_raw), "canonical_sha1": _sha1_text(text_canonical)},
    }

    if subtype:
        ch["subtype"] = subtype
    if tags:
        ch["tags"] = tags
    if table:
        ch["table"] = table
    if algorithm:
        ch["algorithm"] = algorithm

    return ch


def chunk_markdown(text: str, source_rel_path: str) -> List[Dict[str, Any]]:
    """
    Chunker determinístico por blocos:
    - headings constroem section_path
    - listas viram text + subtype=list_item (linha a linha)
    - tabelas viram table_row (linha a linha)
    - mermaid vira algorithm_step (com steps determinísticos)
    - resto vira text + subtype=paragraph
    """
    doc_id = _doc_id_from_path(source_rel_path)
    lines = text.split("\n")

    chunks: List[Dict[str, Any]] = []
    heading_stack: List[tuple[int, str]] = []
    ordinal = 0
    i = 0

    def section_path() -> List[str]:
        return [t for _, t in heading_stack]

    def title() -> str:
        return heading_stack[-1][1] if heading_stack else doc_id

    while i < len(lines):
        ln = lines[i]

        mh = HEADING_RE.match(ln)
        if mh:
            level = len(mh.group(1))
            ttl = mh.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, ttl))
            i += 1
            continue

        if ln.strip() == "":
            i += 1
            continue

        # code fence
        mf = CODE_FENCE_RE.match(ln)
        if mf:
            open_line = i + 1
            lang = (mf.group(1) or "").lower()
            i += 1

            code_lines: List[str] = []
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1

            close_line = (i + 1) if i < len(lines) else i
            if i < len(lines):
                i += 1  # consume closing fence

            raw = "\n".join(["```" + lang] + code_lines + ["```"])
            sec = section_path()
            ctx = " > ".join(sec) if sec else doc_id

            if lang == "mermaid":
                steps = _mermaid_to_steps(code_lines)
                alg = {"name": title(), "steps": steps}
                body = "\n".join([s["text"] for s in steps]) if steps else "\n".join(code_lines).strip()
                canonical = f"[Contexto: {ctx}]\n{body}".strip()
                canonical, bold = extract_bold_spans(canonical)

                ordinal += 1
                chunks.append(
                    _make_chunk(
                        doc_id=doc_id,
                        ordinal=ordinal,
                        start_line=open_line,
                        end_line=close_line,
                        source_path=source_rel_path,
                        section_path=sec,
                        title=title(),
                        chunk_type="algorithm_step",
                        text_raw=raw,
                        text_canonical=canonical,
                        bold_spans=bold,
                        quality_flags=["MERMAID_CONVERTED" if steps else "MERMAID_UNPARSED"],
                        priority="high",
                        algorithm=alg,
                    )
                )
            else:
                canonical = f"[Contexto: {ctx}]\n" + "\n".join(code_lines).strip()
                canonical, bold = extract_bold_spans(canonical)

                ordinal += 1
                chunks.append(
                    _make_chunk(
                        doc_id=doc_id,
                        ordinal=ordinal,
                        start_line=open_line,
                        end_line=close_line,
                        source_path=source_rel_path,
                        section_path=sec,
                        title=title(),
                        chunk_type="text",
                        subtype=f"code:{lang or 'plain'}",
                        text_raw=raw,
                        text_canonical=canonical,
                        bold_spans=bold,
                        quality_flags=["CODE_BLOCK"],
                        priority="normal",
                    )
                )
            continue

        # table block
        if "|" in ln and i + 1 < len(lines) and re.search(r"\|?\s*:?-{3,}", lines[i + 1]):
            block = [ln, lines[i + 1]]
            line_nums = [i + 1, i + 2]
            i += 2

            while i < len(lines) and "|" in lines[i] and lines[i].strip() != "":
                block.append(lines[i])
                line_nums.append(i + 1)
                i += 1

            parsed = _parse_table(block)
            sec = section_path()
            ctx = " > ".join(sec) if sec else doc_id

            if parsed and parsed["rows"]:
                header = parsed["header"]
                for r_idx, row in enumerate(parsed["rows"]):
                    row_line = line_nums[2 + r_idx] if 2 + r_idx < len(line_nums) else line_nums[-1]
                    row_text = "; ".join([f"{k}={v}" for k, v in row.items() if v != ""])
                    canonical = f"[Contexto: {ctx}]\nTabela: {title()}\n{row_text}".strip()
                    canonical, bold = extract_bold_spans(canonical)

                    ordinal += 1
                    chunks.append(
                        _make_chunk(
                            doc_id=doc_id,
                            ordinal=ordinal,
                            start_line=row_line,
                            end_line=row_line,
                            source_path=source_rel_path,
                            section_path=sec,
                            title=title(),
                            chunk_type="table_row",
                            text_raw="\n".join(block),
                            text_canonical=canonical,
                            bold_spans=bold,
                            quality_flags=[],
                            priority="high",
                            table={
                                "table_name": title(),
                                "header": header,
                                "row_index": r_idx,
                                "row": row,
                                "row_text_canonical": row_text,
                            },
                        )
                    )
            else:
                raw = "\n".join(block)
                canonical = f"[Contexto: {ctx}]\n{raw}".strip()
                canonical, bold = extract_bold_spans(canonical)

                ordinal += 1
                chunks.append(
                    _make_chunk(
                        doc_id=doc_id,
                        ordinal=ordinal,
                        start_line=line_nums[0],
                        end_line=line_nums[-1],
                        source_path=source_rel_path,
                        section_path=sec,
                        title=title(),
                        chunk_type="text",
                        subtype="table_raw",
                        text_raw=raw,
                        text_canonical=canonical,
                        bold_spans=bold,
                        quality_flags=["TABLE_UNPARSED"],
                        priority="normal",
                    )
                )
            continue

        # list items (linha a linha)
        if re.match(r"^\s*[-*+]\s+", ln):
            while i < len(lines) and re.match(r"^\s*[-*+]\s+", lines[i]):
                item_line = i + 1
                item_raw = lines[i].strip()
                body = re.sub(r"^\s*[-*+]\s+", "", item_raw)

                sec = section_path()
                ctx = " > ".join(sec) if sec else doc_id
                canonical = f"[Contexto: {ctx}]\n- {body}".strip()
                canonical, bold = extract_bold_spans(canonical)

                ordinal += 1
                chunks.append(
                    _make_chunk(
                        doc_id=doc_id,
                        ordinal=ordinal,
                        start_line=item_line,
                        end_line=item_line,
                        source_path=source_rel_path,
                        section_path=sec,
                        title=title(),
                        chunk_type="text",
                        subtype="list_item",
                        text_raw=item_raw,
                        text_canonical=canonical,
                        bold_spans=bold,
                        quality_flags=[],
                        priority="normal",
                    )
                )
                i += 1
            continue

        # paragraph
        start_line = i + 1
        paras = [ln]
        i += 1

        while i < len(lines):
            if lines[i].strip() == "":
                break
            if (
                HEADING_RE.match(lines[i])
                or CODE_FENCE_RE.match(lines[i])
                or re.match(r"^\s*[-*+]\s+", lines[i])
                or ("|" in lines[i] and i + 1 < len(lines) and re.search(r"\|?\s*:?-{3,}", lines[i + 1]))
            ):
                break
            paras.append(lines[i])
            i += 1

        end_line = start_line + len(paras) - 1
        raw = "\n".join(paras)

        sec = section_path()
        ctx = " > ".join(sec) if sec else doc_id
        canonical = f"[Contexto: {ctx}]\n{raw}".strip()
        canonical, bold = extract_bold_spans(canonical)

        ordinal += 1
        chunks.append(
            _make_chunk(
                doc_id=doc_id,
                ordinal=ordinal,
                start_line=start_line,
                end_line=end_line,
                source_path=source_rel_path,
                section_path=sec,
                title=title(),
                chunk_type="text",
                subtype="paragraph",
                text_raw=raw,
                text_canonical=canonical,
                bold_spans=bold,
                quality_flags=[],
                priority="normal",
            )
        )

    return chunks
