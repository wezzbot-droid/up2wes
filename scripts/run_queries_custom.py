from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def safe_print(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.buffer.write((msg + "\n").encode(enc, errors="backslashreplace"))


def ensure_venv() -> None:
    if getattr(sys, "base_prefix", sys.prefix) == sys.prefix:
        print("[FATAL] Use o Python da .venv: .venv\\Scripts\\python.exe")
        raise SystemExit(2)


ensure_venv()

from uptowes.db import connect
from uptowes.benchmark_negatives import audit_negative_queries
from uptowes.lexicon.selector import infer_area_from_lexicon_path, resolve_lexicon_path
from uptowes.lexicon_runtime import build_tsquery_from_groups, load_lexicon
from uptowes.retrieval import hybrid_search
from uptowes.validate import validate_lex_mode_contract


DISCLAIMER = (
    "> **Nota de seguranca**: este relatorio e apenas *evidencia recuperada* do acervo (chunk_id + fonte). "
    "Nao e orientacao clinica para paciente real.\n"
)

LEXMODE_NOTE = (
    "> **lex_mode**: `STRICT_GROUPS`/`RELAX_GROUPS`/`GROUPS_QUERY_POOR` indicam retrieval com lexicon.\n"
)
TRUE_VALUES = {"1", "true", "yes", "on"}

STOPWORDS = {
    "a", "o", "as", "os", "um", "uma",
    "de", "da", "do", "das", "dos",
    "e", "ou", "em", "no", "na", "nos", "nas",
    "para", "por", "com", "sem",
    "ao", "aos", "a", "as",
    "que", "se", "ser", "estar",
}

DOMAIN_RARE_HINTS = {
    "antibioticoterapia", "tokyo", "hinchey", "alvarado", "cpre", "ercp",
    "figo", "tnm", "ranson", "apache", "bisap", "glasgow",
}
AREA_SOURCE_PREFIX = {
    "cirurgia": "cirurgia/",
    "clinica": "clinica/",
    "go": "go/",
    "pediatria": "pediatria/",
    "preventiva": "preventiva/",
    "core": None,
}
SCOPED_AREAS_REQUIRE_PREFIX = {"cirurgia", "clinica", "go", "pediatria", "preventiva"}


@dataclass
class QueryCase:
    id: str
    bucket: str
    query: str
    expect_hit: bool


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def normalize_for_terms(s: str) -> str:
    s = strip_accents(s.lower())
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_terms(query: str) -> List[str]:
    s = normalize_for_terms(query)
    return [t for t in s.split(" ") if t and t not in STOPWORDS and len(t) >= 3]


def pick_anchor(terms: List[str]) -> str | None:
    for t in terms:
        if t not in STOPWORDS and len(t) >= 4:
            return t
    return terms[0] if terms else None


def is_must_term(t: str) -> bool:
    return (len(t) >= 8) or any(ch.isdigit() for ch in t) or (t in DOMAIN_RARE_HINTS)


def reduce_query(original_query: str) -> Tuple[str, List[str], List[str]]:
    terms = extract_terms(original_query)
    must = [t for t in terms if is_must_term(t)]
    anchor = pick_anchor(terms)

    if not terms or not anchor:
        return original_query, terms, must

    keep_set = {anchor, *must}
    reduced_terms = []
    seen = set()
    for t in terms:
        if t in keep_set and t not in seen:
            reduced_terms.append(t)
            seen.add(t)

    reduced_query = " ".join(reduced_terms) if reduced_terms else original_query
    if reduced_query == " ".join(terms) or len(reduced_terms) < 2:
        return original_query, terms, must

    return reduced_query, terms, must


def must_term_present(snippet: str, must_terms: List[str]) -> bool:
    if not must_terms:
        return False
    sn = normalize_for_terms(snippet)
    return any(t in sn for t in must_terms)


def term_coverage(snippet: str, query: str) -> Tuple[int, int]:
    terms = extract_terms(query)
    if not terms:
        return 0, 0
    sn = normalize_for_terms(snippet)
    hits = sum(1 for t in terms if t in sn)
    return hits, len(terms)


def is_strong_hit(cov: int, total: int, min_ratio: float) -> bool:
    if total <= 0:
        return False
    if total <= 2:
        return cov >= total
    return cov >= 2 and (cov / total) >= min_ratio


def precision_gate(hits, must_terms: List[str], original_terms: List[str]):
    if not hits:
        return hits
    if hits[0].lex_mode != "RELAX":
        return hits

    filtered = []
    for h in hits:
        snippet = h.text or ""
        if must_terms:
            if must_term_present(snippet, must_terms):
                filtered.append(h)
        else:
            cov, _ = term_coverage(snippet, " ".join(original_terms))
            if cov >= 2:
                filtered.append(h)

    return filtered


def load_cases(path: Path) -> List[QueryCase]:
    rows: List[QueryCase] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        try:
            rows.append(
                QueryCase(
                    id=str(obj["id"]).strip(),
                    bucket=str(obj["bucket"]).strip().upper(),
                    query=str(obj["query"]).strip(),
                    expect_hit=bool(obj["expect_hit"]),
                )
            )
        except KeyError as exc:
            raise ValueError(f"Invalid JSONL at line {lineno}: missing {exc}") from exc

    if not rows:
        raise ValueError("custom_queries.jsonl is empty.")
    return rows


def env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in TRUE_VALUES


def to_repo_path(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else (REPO_ROOT / p).resolve()


def build_report_path(
    out_arg: str | None,
    *,
    lexicon_path: Path,
    area: str,
    include_area_suffix: bool,
    matrix_mode: bool,
) -> Path:
    if out_arg and not matrix_mode:
        return to_repo_path(out_arg)

    if out_arg and matrix_mode:
        base = to_repo_path(out_arg)
        suffix = base.suffix or ".md"
        stem = base.stem if base.suffix else base.name
        return base.with_name(f"{stem}__area-{area}{suffix}")

    lexicon_id = lexicon_path.stem
    filename = f"queries_custom__{lexicon_id}"
    if include_area_suffix:
        filename += f"__area-{area}"
    return (REPO_ROOT / "dataset" / "out" / "reports" / f"{filename}.md").resolve()


def normalize_source_prefix(source_prefix: str | None) -> str | None:
    value = (source_prefix or "").strip()
    return value or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default="dataset/queries/custom_queries.jsonl")
    ap.add_argument("--out", default=None, help="Optional output report path. If omitted, uses deterministic per-lexicon name.")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--min-cov-ratio", type=float, default=(2 / 3))
    ap.add_argument("--embed-model", default="nomic-embed-text")
    ap.add_argument("--lex-only", action="store_true", help="Disable vector search (no Ollama needed).")
    ap.add_argument("--lexicon", default=None, help="Path to lexicon .py (optional override for UPTOWES_LEXICON).")
    ap.add_argument("--area", default=None, help="Lexicon area selector when UPTOWES_LEXICON/--lexicon is not set (ex: cirurgia, core).")
    ap.add_argument("--matrix", action="store_true", help="Run benchmark matrix for areas: cirurgia and core.")
    ap.add_argument("--source-prefix", default=None, help="Optional retrieval scope prefix (ex: cirurgia/).")
    ap.add_argument("--require-lexicon", action="store_true", help="Fail-fast if retrieval falls back to legacy no-lexicon.")
    ap.add_argument(
        "--audit-corpus-jsonl",
        default="dataset/chunks.jsonl",
        help="Corpus JSONL used by preflight gate for negative-query validity.",
    )
    ap.add_argument(
        "--audit-source-prefix",
        action="append",
        default=["cirurgia/"],
        help="Source path prefix to scope negative-query audit (repeatable). Default: cirurgia/",
    )
    ap.add_argument(
        "--audit-max-token-df",
        type=int,
        default=5,
        help="Maximum chunk document-frequency for a token to be considered discriminative in negative-audit.",
    )
    args = ap.parse_args()

    seed_path = (REPO_ROOT / args.seed).resolve()
    if not seed_path.exists():
        print(f"[FATAL] seed not found: {seed_path}")
        return 2

    cases = load_cases(seed_path)

    enable_vector = not args.lex_only
    w_vec = 0.0 if args.lex_only else 0.6
    w_lex = 1.0 if args.lex_only else 0.4

    require_lexicon = bool(args.require_lexicon or env_truthy("UPTOWES_RETRIEVAL_REQUIRE_LEXICON"))
    audit_corpus_path = (REPO_ROOT / args.audit_corpus_jsonl).resolve()
    if not audit_corpus_path.exists():
        print(f"[FATAL] audit corpus jsonl not found: {audit_corpus_path}")
        return 2

    def run_once(selected_area: str, explicit_path: str | None, *, matrix_mode: bool) -> tuple[int, Path, str, str]:
        try:
            lexicon_input = resolve_lexicon_path(selected_area, explicit_path)
        except ValueError as exc:
            print(f"[FATAL] {exc}")
            return 2, Path(), "", ""

        lex_path = to_repo_path(lexicon_input)
        area_label = (selected_area or infer_area_from_lexicon_path(lexicon_input)).strip().lower()
        derived_prefix = AREA_SOURCE_PREFIX.get(area_label, None)
        source_prefix = normalize_source_prefix(args.source_prefix) if args.source_prefix is not None else normalize_source_prefix(derived_prefix)

        if require_lexicon and area_label in SCOPED_AREAS_REQUIRE_PREFIX and not source_prefix:
            safe_print(
                f"[ERROR] require-lexicon with area='{area_label}' requires non-empty source_prefix "
                f"(use --source-prefix or area mapping)."
            )
            return 2, Path(), "", ""

        include_area_suffix = bool(args.matrix or (args.area or "").strip() or (os.environ.get("UPTOWES_AREA") or "").strip())
        out_path = build_report_path(
            args.out,
            lexicon_path=lex_path,
            area=area_label,
            include_area_suffix=include_area_suffix,
            matrix_mode=matrix_mode,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)

        os.environ["UPTOWES_LEXICON"] = str(lex_path)
        if require_lexicon:
            os.environ["UPTOWES_RETRIEVAL_REQUIRE_LEXICON"] = "1"

        safe_print(f"[LEXICON] path={lex_path} area={area_label} require_lexicon={str(require_lexicon).lower()}")
        safe_print(f"[SCOPE] source_prefix={source_prefix if source_prefix else 'NONE'}")
        lex = load_lexicon(str(lex_path))

        preflight_cases = [
            {"id": c.id, "bucket": c.bucket, "query": c.query, "expect_hit": c.expect_hit}
            for c in cases
        ]
        negative_violations = audit_negative_queries(
            preflight_cases,
            audit_corpus_path,
            short_allowlist=set(getattr(lex, "short_allow", set()) or set()),
            source_prefixes=[str(p).strip() for p in (args.audit_source_prefix or []) if str(p).strip()],
            max_token_df=args.audit_max_token_df,
        )
        if negative_violations:
            safe_print("[ERROR] Invalid negative queries detected in preflight audit.")
            for v in negative_violations:
                safe_print(
                    f"NEGATIVE_INVALID token={v.token} "
                    f"matched_tokens={','.join(v.matched_tokens)} "
                    f"evidence={v.chunk_id} path={v.source_path} case_id={v.case_id} "
                    f"excerpt={v.excerpt}"
                )
            return 2, out_path, "", ""

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        bucket_totals: Dict[str, int] = {"A": 0, "B": 0, "C": 0}
        bucket_hits_any: Dict[str, int] = {"A": 0, "B": 0, "C": 0}
        bucket_hits_strong: Dict[str, int] = {"A": 0, "B": 0, "C": 0}
        mismatches = 0
        lex_contract_violations = 0

        lines: list[str] = []
        lines.append("# UpToWes — Custom Queries Bucket Report\n\n")
        lines.append(f"- generated_at: `{now}`\n")
        lines.append(f"- mode: `{'LEX_ONLY' if args.lex_only else 'HYBRID'}`\n")
        lines.append(f"- embed_model: `{args.embed_model if not args.lex_only else 'DISABLED'}`\n")
        lines.append(f"- weights: `w_vec={w_vec:.2f}, w_lex={w_lex:.2f}`\n\n")
        lines.append(f"- require_lexicon: `{str(require_lexicon).lower()}`\n")
        lines.append(f"- lexicon_path: `{lex_path}`\n")
        lines.append(f"- area: `{area_label}`\n\n")
        lines.append(f"- min_cov_ratio: {args.min_cov_ratio:.4f}\n\n")
        lines.append(DISCLAIMER)
        lines.append(LEXMODE_NOTE)
        lines.append("> **precision gate (RELAX)**: tenta `QUERY_REDUCED` (anchor + termos raros). Se ainda RELAX, so aceita hits contendo ao menos 1 termo raro.\n")

        with connect() as conn:
            for case in cases:
                if case.bucket not in bucket_totals:
                    bucket_totals[case.bucket] = 0
                    bucket_hits_any[case.bucket] = 0
                    bucket_hits_strong[case.bucket] = 0

                bucket_totals[case.bucket] += 1

                reduced_q, terms, must_terms = reduce_query(case.query)

                hits = hybrid_search(
                    conn,
                    case.query,
                    top=args.top,
                    w_vec=w_vec,
                    w_lex=w_lex,
                    embed_model=args.embed_model,
                    enable_vector=enable_vector,
                    require_lexicon=require_lexicon,
                    source_prefix=source_prefix,
                )

                used_query = case.query
                used_reduction = False

                if hits and hits[0].lex_mode == "RELAX" and reduced_q != case.query:
                    hits2 = hybrid_search(
                        conn,
                        reduced_q,
                        top=args.top,
                        w_vec=w_vec,
                        w_lex=w_lex,
                        embed_model=args.embed_model,
                        enable_vector=enable_vector,
                        require_lexicon=require_lexicon,
                        source_prefix=source_prefix,
                    )
                    if hits2:
                        hits = hits2
                        used_query = reduced_q
                        used_reduction = True
                qa_query = used_query
                if (not used_reduction) and (reduced_q != case.query):
                    qa_query = reduced_q

                raw_lex_mode = hits[0].lex_mode if hits else "NONE"
                contract_error = validate_lex_mode_contract(raw_lex_mode, require_lexicon=require_lexicon)
                if contract_error:
                    lex_contract_violations += 1

                hits_before = len(hits)
                hits = precision_gate(hits, must_terms=must_terms, original_terms=terms)
                hits_after = len(hits)
                lex_mode = raw_lex_mode if hits else ("NONE" if hits_before == 0 else f"{raw_lex_mode}_FILTERED_TO_ZERO")

                hit_any = bool(hits)
                top_cov = 0
                top_total = 0
                top_cov_ratio = 0.0
                if hit_any:
                    top_cov, top_total = term_coverage(hits[0].text or "", qa_query)
                    top_cov_ratio = (top_cov / top_total) if top_total > 0 else 0.0
                hit_strong = hit_any and is_strong_hit(top_cov, top_total, args.min_cov_ratio)
                got_hit = hit_strong

                if hit_any:
                    bucket_hits_any[case.bucket] += 1
                if hit_strong:
                    bucket_hits_strong[case.bucket] += 1
                expectation_pass = (got_hit == case.expect_hit)
                passed = expectation_pass and not contract_error
                if not expectation_pass:
                    mismatches += 1

                lines.append(f"\n## {case.id} [{case.bucket}] — {case.query}\n")
                lines.append(f"- expect_hit: `{str(case.expect_hit).lower()}`\n")
                lines.append(f"- got_hit_any: `{str(hit_any).lower()}`\n")
                lines.append(f"- got_hit_strong: `{str(hit_strong).lower()}`\n")
                lines.append(f"- top1_cov: `{top_cov}/{top_total}`\n")
                lines.append(f"- top1_cov_ratio: `{top_cov_ratio:.3f}`\n")
                lines.append(f"- status: `{'PASS' if passed else 'FAIL'}`\n")
                if contract_error:
                    lines.append(f"- require_lexicon_gate: `FAIL` ({contract_error})\n")
                elif require_lexicon:
                    lines.append("- require_lexicon_gate: `PASS`\n")
                lines.append(f"- query_effective: `{used_query}`" + (" (`QUERY_REDUCED`)\n" if used_reduction else "\n"))
                if qa_query != used_query:
                    lines.append(f"- qa_query: `{qa_query}` (`QUERY_CORE`)\n")
                lines.append(f"- lex_mode: `{lex_mode}`\n")
                lex_tsquery_groups_str = ""
                lex_tsquery_canon = None
                lex_rest_text = ""
                lex_anchor = None
                lex_groups = None
                lex_rest = None
                if hit_any:
                    lex_tsquery_groups_str = str(getattr(hits[0], "lex_tsquery_groups_str", "") or "")
                    lex_rest_text = str(getattr(hits[0], "lex_rest_text", "") or "")
                if lex_mode == "STRICT_GROUPS":
                    lex_anchor, lex_groups, lex_rest = lex.expand_query(qa_query)
                    if not lex_tsquery_groups_str:
                        lex_tsquery_groups_str = build_tsquery_from_groups(lex_groups)
                    if not lex_rest_text:
                        group_terms = {t for g in lex_groups for t in g if t}
                        rest_list = [t for t in extract_terms(qa_query) if t not in group_terms]
                        lex_rest_text = " ".join(rest_list)
                    if lex_tsquery_groups_str:
                        with conn.cursor() as cur:
                            cur.execute("SELECT to_tsquery('portuguese', %s)::text", (lex_tsquery_groups_str,))
                            lex_tsquery_canon = cur.fetchone()[0]

                    lines.append(f"- lex_anchor: `{lex_anchor}`\n")
                    lines.append(f"- lex_groups: `{lex_groups}`\n")
                    lines.append(f"- lex_rest_terms: `{sorted(list(lex_rest))}`\n")
                    lines.append(f"- lex_rest_text: `{lex_rest_text}`\n")
                    lines.append(f"- lex_tsquery_groups_str: `{lex_tsquery_groups_str}`\n")
                    lines.append(f"- lex_tsquery_canon: `{lex_tsquery_canon}`\n")
                if must_terms:
                    lines.append(f"- must_terms: `{', '.join(must_terms)}`\n")
                if hits_before != hits_after:
                    lines.append(f"- precision_gate: kept={hits_after} dropped={hits_before - hits_after}\n")
                if lex_mode == "RELAX":
                    lines.append("- note: `RELAX_FALLBACK_USED`\n")

                if not hits:
                    lines.append("- **NO_HITS**\n")
                    continue

                for h in hits:
                    full = (h.text or "").replace("\n", " ").strip()
                    cov, total = term_coverage(full, qa_query)
                    snippet = (full[:240] + "...") if len(full) > 240 else full
                    lines.append(
                        f"- score={h.score:.3f} vec={h.score_vec:.3f} lex={h.score_lex:.3f} "
                        f"cov={cov}/{total} [{h.source_table}] `{h.chunk_id}`\n"
                        f"  - doc: `{h.doc_id}` | path: `{h.source_path}` | loc: `{h.locator}` | title: `{h.title}` | type: `{h.chunk_type}`\n"
                        f"  - snippet: {snippet}\n"
                    )

        summary = (
            f"Bucket A: strong {bucket_hits_strong.get('A', 0)}/{bucket_totals.get('A', 0)} | any {bucket_hits_any.get('A', 0)}/{bucket_totals.get('A', 0)} | "
            f"Bucket B: strong {bucket_hits_strong.get('B', 0)}/{bucket_totals.get('B', 0)} | any {bucket_hits_any.get('B', 0)}/{bucket_totals.get('B', 0)} | "
            f"Bucket C: strong {bucket_hits_strong.get('C', 0)}/{bucket_totals.get('C', 0)} | any {bucket_hits_any.get('C', 0)}/{bucket_totals.get('C', 0)}"
        )
        total_failures = mismatches + lex_contract_violations
        total_status = "PASS" if total_failures == 0 else "FAIL"
        total_line = (
            f"{total_status} total: mismatches={mismatches}/{len(cases)} "
            f"| require_lexicon_violations={lex_contract_violations}"
        )

        lines.append("\n## Summary\n")
        lines.append(f"- {summary}\n")
        lines.append(f"- {total_line}\n")

        out_path.write_text("".join(lines), encoding="utf-8")
        print(f"[OK] wrote report: {out_path}")
        print(summary)
        print(total_line)
        return (0 if total_failures == 0 else 1), out_path, summary, total_line

    explicit_cli = (args.lexicon or "").strip()
    explicit_env = (os.environ.get("UPTOWES_LEXICON") or "").strip()
    explicit_input = explicit_cli or explicit_env
    area_input = (args.area or "").strip() or (os.environ.get("UPTOWES_AREA") or "").strip()

    if args.matrix:
        if explicit_input:
            safe_print("[WARN] --matrix ignores explicit lexicon override and runs fixed areas: cirurgia, core.")
        matrix_results: list[tuple[str, int, Path, str, str]] = []
        for area in ("cirurgia", "core"):
            rc, out_path, summary, total_line = run_once(area, None, matrix_mode=True)
            matrix_results.append((area, rc, out_path, summary, total_line))
        safe_print("[MATRIX] completed")
        for area, rc, out_path, summary, total_line in matrix_results:
            safe_print(f"[MATRIX] area={area} rc={rc} report={out_path}")
            safe_print(f"[MATRIX] {summary}")
            safe_print(f"[MATRIX] {total_line}")
        return 0 if all(rc == 0 for _, rc, _, _, _ in matrix_results) else 1

    if explicit_input:
        selected_area = area_input or infer_area_from_lexicon_path(explicit_input)
    else:
        selected_area = area_input or "cirurgia"
    rc, _, _, _ = run_once(selected_area, explicit_input, matrix_mode=False)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
