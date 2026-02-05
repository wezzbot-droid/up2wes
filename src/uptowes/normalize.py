# src/uptowes/normalize.py
from __future__ import annotations

import html


def normalize_text(raw: str) -> str:
    """
    Normalização determinística (SEM LLM).
    Objetivo: reduzir ruído sem perder conteúdo.
    """
    if raw is None:
        return ""

    t = raw.replace("\r\n", "\n").replace("\r", "\n")
    t = html.unescape(t)

    # higiene de símbolos / OCR comum
    t = t.replace("\u00ad", "")  # soft hyphen invisível
    t = t.replace("•", "- ")
    t = t.replace("→", "->").replace("⇒", "=>")

    # remove trailing spaces (preserva linhas)
    t = "\n".join([ln.rstrip() for ln in t.split("\n")])
    return t


def extract_bold_spans(md: str):
    """
    Converte **bold** em texto puro e retorna spans com offsets no texto resultante.
    """
    spans = []
    out = []
    i = 0
    plain_idx = 0

    while i < len(md):
        if md.startswith("**", i):
            j = md.find("**", i + 2)
            if j == -1:
                out.append(md[i])
                i += 1
                plain_idx += 1
                continue

            bold_text = md[i + 2 : j]
            start = plain_idx
            out.append(bold_text)
            plain_idx += len(bold_text)
            end = plain_idx
            spans.append({"start": start, "end": end, "text": bold_text})
            i = j + 2
        else:
            out.append(md[i])
            i += 1
            plain_idx += 1

    return "".join(out), spans
