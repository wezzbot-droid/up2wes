#!/usr/bin/env python3
# scripts/query_lex.py
from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Any

WORD_RE = re.compile(r"[a-z0-9]+")

def deaccent(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))

def tokenize(s: str) -> List[str]:
    s = deaccent(s.lower())
    return WORD_RE.findall(s)

def bm25_score(query_tokens: List[str], doc_tokens: List[str], df: Dict[str, int], N: int, avgdl: float, k1: float = 1.5, b: float = 0.75) -> float:
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

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="Query string")
    ap.add_argument("--dataset", default="dataset/chunks.jsonl", help="Path to chunks.jsonl")
    ap.add_argument("--top", type=int, default=8, help="Top K results")
    args = ap.parse_args()

    ds_path = Path(args.dataset)
    if not ds_path.exists():
        print(f"[FATAL] Dataset not found: {ds_path}")
        return 2

    chunks: List[Dict[str, Any]] = []
    docs_tokens: List[List[str]] = []
    df = defaultdict(int)

    # Load
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
            for t in set(toks):
                df[t] += 1

    N = len(chunks)
    if N == 0:
        print("[FATAL] Empty dataset.")
        return 2

    avgdl = sum(len(t) for t in docs_tokens) / max(N, 1)
    qtok = tokenize(args.query)

    scored: List[Tuple[float, int]] = []
    for i, toks in enumerate(docs_tokens):
        s = bm25_score(qtok, toks, df, N, avgdl)
        if s > 0:
            scored.append((s, i))
    scored.sort(reverse=True, key=lambda x: x[0])

    print(f"[OK] query='{args.query}' hits={len(scored)}/{N}\n")

    for rank, (score, idx) in enumerate(scored[: args.top], start=1):
        c = chunks[idx]
        src = c.get("source") or {}
        print(f"#{rank}  score={score:.4f}  type={c.get('chunk_type')}  title={c.get('title')}")
        print(f"    id={c.get('chunk_id')}")
        print(f"    path={src.get('path')}  loc={src.get('locator')}")
        sp = c.get("section_path") or []
        if sp:
            print(f"    section={' > '.join(sp)}")
        snippet = (c.get("text_raw") or "").strip().replace("\n", " ")
        if len(snippet) > 220:
            snippet = snippet[:220] + "..."
        print(f"    {snippet}\n")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
