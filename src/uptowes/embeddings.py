from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

import requests


DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "nomic-embed-text"
EMBED_MAX_CHARS = 3500  # determinístico: corta para evitar prompts gigantes


@dataclass(frozen=True)
class EmbedConfig:
    ollama_url: str
    model: str
    timeout_s: int


def get_embed_config(model: str | None = None) -> EmbedConfig:
    return EmbedConfig(
        ollama_url=os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/"),
        model=model or os.environ.get("UPTOWES_EMBED_MODEL", DEFAULT_MODEL),
        timeout_s=int(os.environ.get("UPTOWES_OLLAMA_TIMEOUT_S", "60")),
    )


def _clip_text(text: str) -> str:
    text = text or ""
    text = text.strip()
    if len(text) <= EMBED_MAX_CHARS:
        return text
    return text[:EMBED_MAX_CHARS].rstrip()


def ollama_embed(text: str, model: str | None = None) -> List[float]:
    cfg = get_embed_config(model=model)
    prompt = _clip_text(text)

    url = f"{cfg.ollama_url}/api/embeddings"
    payload = {"model": cfg.model, "prompt": prompt}

    r = requests.post(url, json=payload, timeout=cfg.timeout_s)
    if r.status_code != 200:
        raise RuntimeError(f"Ollama embeddings failed: HTTP {r.status_code} - {r.text[:300]}")

    data = r.json()
    emb = data.get("embedding")
    if not isinstance(emb, list) or not emb:
        raise RuntimeError(f"Ollama embeddings invalid response: {str(data)[:300]}")
    return [float(x) for x in emb]
