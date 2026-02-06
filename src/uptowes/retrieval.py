from __future__ import annotations

import os
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import psycopg

from uptowes.embeddings import ollama_embed
from uptowes.lexicon_runtime import (
    load_lexicon,
    build_tsquery_from_groups,
    group_coverage,
    tokens as lex_tokens,
)


@dataclass(frozen=True)
class Hit:
    source_table: str              # chunks_text | table_rows
    chunk_id: str
    doc_id: str
    source_path: str
    locator: str
    title: str
    chunk_type: str
    text: str
    score_vec: float
    score_lex: float
    score: float
    lex_mode: str                  # STRICT | RELAX | STRICT_GROUPS | RELAX_GROUPS | NONE
    lex_tsquery_groups_str: str = ""
    lex_rest_text: str = ""


_WORD_RE = re.compile(r"[0-9A-Za-zÀ-ÿ]+")
_GENERIC_QUERY_TERMS = {
    "sindrome",
    "criterio",
    "criterios",
    "diagnostico",
    "diagnosticos",
    "tratamento",
    "conduta",
    "tipo",
    "grau",
    "classificacao",
    "classificacoes",
    "guideline",
    "guidelines",
    "protocolo",
    "manejo",
    "indicacao",
    "indicacoes",
}
_DISCRIMINATIVE_WHITELIST = {
    "tokyo",
    "cpre",
    "ercp",
    "alvarado",
    "hinchey",
    "mirizzi",
    "csendes",
    "figo",
    "tnm",
    "bisap",
    "apache",
    "ranson",
}


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _normalize_scores(scores: List[float]) -> List[float]:
    if not scores:
        return []
    mx = max(scores)
    if mx <= 0:
        return [0.0 for _ in scores]
    return [float(s) / float(mx) for s in scores]


def _unique_preserve(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for it in items:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out


def _query_terms(query: str) -> List[str]:
    return _unique_preserve([t for t in lex_tokens(query) if t])


def _coverage_ratio(text: str, query: str) -> float:
    q_terms = _query_terms(query)
    if not q_terms:
        return 0.0
    txt_terms = set(_query_terms(text))
    if not txt_terms:
        return 0.0
    hits = sum(1 for t in q_terms if t in txt_terms)
    return float(hits) / float(len(q_terms))


def _dedupe_by_chunk_id_keep_best(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        cid = str(r.get("chunk_id") or "")
        if not cid:
            continue
        cur = best.get(cid)
        score = float(r.get("score_lex") or 0.0)
        if cur is None or score > float(cur.get("score_lex") or 0.0):
            best[cid] = r
    return list(best.values())


def _is_discriminative_term(term: str) -> bool:
    t = (term or "").strip().lower()
    if not t:
        return False
    if t in _DISCRIMINATIVE_WHITELIST:
        return True
    if t in _GENERIC_QUERY_TERMS:
        return False
    return len(t) >= 6


def _is_groups_query_poor(
    anchor_token: Optional[str],
    must_groups: List[set[str]],
    discriminative_terms: List[str],
    tsquery_groups_str: str,
) -> bool:
    if not (tsquery_groups_str or "").strip():
        return True
    anchor = (anchor_token or "").strip().lower()
    return len(must_groups) <= 1 and anchor in _GENERIC_QUERY_TERMS and not discriminative_terms


def _has_column(conn: psycopg.Connection, table: str, column: str) -> bool:
    sql = """
    SELECT 1
    FROM information_schema.columns
    WHERE table_name=%s AND column_name=%s
    LIMIT 1;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (table, column))
        return cur.fetchone() is not None


def _has_unaccent(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname='unaccent' LIMIT 1;")
        return cur.fetchone() is not None


def _vector_search(conn: psycopg.Connection, table: str, query_vec: list[float], limit: int) -> List[Dict[str, Any]]:
    if table == "chunks_text":
        sql = """
        SELECT
          'chunks_text' AS source_table,
          chunk_id, doc_id, source_path, locator, title, chunk_type,
          text_canonical AS text,
          (1 - (embedding <=> %s)) AS score_vec
        FROM chunks_text
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s
        LIMIT %s;
        """
    else:
        sql = """
        SELECT
          'table_rows' AS source_table,
          chunk_id, doc_id, source_path, locator, title, chunk_type,
          row_text_canonical AS text,
          (1 - (embedding <=> %s)) AS score_vec
        FROM table_rows
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s
        LIMIT %s;
        """

    with conn.cursor() as cur:
        cur.execute(sql, (query_vec, query_vec, limit))
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _lex_search_strict_or_relax(conn: psycopg.Connection, table: str, query: str, limit: int) -> Tuple[List[Dict[str, Any]], str]:
    """
    Deterministic lexical strategy:
    1) STRICT: plainto_tsquery (AND)
    2) if 0 hits: RELAX: websearch_to_tsquery with tokens joined by " OR " (still dictionary-aware)

    Also prefers content_tsv_u when present (accent-insensitive precomputed tsvector).
    """
    q = (query or "").strip()
    if not q:
        return ([], "NONE")

    use_unaccent = _has_unaccent(conn)

    # Prefer unaccented tsvector if migration 002 applied
    tsv_col = "content_tsv_u" if _has_column(conn, table, "content_tsv_u") else "content_tsv"

    if table == "chunks_text":
        text_col = "text_canonical"
        base_sql = f"""
        SELECT
          'chunks_text' AS source_table,
          chunk_id, doc_id, source_path, locator, title, chunk_type,
          {text_col} AS text,
          ts_rank_cd({tsv_col}, q.tq) AS score_lex
        FROM chunks_text, q
        WHERE {tsv_col} @@ q.tq
        ORDER BY score_lex DESC
        LIMIT %s;
        """
    else:
        text_col = "row_text_canonical"
        base_sql = f"""
        SELECT
          'table_rows' AS source_table,
          chunk_id, doc_id, source_path, locator, title, chunk_type,
          {text_col} AS text,
          ts_rank_cd({tsv_col}, q.tq) AS score_lex
        FROM table_rows, q
        WHERE {tsv_col} @@ q.tq
        ORDER BY score_lex DESC
        LIMIT %s;
        """

    # STRICT (AND)
    if use_unaccent:
        strict_cte = "WITH q AS (SELECT plainto_tsquery('portuguese', unaccent(%s)) AS tq)"
    else:
        strict_cte = "WITH q AS (SELECT plainto_tsquery('portuguese', %s) AS tq)"
    strict_sql = strict_cte + "\n" + base_sql

    with conn.cursor() as cur:
        cur.execute(strict_sql, (q, limit))
        rows = cur.fetchall()
        if rows:
            cols = [c.name for c in cur.description]
            return ([dict(zip(cols, r)) for r in rows], "STRICT")

    # RELAX (OR)
    tokens = _WORD_RE.findall(q)
    if not tokens:
        tokens = [q]
    q_or = " OR ".join(tokens)

    if use_unaccent:
        relax_cte = "WITH q AS (SELECT websearch_to_tsquery('portuguese', unaccent(%s)) AS tq)"
    else:
        relax_cte = "WITH q AS (SELECT websearch_to_tsquery('portuguese', %s) AS tq)"
    relax_sql = relax_cte + "\n" + base_sql

    with conn.cursor() as cur:
        cur.execute(relax_sql, (q_or, limit))
        cols = [c.name for c in cur.description]
        return ([dict(zip(cols, r)) for r in cur.fetchall()], "RELAX")


def _lex_search_groups(
    conn: psycopg.Connection,
    table: str,
    tsquery_str: str,
    rest_text: str,
    limit: int,
    use_unaccent: bool = True,
) -> List[Dict[str, Any]]:
    """
    Busca lexical usando um tsquery já montado (AND/OR).
    Usa to_tsquery('portuguese', <tsquery_str>).
    """
    # preferir content_tsv_u quando existir (mesma lógica do strict/relax)
    tsv_col = "content_tsv_u" if _has_column(conn, table, "content_tsv_u") else "content_tsv"

    if table == "chunks_text":
        text_col = "text_canonical"
    else:
        text_col = "row_text_canonical"

    base_sql = f"""
SELECT
  '{table}'::text AS source_table,
  chunk_id,
  doc_id,
  source_path,
  locator,
  title,
  chunk_type,
  {text_col} AS text,
  (ts_rank({tsv_col}, q.qg) + 0.25 * ts_rank({tsv_col}, q.qr)) AS score_lex
FROM {table} c
CROSS JOIN q
WHERE
  q.qg <> ''::tsquery
  AND c.{tsv_col} @@ q.qg
ORDER BY score_lex DESC, c.chunk_id ASC
LIMIT %s
""".strip()

    if use_unaccent:
        cte = """
WITH q AS (
  SELECT
    to_tsquery('portuguese', unaccent(%s)) AS qg,
    CASE
      WHEN %s = '' THEN ''::tsquery
      ELSE plainto_tsquery('portuguese', unaccent(%s))
    END AS qr
)
""".strip()
    else:
        cte = """
WITH q AS (
  SELECT
    to_tsquery('portuguese', %s) AS qg,
    CASE
      WHEN %s = '' THEN ''::tsquery
      ELSE plainto_tsquery('portuguese', %s)
    END AS qr
)
""".strip()

    sql = cte + "\n" + base_sql

    with conn.cursor() as cur:
        cur.execute(sql, (tsquery_str, rest_text, rest_text, limit))
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def hybrid_search(
    conn: psycopg.Connection,
    query: str,
    top: int = 8,
    w_vec: float = 0.6,
    w_lex: float = 0.4,
    vec_k: Optional[int] = None,
    lex_k: Optional[int] = None,
    embed_model: Optional[str] = None,
    enable_vector: bool = True,
) -> List[Hit]:
    """
    Retrieval híbrido (lex + vetor), com estratégia determinística:

    1) Sem lexicon: STRICT -> RELAX fallback (comportamento legado)
    2) Com lexicon: usa expand_query + grupos (STRICT_GROUPS / RELAX_GROUPS)
       com gates de precisão (âncora hard, cobertura mínima e rare gate)
    """
    q = (query or "").strip()
    if not q:
        return []

    vec_k = vec_k or max(20, top * 4)
    lex_k = lex_k or max(20, top * 4)

    # ---------------------------
    # Lexicon runtime (fail-fast)
    # ---------------------------
    lexicon_path = (os.environ.get("UPTOWES_LEXICON") or "").strip()
    lex = None
    anchor_token: Optional[str] = None
    must_groups: List[set[str]] = []
    rare_group_ids: set[str] = set()
    rest_terms: set[str] = set()
    tsquery_groups_str = ""
    rest_text = ""
    discriminative_terms: List[str] = []
    if lexicon_path:
        try:
            lex = load_lexicon(lexicon_path)
            expanded = lex.expand_query(q)
            if isinstance(expanded, tuple) and len(expanded) >= 4:
                anchor_token = expanded[0]
                must_groups = expanded[1]
                rare_group_ids = set(expanded[2] or set())
                rest_terms = set(expanded[3] or set())
            else:
                anchor_token, must_groups, rare_group_ids = expanded
            matched_terms = {t for g in must_groups for t in g if t}

            # Fallback equivalente: termos da query que nao foram absorvidos pelos grupos.
            query_terms = _query_terms(q)
            if not rest_terms:
                rest_terms = {t for t in query_terms if t and t not in matched_terms}

            # Preserva ordem da query para evitar escolher termo pouco útil primeiro.
            rest_terms_ordered = [t for t in query_terms if t in rest_terms and t not in matched_terms]
            rest_terms_ordered = _unique_preserve(rest_terms_ordered)
            rest_text = " ".join(rest_terms_ordered)

            base_groups_tsquery = build_tsquery_from_groups(must_groups)
            discriminative_terms = [t for t in rest_terms_ordered if _is_discriminative_term(t)][:2]
            if base_groups_tsquery and discriminative_terms:
                if len(discriminative_terms) == 1:
                    tsquery_groups_str = f"({base_groups_tsquery}) & {discriminative_terms[0]}"
                else:
                    tsquery_groups_str = f"({base_groups_tsquery}) & ({' | '.join(discriminative_terms)})"
            else:
                tsquery_groups_str = base_groups_tsquery
        except Exception as exc:
            raise RuntimeError(f"Failed to load lexicon from '{lexicon_path}'") from exc

    # ---------------------------
    # Lex retrieval
    # ---------------------------
    lex_rows: List[Dict[str, Any]] = []
    lex_mode = "NONE"

    if lex:
        use_unaccent = _has_unaccent(conn)
        anchor_group: set[str] = set(must_groups[0]) if must_groups else ({anchor_token} if anchor_token else set())
        rare_groups: List[set[str]] = []
        if rare_group_ids:
            for gid in sorted(rare_group_ids):
                g = lex.groups.get(gid) or {}
                variants = {str(v) for v in (g.get("variants") or []) if str(v).strip()}
                if variants:
                    rare_groups.append(variants)

        total_groups = len(must_groups)
        strict_min_group_hits = total_groups
        relax_min_group_hits = total_groups if total_groups < 3 else int(math.ceil(0.67 * total_groups))
        groups_query_poor = _is_groups_query_poor(
            anchor_token=anchor_token,
            must_groups=must_groups,
            discriminative_terms=discriminative_terms,
            tsquery_groups_str=tsquery_groups_str,
        )

        def _apply_group_gates(rows: List[Dict[str, Any]], min_group_hits: int) -> List[Dict[str, Any]]:
            if not rows:
                return []

            kept: List[Dict[str, Any]] = []
            for r in rows:
                txt = str(r.get("text") or "")

                # anchor hard: precisa bater no grupo âncora
                if anchor_group and group_coverage(txt, [anchor_group]) < 1:
                    continue

                # cobertura mínima de must_groups
                if must_groups and min_group_hits > 0 and group_coverage(txt, must_groups) < min_group_hits:
                    continue

                # rare gate: se houver grupos raros, precisa bater ao menos 1
                if rare_groups and group_coverage(txt, rare_groups) < 1:
                    continue

                kept.append(r)

            return kept

        # STRICT_GROUPS (MVP): 2-pass (GROUPS + STRICT(rest_text)) + merge + rerank determinístico.
        strict_fetch_k = max(lex_k * 10, lex_k)
        strict_groups_rows: List[Dict[str, Any]] = []
        if tsquery_groups_str and not groups_query_poor:
            strict_rows_ct = _lex_search_groups(
                conn,
                "chunks_text",
                tsquery_groups_str,
                rest_text,
                strict_fetch_k,
                use_unaccent=use_unaccent,
            )
            strict_rows_tr = _lex_search_groups(
                conn,
                "table_rows",
                tsquery_groups_str,
                rest_text,
                strict_fetch_k,
                use_unaccent=use_unaccent,
            )
            strict_groups_rows = strict_rows_ct + strict_rows_tr

        strict_rest_rows: List[Dict[str, Any]] = []
        if rest_text:
            strict_rest_ct, strict_mode_ct = _lex_search_strict_or_relax(conn, "chunks_text", rest_text, strict_fetch_k)
            strict_rest_tr, strict_mode_tr = _lex_search_strict_or_relax(conn, "table_rows", rest_text, strict_fetch_k)
            if strict_mode_ct == "STRICT":
                strict_rest_rows.extend(strict_rest_ct)
            if strict_mode_tr == "STRICT":
                strict_rest_rows.extend(strict_rest_tr)

        strict_merged = _dedupe_by_chunk_id_keep_best(strict_groups_rows + strict_rest_rows)
        for r in strict_merged:
            r["_cov_ratio"] = _coverage_ratio(str(r.get("text") or ""), q)
        strict_merged.sort(
            key=lambda r: (
                -float(r.get("_cov_ratio") or 0.0),
                -float(r.get("score_lex") or 0.0),
                str(r.get("chunk_id") or ""),
            )
        )

        strict_rows = _apply_group_gates(strict_merged, strict_min_group_hits)
        if strict_rows:
            strict_rows = strict_rows[:lex_k]
        else:
            strict_rows = []

        if strict_rows:
            lex_rows = strict_rows
            lex_mode = "STRICT_GROUPS"
        else:
            if groups_query_poor:
                # Fallback seguro: evita query de grupos genérica (ex.: apenas "sindrome").
                fallback_rows_ct, mode_ct = _lex_search_strict_or_relax(conn, "chunks_text", q, lex_k)
                fallback_rows_tr, mode_tr = _lex_search_strict_or_relax(conn, "table_rows", q, lex_k)
                fallback_rows = fallback_rows_ct + fallback_rows_tr
                if fallback_rows:
                    lex_rows = fallback_rows
                    lex_mode = "RELAX" if ("RELAX" in (mode_ct, mode_tr)) else "STRICT"
            else:
                # RELAX_GROUPS: baseline STRICT/RELAX + gate mínimo por grupos
                relax_rows_ct, _ = _lex_search_strict_or_relax(conn, "chunks_text", q, lex_k)
                relax_rows_tr, _ = _lex_search_strict_or_relax(conn, "table_rows", q, lex_k)
                relax_rows = _apply_group_gates(relax_rows_ct + relax_rows_tr, relax_min_group_hits)
                if relax_rows:
                    lex_rows = relax_rows
                    lex_mode = "RELAX_GROUPS"
    else:
        # Sem lexicon: comportamento legado
        lex_rows_ct, lex_mode_ct = _lex_search_strict_or_relax(conn, "chunks_text", q, lex_k)
        lex_rows_tr, lex_mode_tr = _lex_search_strict_or_relax(conn, "table_rows", q, lex_k)
        lex_rows = lex_rows_ct + lex_rows_tr
        lex_mode = "RELAX" if ("RELAX" in (lex_mode_ct, lex_mode_tr)) else ("STRICT" if lex_rows else "NONE")

    # ---------------------------
    # Vector
    # ---------------------------
    vec_rows: List[Dict[str, Any]] = []
    if enable_vector:
        query_vec = ollama_embed(q, model=embed_model)
        vec_rows = _vector_search(conn, "chunks_text", query_vec, vec_k) + _vector_search(conn, "table_rows", query_vec, vec_k)

    vec_map: Dict[str, Dict[str, Any]] = {}
    for r in vec_rows:
        cid = r["chunk_id"]
        r["score_vec"] = _clamp01(float(r.get("score_vec") or 0.0))
        if cid not in vec_map or r["score_vec"] > vec_map[cid]["score_vec"]:
            vec_map[cid] = r

    # ---------------------------
    # Normalize lex scores
    # ---------------------------
    lex_scores = [float(r.get("score_lex") or 0.0) for r in lex_rows]
    norm = _normalize_scores(lex_scores)

    lex_map: Dict[str, Dict[str, Any]] = {}
    for r, s in zip(lex_rows, norm):
        cid = r["chunk_id"]
        r["score_lex"] = float(s)
        if cid not in lex_map or r["score_lex"] > lex_map[cid]["score_lex"]:
            lex_map[cid] = r

    # Determinístico
    all_ids = sorted(set(vec_map.keys()) | set(lex_map.keys()))

    hits: List[Hit] = []
    for cid in all_ids:
        base = vec_map.get(cid) or lex_map.get(cid)
        if not base:
            continue

        score_vec = float(vec_map.get(cid, {}).get("score_vec") or 0.0)
        score_lex = float(lex_map.get(cid, {}).get("score_lex") or 0.0)
        score = (w_vec * score_vec) + (w_lex * score_lex)

        hits.append(
            Hit(
                source_table=str(base["source_table"]),
                chunk_id=str(base["chunk_id"]),
                doc_id=str(base["doc_id"]),
                source_path=str(base["source_path"]),
                locator=str(base["locator"]),
                title=str(base["title"]),
                chunk_type=str(base["chunk_type"]),
                text=str(base["text"]),
                score_vec=score_vec,
                score_lex=score_lex,
                score=score,
                lex_mode=lex_mode,
                lex_tsquery_groups_str=tsquery_groups_str,
                lex_rest_text=rest_text,
            )
        )

    hits.sort(key=lambda h: (-h.score, h.chunk_id))
    return hits[:top]
