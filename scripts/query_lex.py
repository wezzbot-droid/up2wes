#!/usr/bin/env python3
# scripts/query_lex.py
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple, Set

WORD_RE = re.compile(r"[a-z0-9]+")


# -------------------------
# Normalização / tokenização
# -------------------------
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


# -------------
# BM25 (baseline)
# -------------
def bm25_score(
    query_tokens: List[str],
    doc_tokens: List[str],
    df: Dict[str, int],
    N: int,
    avgdl: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    tf = Counter(doc_tokens)
    score = 0.0
    dl = len(doc_tokens)
    for t in query_tokens:
        if t not in tf:
            continue
        n_q = df.get(t, 0)
        # IDF w/ +0.5 smoothing
        idf = math.log((N - n_q + 0.5) / (n_q + 0.5) + 1.0)
        denom = tf[t] + k1 * (1 - b + b * (dl / (avgdl + 1e-9)))
        score += idf * ((tf[t] * (k1 + 1)) / (denom + 1e-9))
    return score


# -------------------------
# Lexicon loader
# -------------------------
def load_lexicon(path: Path) -> Dict[str, Any]:
    """
    Espera um .py com:
      - LEX_GROUPS: dict[group_id] -> {"canonical": str, "variants": list[str], opcional "is_rare": bool, "is_anchor_hint": bool}
    """
    spec = importlib.util.spec_from_file_location("lexicon_mod", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    lex_groups = getattr(mod, "LEX_GROUPS", None)
    if lex_groups is None:
        raise ValueError("LEX_GROUPS not found in lexicon file.")
    if not isinstance(lex_groups, dict):
        raise ValueError("LEX_GROUPS must be a dict.")
    return {"LEX_GROUPS": lex_groups}


# -------------------------
# MUST_GROUPS builder
# -------------------------
def build_must_groups(query: str, lex_groups: Dict[str, Any]) -> Tuple[List[Set[str]], str, Set[str]]:
    """
    Retorna:
      - groups: lista de sets (OR dentro do grupo)
      - anchor: token âncora (normalizado) (primeiro grupo SEMPRE)
      - rare_union: união dos termos de grupos marcados is_rare (usado no gate)
    Regras:
      - detecta grupos cujo conjunto de variantes intersecta tokens da query
      - escolhe âncora:
          * se houver grupo com is_anchor_hint presente na query -> anchor = canonical desse grupo (normalizado)
          * senão -> anchor = primeiro token da query
      - garante que anchor é hard group {anchor} no início
    """
    q_tokens = tokenize(query)
    if not q_tokens:
        return [], "", set()

    # pré-processa grupos: normaliza variantes e canonical
    gid_to_terms: Dict[str, Set[str]] = {}
    gid_is_rare: Dict[str, bool] = {}
    gid_is_anchor_hint: Dict[str, bool] = {}
    token_to_gid: Dict[str, str] = {}

    for gid, g in lex_groups.items():
        if not isinstance(g, dict):
            continue
        variants = g.get("variants") or []
        canon = g.get("canonical") or ""
        terms = set()
        for v in variants:
            nv = normalize_term(v)
            if nv:
                terms.add(nv)
        # também inclui canonical como termo do grupo (se não estiver)
        ncanon = normalize_term(canon)
        if ncanon:
            terms.add(ncanon)

        if not terms:
            continue

        gid_to_terms[gid] = terms
        gid_is_rare[gid] = bool(g.get("is_rare", False))
        gid_is_anchor_hint[gid] = bool(g.get("is_anchor_hint", False))

        # índice reverso (token -> gid) (se 2 grupos tiverem mesmo token, o último sobrescreve;
        # isso é aceitável aqui porque o lexicon "por grupos" deve evitar duplicar token em grupos diferentes
        # quando NÃO for equivalência)
        for t in terms:
            token_to_gid[t] = gid

    # detecta quais grupos aparecem na query
    seen_gids: List[str] = []
    for t in q_tokens:
        gid = token_to_gid.get(t)
        if gid and gid not in seen_gids:
            seen_gids.append(gid)

    # união de rare terms (de grupos presentes)
    rare_union: Set[str] = set()
    for gid in seen_gids:
        if gid_is_rare.get(gid, False):
            rare_union |= gid_to_terms.get(gid, set())

    # escolhe âncora
    anchor = ""
    for gid in seen_gids:
        if gid_is_anchor_hint.get(gid, False):
            # usa canonical se disponível
            canon = normalize_term(lex_groups[gid].get("canonical") or "")
            anchor = canon or q_tokens[0]
            break
    if not anchor:
        anchor = q_tokens[0]

    # groups = [ {anchor} ] + grupos detectados (exceto os que já contêm anchor)
    groups: List[Set[str]] = [{anchor}]
    for gid in seen_gids:
        terms = gid_to_terms.get(gid, set())
        if not terms:
            continue
        if anchor in terms:
            continue
        groups.append(terms)

    return groups, anchor, rare_union


def cov_groups(doc_tok_set: Set[str], groups: List[Set[str]]) -> Tuple[int, int]:
    hit = 0
    for g in groups:
        if doc_tok_set.intersection(g):
            hit += 1
    return hit, len(groups)


def has_any(doc_tok_set: Set[str], terms: Set[str]) -> bool:
    if not terms:
        return True
    return bool(doc_tok_set.intersection(terms))


# -------------------------
# Main
# -------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="Query string")
    ap.add_argument("--dataset", default="dataset/chunks.jsonl", help="Path to chunks.jsonl")
    ap.add_argument("--top", type=int, default=8, help="Top K results")
    ap.add_argument("--lexicon", default="src/uptowes/lexicon/ptbr_surgery_v1.py", help="Path to lexicon .py with LEX_GROUPS")
    ap.add_argument("--min-cov-groups", type=float, default=0.67, help="Min coverage ratio for groups (0.67 ~ 2/3)")
    args = ap.parse_args()

    ds_path = Path(args.dataset)
    if not ds_path.exists():
        print(f"[FATAL] Dataset not found: {ds_path}")
        return 2

    lex_path = Path(args.lexicon)
    if not lex_path.exists():
        print(f"[FATAL] Lexicon not found: {lex_path}")
        return 2

    lex = load_lexicon(lex_path)
    groups, anchor, rare_union = build_must_groups(args.query, lex["LEX_GROUPS"])

    # Load dataset + build df for BM25
    chunks: List[Dict[str, Any]] = []
    docs_tokens: List[List[str]] = []
    docs_tok_sets: List[Set[str]] = []
    df = defaultdict(int)

    with ds_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            chunks.append(c)
            text = c.get("text_canonical") or c.get("text_raw") or ""
            toks = tokenize(text)
            docs_tokens.append(toks)
            tset = set(toks)
            docs_tok_sets.append(tset)
            for t in tset:
                df[t] += 1

    N = len(chunks)
    if N == 0:
        print("[FATAL] Empty dataset.")
        return 2

    avgdl = sum(len(t) for t in docs_tokens) / max(N, 1)
    qtok = tokenize(args.query)

    # thresholds
    total_groups = len(groups)
    if total_groups == 0:
        print("[NO_HITS] empty query after tokenization.")
        return 0

    # mínimo de grupos a acertar:
    # - se só 1 grupo (âncora), exige 1
    # - se 2+ grupos, exige ceil(ratio * total)
    min_hits = 1 if total_groups <= 1 else max(2, math.ceil(args.min_cov_groups * total_groups))

    def relax_gate(doc_set: Set[str]) -> Tuple[bool, str]:
        # 1) âncora hard
        if anchor and anchor not in doc_set:
            return False, "NO_ANCHOR"
        # 2) cobertura por grupos
        hit, tot = cov_groups(doc_set, groups)
        if tot > 1 and hit < min_hits:
            return False, f"LOW_COV_GROUPS {hit}/{tot} < {min_hits}"
        # 3) rare group (se existe na query)
        if rare_union and not has_any(doc_set, rare_union):
            return False, "NO_RARE_GROUP"
        return True, "OK"

    # -------------------------
    # STRICT_GROUPS = aplicar gate (mesmo gate) e rankear por BM25
    # (isso substitui seu "STRICT" anterior: é o modo forte)
    # -------------------------
    strict_scored: List[Tuple[float, int, str]] = []  # score, idx, covstr
    for i, doc_set in enumerate(docs_tok_sets):
        ok, _why = relax_gate(doc_set)
        if not ok:
            continue
        s = bm25_score(qtok, docs_tokens[i], df, N, avgdl)
        if s > 0:
            hit, tot = cov_groups(doc_set, groups)
            strict_scored.append((s, i, f"{hit}/{tot}"))
    strict_scored.sort(reverse=True, key=lambda x: x[0])

    results = strict_scored
    mode_used = "STRICT_GROUPS"

    # -------------------------
    # RELAX_GATED = fallback: score>0 + gate (mesmo gate)
    # -------------------------
    if not results:
        relax_scored: List[Tuple[float, int, str]] = []
        for i, doc_set in enumerate(docs_tok_sets):
            s = bm25_score(qtok, docs_tokens[i], df, N, avgdl)
            if s <= 0:
                continue
            ok, _why = relax_gate(doc_set)
            if not ok:
                continue
            hit, tot = cov_groups(doc_set, groups)
            relax_scored.append((s, i, f"{hit}/{tot}"))
        relax_scored.sort(reverse=True, key=lambda x: x[0])
        results = relax_scored
        mode_used = "RELAX_GATED" if results else "NO_HITS"

    # output
    print("\n=== Retrieval Results (evidence pointers only) ===")
    print("mode=LEX_ONLY (no patient-specific guidance)")
    print(f"query={args.query!r}")
    print(f"dataset={str(ds_path)}")
    print(f"lexicon={str(lex_path)}")
    print(f"anchor={anchor!r}")
    print(f"groups={len(groups)} min_group_hits={min_hits} (min_cov_groups={args.min_cov_groups})")
    print(f"retrieval_mode={mode_used}")
    print("NOTE: evidence only (chunk_id + source), not clinical instruction.\n")

    if not results:
        print("[NO_HITS] (either none found, or all filtered by anchor/cov_groups/rare)\n")
        return 0

    for rank, (score, idx, covstr) in enumerate(results[: args.top], start=1):
        c = chunks[idx]
        src = c.get("source") or {}
        print(f"#{rank} score={score:.4f} mode={mode_used} cov_groups={covstr} type={c.get('chunk_type')} title={c.get('title')}")
        print(f"   id={c.get('chunk_id')}")
        print(f"   path={src.get('path')} loc={src.get('locator')}")
        sp = c.get("section_path") or []
        if sp:
            print(f"   section={' > '.join(sp)}")
        snippet = (c.get("text_raw") or "").strip().replace("\n", " ")
        if len(snippet) > 220:
            snippet = snippet[:220] + "..."
        print(f"   {snippet}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
