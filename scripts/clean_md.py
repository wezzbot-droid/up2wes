# scripts/clean_md.py
from __future__ import annotations

import argparse
import fnmatch
import html
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
CPF_DOTTED_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
# CPF “seco” (11 dígitos). É agressivo de propósito: melhor falso-positivo do que vazamento.
CPF_11_RE = re.compile(r"\b\d{11}\b")
# Telefones BR comuns
PHONE_RE = re.compile(r"\b(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?\d{4,5}-\d{4}\b")

# Remove tags HTML comuns sem destruir "<" usado como comparação clínica
HTML_TAG_RE = re.compile(r"</?(br|p|i|b|strong|em|span|div|sup|sub)\b[^>]*>", re.IGNORECASE)

# Headers/footers conservadores
PAGE_HEADER_RE = re.compile(r"^\s*\d+\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{6,}\s*$")  # ex: "2 CIRURGIA GERAL"
PAGE_NUMBER_ONLY_RE = re.compile(r"^\s*\d{1,3}\s*$")  # página "2"


def should_drop_line(line: str) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if EMAIL_RE.search(line):
        reasons.append("email")
    if CPF_DOTTED_RE.search(line) or CPF_11_RE.search(line):
        reasons.append("cpf_like")
    if PHONE_RE.search(line):
        reasons.append("phone")
    if PAGE_HEADER_RE.match(line) or PAGE_NUMBER_ONLY_RE.match(line):
        reasons.append("page_header_footer")
    return (len(reasons) > 0, reasons)


def clean_text(text: str) -> Tuple[str, Dict[str, int]]:
    stats = {"lines_dropped": 0, "email": 0, "cpf_like": 0, "phone": 0, "page_header_footer": 0}

    # Normalizações seguras
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u200b", "")  # zero-width space
    text = html.unescape(text)

    # Conserta tags HTML comuns
    text = HTML_TAG_RE.sub("\n", text)

    out_lines: List[str] = []
    for line in text.split("\n"):
        drop, reasons = should_drop_line(line)
        if drop:
            stats["lines_dropped"] += 1
            for r in reasons:
                stats[r] += 1
            continue
        out_lines.append(line.rstrip())

    cleaned = "\n".join(out_lines)

    # Colapsa excesso de linhas vazias
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip() + "\n"
    return cleaned, stats


def iter_files(root: Path, pattern: str) -> List[Path]:
    files: List[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and fnmatch.fnmatch(p.name, pattern):
            files.append(p)
    return sorted(files)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir", required=True, help="Diretório com .md")
    ap.add_argument("--out", dest="out_dir", required=True, help="Diretório de saída (clean)")
    ap.add_argument("--pattern", default="*_raw.md", help="Padrão de arquivos (default: *_raw.md)")
    ap.add_argument("--overwrite", action="store_true", help="Sobrescrever arquivos de saída existentes")
    ap.add_argument("--report", default="clean_report.json", help="Nome do relatório JSON (no out_dir)")
    args = ap.parse_args()

    in_dir = Path(args.in_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    files = iter_files(in_dir, args.pattern)
    if not files:
        print(f"[clean_md] Nenhum arquivo encontrado em {in_dir} com pattern '{args.pattern}'")
        return 2

    report: Dict[str, Dict[str, int]] = {}
    for src in files:
        rel = src.relative_to(in_dir)
        # Troca sufixo *_raw.md -> *_clean.md
        out_name = src.name.replace("_raw.md", "_clean.md") if src.name.endswith("_raw.md") else src.name
        dst = (out_dir / rel.parent / out_name).resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists() and not args.overwrite:
            print(f"[clean_md] SKIP (existe): {dst}")
            continue

        text = src.read_text(encoding="utf-8", errors="replace")
        cleaned, stats = clean_text(text)
        dst.write_text(cleaned, encoding="utf-8")

        report[str(rel)] = stats
        print(f"[clean_md] OK: {rel} -> {dst.relative_to(out_dir)} | dropped={stats['lines_dropped']}")

    (out_dir / args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[clean_md] Relatório: {out_dir / args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
