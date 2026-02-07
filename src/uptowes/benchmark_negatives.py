from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Sequence, Set

from uptowes.lexicon_runtime import tokens as lex_tokens


GENERIC_NON_DISCRIMINATIVE = {
    "principal",
    "ducto",
    "margem",
    "margens",
    "criterio",
    "criterios",
    "diagnostico",
    "diagnosticos",
    "escala",
    "classificacao",
    "classificacoes",
}


@dataclass(frozen=True)
class NegativeInvalidEvidence:
    case_id: str
    query: str
    token: str
    matched_tokens: tuple[str, ...]
    chunk_id: str
    source_path: str
    excerpt: str


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        yield json.loads(line)


def _extract_chunk_text(obj: Mapping[str, Any]) -> str:
    table = obj.get("table")
    table_text = ""
    if isinstance(table, Mapping):
        table_text = str(table.get("row_text_canonical") or "")
    return " ".join(
        [
            str(obj.get("title") or ""),
            str(obj.get("text_canonical") or ""),
            table_text,
            str(obj.get("text_raw") or ""),
        ]
    ).strip()


def _is_discriminative_token(token: str, short_allowlist: Set[str]) -> bool:
    t = (token or "").strip().lower()
    if not t:
        return False
    if t in short_allowlist:
        return True
    if t.isnumeric():
        return False
    if len(t) < 5:
        return False
    if t in GENERIC_NON_DISCRIMINATIVE:
        return False
    return True


def extract_discriminative_tokens(query: str, short_allowlist: Set[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for t in lex_tokens(query):
        tok = str(t or "").strip().lower()
        if tok in seen:
            continue
        if not _is_discriminative_token(tok, short_allowlist):
            continue
        seen.add(tok)
        out.append(tok)
    return out


def audit_negative_queries(
    cases: Sequence[Mapping[str, Any]],
    corpus_jsonl: Path,
    short_allowlist: Set[str] | None = None,
    source_prefixes: Sequence[str] | None = None,
    min_token_hits: int = 2,
    max_token_df: int = 5,
) -> List[NegativeInvalidEvidence]:
    short_allow = {str(t).strip().lower() for t in (short_allowlist or set()) if str(t).strip()}
    prefixes = [str(p).strip().lower() for p in (source_prefixes or []) if str(p).strip()]
    token_index: dict[str, list[tuple[str, str, str]]] = {}
    token_df: dict[str, int] = {}

    for obj in _iter_jsonl(corpus_jsonl):
        chunk_id = str(obj.get("chunk_id") or "")
        source_path = str((obj.get("source") or {}).get("path") or obj.get("source_path") or "")
        source_path_norm = source_path.strip().lower()
        if prefixes and not any(source_path_norm.startswith(p) for p in prefixes):
            continue
        text = _extract_chunk_text(obj)
        if not text:
            continue
        text_tokens = set(lex_tokens(text))
        excerpt = text.replace("\n", " ").strip()
        if len(excerpt) > 220:
            excerpt = excerpt[:220] + "..."
        for tok in text_tokens:
            token_index.setdefault(tok, []).append((chunk_id, source_path, excerpt))
            token_df[tok] = token_df.get(tok, 0) + 1

    violations: List[NegativeInvalidEvidence] = []
    for case in cases:
        if bool(case.get("expect_hit")):
            continue
        if str(case.get("bucket") or "").upper() != "B":
            continue

        case_id = str(case.get("id") or "")
        query = str(case.get("query") or "")
        token_matches: list[tuple[str, tuple[str, str, str]]] = []
        for tok in extract_discriminative_tokens(query, short_allow):
            if int(token_df.get(tok, 0)) > int(max_token_df):
                continue
            matches = token_index.get(tok) or []
            if not matches:
                continue
            token_matches.append((tok, matches[0]))

        if len(token_matches) < max(1, int(min_token_hits)):
            continue

        tok, evidence = token_matches[0]
        chunk_id, source_path, excerpt = evidence
        violations.append(
            NegativeInvalidEvidence(
                case_id=case_id,
                query=query,
                token=tok,
                matched_tokens=tuple(t for t, _ in token_matches),
                chunk_id=chunk_id,
                source_path=source_path,
                excerpt=excerpt,
            )
        )
    return violations
