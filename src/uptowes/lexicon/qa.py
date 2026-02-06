# src/uptowes/lexicon/qa.py
from __future__ import annotations

import importlib.util
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

WORD_RE = re.compile(r"[a-z0-9]+")


# termos genéricos proibidos (ajuste conforme necessário)
BANNED_GENERIC = {
    "diagnostico", "tratamento", "conduta", "complicacoes", "sintomas", "avaliacao",
    "risco cirurgico", "agudo", "cronico", "dor", "infeccao", "cirurgia", "paciente",
    "classificacao", "criterios", "indicacao", "manejo",
}

BANNED_TOKENS = {"dx", "tx", "cond", "avaliar", "manejo"}


@dataclass(frozen=True)
class Issue:
    code: str
    message: str


def deaccent(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def normalize_term(s: str) -> str:
    s = deaccent((s or "").strip().lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokenize(s: str) -> List[str]:
    return WORD_RE.findall(normalize_term(s))


def load_lexicon_module(path: Path) -> Dict[str, Any]:
    spec = importlib.util.spec_from_file_location("lexicon_mod", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "LEX_GROUPS") or not hasattr(mod, "SHORT_TOKEN_ALLOWLIST"):
        raise ValueError("Lexicon file must define LEX_GROUPS and SHORT_TOKEN_ALLOWLIST.")

    return {
        "LEX_GROUPS": getattr(mod, "LEX_GROUPS"),
        "LEX_ALIASES": getattr(mod, "LEX_ALIASES", {}),
        "SHORT_TOKEN_ALLOWLIST": getattr(mod, "SHORT_TOKEN_ALLOWLIST"),
    }


def iter_dataset_tokens(dataset_jsonl: Path) -> Set[str]:
    """
    Gate de presença no acervo: varre dataset/chunks.jsonl e coleta tokens normalizados.
    Determinístico e barato (mas pode demorar um pouco em dataset grande).
    """
    tokens: Set[str] = set()
    with dataset_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            txt = obj.get("text_canonical") or obj.get("text_raw") or ""
            for t in tokenize(txt):
                tokens.add(t)
            # opcional: também indexar title/path/section_path como tokens
            title = obj.get("title") or ""
            for t in tokenize(title):
                tokens.add(t)
            src = obj.get("source") or {}
            path = src.get("path") or ""
            for t in tokenize(path):
                tokens.add(t)
    return tokens


def is_banned(term_norm: str) -> bool:
    if not term_norm:
        return True
    if term_norm in BANNED_GENERIC:
        return True
    if term_norm in BANNED_TOKENS:
        return True
    if len(term_norm) < 3:
        return True
    return False


def validate_lexicon(
    lex_groups: Any,
    short_allowlist: Any,
    *,
    dataset_tokens: Set[str] | None = None,
    max_variants: int = 6,
) -> List[Issue]:
    issues: List[Issue] = []

    if not isinstance(lex_groups, dict):
        return [Issue("LEX_GROUPS_NOT_DICT", f"LEX_GROUPS must be dict, got {type(lex_groups).__name__}.")]

    if not isinstance(short_allowlist, (set, frozenset)):
        return [Issue("SHORT_ALLOWLIST_NOT_SET", "SHORT_TOKEN_ALLOWLIST must be a set.")]

    # 1) valida estrutura dos grupos
    for gid, g in lex_groups.items():
        if not isinstance(gid, str) or not gid:
            issues.append(Issue("GROUP_ID_INVALID", f"Invalid group_id: {gid!r}"))
            continue
        if not isinstance(g, dict):
            issues.append(Issue("GROUP_NOT_DICT", f"Group {gid!r} must be dict."))
            continue
        canonical = g.get("canonical")
        variants = g.get("variants")
        if not isinstance(canonical, str) or not canonical:
            issues.append(Issue("CANONICAL_MISSING", f"Group {gid!r} missing canonical."))
        if not isinstance(variants, list) or not all(isinstance(x, str) for x in variants):
            issues.append(Issue("VARIANTS_INVALID", f"Group {gid!r} variants must be list[str]."))
        if isinstance(variants, list) and len(variants) == 0:
            issues.append(Issue("VARIANTS_EMPTY", f"Group {gid!r} variants empty."))
        if isinstance(variants, list) and len(variants) > max_variants:
            issues.append(Issue("VARIANTS_TOO_MANY", f"Group {gid!r} has {len(variants)} variants > {max_variants}."))

    if issues:
        return issues  # fail-fast estrutural

    # 2) normalização + banned + tokens curtos + presença no acervo
    for gid, g in lex_groups.items():
        canon_raw = g["canonical"]
        canon = normalize_term(canon_raw)
        if canon != canon_raw:
            issues.append(Issue("CANONICAL_NOT_NORMALIZED", f"{gid}: canonical {canon_raw!r} -> {canon!r}"))

        if is_banned(canon):
            issues.append(Issue("CANONICAL_BANNED", f"{gid}: canonical banned/generic {canon_raw!r}"))

        seen: Set[str] = set()
        for v_raw in g["variants"]:
            v = normalize_term(v_raw)
            if v != v_raw:
                issues.append(Issue("VARIANT_NOT_NORMALIZED", f"{gid}: variant {v_raw!r} -> {v!r}"))
            if is_banned(v):
                issues.append(Issue("VARIANT_BANNED", f"{gid}: variant banned/generic {v_raw!r}"))

            # tokens curtos perigosos
            if len(v) <= 3 and v not in short_allowlist:
                issues.append(Issue("SHORT_TOKEN_NOT_ALLOWED", f"{gid}: short token {v!r} not in SHORT_TOKEN_ALLOWLIST"))

            if v in seen:
                issues.append(Issue("DUP_VARIANT_IN_GROUP", f"{gid}: duplicate variant {v!r}"))
            seen.add(v)

            # gate de presença no acervo
            if dataset_tokens is not None and v not in dataset_tokens:
                issues.append(Issue("OOV_VARIANT_NOT_IN_DATASET", f"{gid}: variant {v!r} not found in dataset tokens"))

    return issues
