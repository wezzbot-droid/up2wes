from __future__ import annotations

import json
import re
from typing import Any, Dict, List

_WS_RE = re.compile(r"\s+")


def _canon_for_substring(s: str) -> str:
    """
    Canon leve e deterministico para evitar falsos negativos por formatacao.
    Remove apenas:
    - markdown bold (**)
    - pipes de tabela (|)
    - normaliza whitespace (\n, \t, multiplos espacos)
    """
    s = str(s or "")
    s = s.replace("**", "")
    s = s.replace("|", " ")
    s = _WS_RE.sub(" ", s).strip()
    return s


def quote_is_from_source(quote: str, source_text: str, *, min_canon_len: int = 12) -> bool:
    if not quote or not source_text:
        return False

    q = _canon_for_substring(quote)
    if len(q) < min_canon_len:
        return False

    # 1) literal (mais forte)
    if quote in source_text:
        return True

    # 2) canonical (resiste a pipes/bold/whitespace)
    s = _canon_for_substring(source_text)

    return q in s


class AnswererValidationError(Exception):
    pass


REQUIRED_KEYS = {"answer_markdown", "citations", "supporting_quotes", "limits", "confidence"}
CONF_VALUES = {"low", "medium", "high"}


def validate_answerer_output(raw_output: str, evidence_input: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        out = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise AnswererValidationError(f"JSON invalido: {exc}") from exc

    if not isinstance(out, dict):
        raise AnswererValidationError("Output nao e objeto JSON")

    missing = REQUIRED_KEYS - set(out.keys())
    if missing:
        raise AnswererValidationError(f"Campos faltando: {sorted(missing)}")

    if out["confidence"] not in CONF_VALUES:
        raise AnswererValidationError(f"confidence invalido: {out['confidence']}")

    answer = str(out["answer_markdown"] or "")
    is_insufficient = answer.startswith("EVIDÊNCIA INSUFICIENTE:")

    if not is_insufficient:
        if not out["citations"]:
            raise AnswererValidationError("citations vazio quando answer nao e insuficiente")
        if not out["supporting_quotes"]:
            raise AnswererValidationError("supporting_quotes vazio quando answer nao e insuficiente")
    else:
        if out["confidence"] != "low":
            raise AnswererValidationError("confidence deve ser low quando answer e insuficiente")
        if not out["limits"]:
            raise AnswererValidationError("limits vazio")

    if not out["limits"]:
        raise AnswererValidationError("limits vazio")

    # Mapa de evidencia
    ev_map = {str(e.get("chunk_id") or ""): e for e in evidence_input}
    quote_src = {
        cid: str(
            ev_map[cid].get("quote_source_text")
            or ev_map[cid].get("evidence_text_for_quote")
            or ev_map[cid].get("text")
            or ""
        )
        for cid in ev_map
    }

    # citation chunk_id existe
    for c in out["citations"]:
        if not isinstance(c, dict):
            raise AnswererValidationError("citation deve ser objeto")
        cid = str(c.get("chunk_id") or "")
        if cid not in ev_map:
            raise AnswererValidationError(f"chunk_id citado nao existe no input: {cid}")

    # supporting_quote: chunk existe + quote <= 300 + substring (literal OU canonical)
    for sq in out["supporting_quotes"]:
        if not isinstance(sq, dict):
            raise AnswererValidationError("supporting_quote deve ser objeto")
        cid = str(sq.get("chunk_id") or "")
        q = str(sq.get("quote") or "")
        if cid not in quote_src:
            raise AnswererValidationError(f"supporting_quote chunk_id nao existe: {cid}")
        if len(q) > 300:
            raise AnswererValidationError(f"Quote excede 300 chars: {len(q)} (chunk={cid})")

        src = quote_src[cid]
        if not quote_is_from_source(q, src):
            raise AnswererValidationError(
                f"Quote nao e substring (literal/canon) da evidencia (chunk={cid}). "
                f"quote[:80]={q[:80]!r}"
            )

    # cada citation precisa ter >=1 supporting_quote
    cited_ids = {str(c["chunk_id"]) for c in out["citations"]} if out["citations"] else set()
    quoted_ids = (
        {str(sq["chunk_id"]) for sq in out["supporting_quotes"]} if out["supporting_quotes"] else set()
    )
    missing_q = cited_ids - quoted_ids
    if missing_q:
        raise AnswererValidationError(f"Citations sem supporting_quotes: {sorted(missing_q)}")

    return out
