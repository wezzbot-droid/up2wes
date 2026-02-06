#!/usr/bin/env python3
# scripts/query_hybrid.py
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_exe = (sys.executable or "").replace("/", "\\").lower()
if "\\.venv\\scripts\\python.exe" not in _exe:
    print(
        "[FATAL] Use o Python da .venv para este script: "
        "${workspaceFolder}\\.venv\\Scripts\\python.exe"
    )
    raise SystemExit(2)

import psycopg

# Bootstrap: permite `from uptowes...` sem precisar instalar pacote
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from uptowes.db import connect
from uptowes.lexicon_runtime import load_lexicon, tokens
from uptowes.retrieval import hybrid_search


_GENERIC_TERMS = {
    "dor",
    "febre",
    "sinal",
    "sinais",
    "sintoma",
    "sintomas",
    "criterio",
    "criterios",
    "escala",
    "classificacao",
    "diagnostico",
    "tratamento",
    "manejo",
    "agudo",
    "aguda",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True, help="Query string")
    ap.add_argument("--top", type=int, default=8, help="Top K results")
    ap.add_argument("--lex-only", action="store_true", help="Disable vector; lexical only")
    ap.add_argument("--w-vec", type=float, default=0.6)
    ap.add_argument("--w-lex", type=float, default=0.4)
    args = ap.parse_args()

    q = (args.query or "").strip()
    if not q:
        print("[FATAL] empty query")
        return 2

    enable_vector = not args.lex_only
    w_vec = 0.0 if args.lex_only else float(args.w_vec)
    w_lex = 1.0 if args.lex_only else float(args.w_lex)

    lexicon = os.environ.get("UPTOWES_LEXICON", "").strip()

    print("\n=== Retrieval Results (evidence pointers only) ===")
    print("mode=" + ("LEX_ONLY" if args.lex_only else "HYBRID"))
    print(f"query='{q}'")
    print(f"top={args.top}  enable_vector={enable_vector}  w_vec={w_vec:.2f}  w_lex={w_lex:.2f}")
    print(f"UPTOWES_LEXICON={lexicon if lexicon else '(not set)'}")
    print("\nNOTE: This is retrieval evidence (chunk_id + source), not clinical instruction.\n")

    # Guard de UX/segurança para consultas sem âncora real (ou genéricas) no modo LEX_ONLY
    if args.lex_only and lexicon:
        lex = load_lexicon(lexicon)
        anchor_token, must_groups, _ = lex.expand_query(q)
        q_tokens = tokens(q)
        matched_alias_groups = {lex.aliases[t] for t in q_tokens if t in lex.aliases}
        group_terms = {t for g in must_groups for t in g if t}
        only_generic_terms = bool(group_terms) and group_terms.issubset(_GENERIC_TERMS)
        no_anchor = (not anchor_token) or (not matched_alias_groups)
        if no_anchor or only_generic_terms:
            print("[NO_HITS]")
            print(
                "Sugestão: inclua um termo-âncora (diagnóstico/procedimento/órgão), "
                "ex: 'abdome agudo', 'apendicite', 'peritonite'."
            )
            return 0

    # Conexão DB (usa a mesma config do projeto)
    conn = connect()

    hits = hybrid_search(
        conn=conn,
        query=q,
        top=int(args.top),
        w_vec=w_vec,
        w_lex=w_lex,
        enable_vector=enable_vector,
    )

    if not hits:
        print("[NO_HITS]")
        return 0

    # lex_mode vem em cada Hit; eles devem ser iguais (mesmo batch)
    lex_mode = hits[0].lex_mode
    print(f"lex_mode={lex_mode}\n")

    for i, h in enumerate(hits, start=1):
        snippet = (h.text or "").strip().replace("\n", " ")
        if len(snippet) > 220:
            snippet = snippet[:220] + "..."

        print(f"{i}. score={h.score:.3f} vec={h.score_vec:.3f} lex={h.score_lex:.3f} lex_mode={h.lex_mode} [{h.source_table}] {h.chunk_id}")
        print(f"   doc={h.doc_id} path={h.source_path} loc={h.locator} title={h.title} type={h.chunk_type}")
        print(f"   {snippet}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


