# scripts/pii_scan.py
from __future__ import annotations

import argparse
import re
from pathlib import Path

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
CPF_DOTTED_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
CPF_11_RE = re.compile(r"\b\d{11}\b")
PHONE_RE = re.compile(r"\b(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?\d{4,5}-\d{4}\b")

def mask(s: str) -> str:
    # mascara agressiva: não imprime números/emails crus no terminal
    s = EMAIL_RE.sub("[REDACTED_EMAIL]", s)
    s = CPF_DOTTED_RE.sub("[REDACTED_CPF]", s)
    s = CPF_11_RE.sub("[REDACTED_CPF]", s)
    s = PHONE_RE.sub("[REDACTED_PHONE]", s)
    # mascara qualquer sequência longa de dígitos
    s = re.sub(r"\d{6,}", "[REDACTED_NUM]", s)
    return s

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="Arquivo ou diretório para varrer")
    args = ap.parse_args()

    root = Path(args.path).expanduser().resolve()
    files = [root] if root.is_file() else sorted([p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".json", ".jsonl", ".txt"}])

    hits = 0
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue

        for i, line in enumerate(lines, start=1):
            if EMAIL_RE.search(line) or CPF_DOTTED_RE.search(line) or CPF_11_RE.search(line) or PHONE_RE.search(line):
                hits += 1
                print(f"[PII] {f} : L{i} : {mask(line)[:200]}")

    if hits:
        print(f"[PII] FAIL: {hits} ocorrência(s). Não faça commit/push.")
        return 3

    print("[PII] OK: nenhum padrão encontrado.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
