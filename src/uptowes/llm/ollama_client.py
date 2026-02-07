from __future__ import annotations

import os
from dataclasses import dataclass

import requests


DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_LLM_MODEL = "qwen2.5:14b"


@dataclass(frozen=True)
class OllamaLLMConfig:
    base_url: str
    model: str
    timeout_s: int


def get_ollama_llm_config() -> OllamaLLMConfig:
    return OllamaLLMConfig(
        base_url=(os.environ.get("UPTOWES_OLLAMA_URL") or DEFAULT_OLLAMA_URL).rstrip("/"),
        model=(os.environ.get("UPTOWES_LLM_MODEL") or DEFAULT_LLM_MODEL).strip(),
        timeout_s=int(os.environ.get("UPTOWES_OLLAMA_TIMEOUT_S", "90")),
    )


def generate(prompt: str) -> str:
    cfg = get_ollama_llm_config()
    if not (prompt or "").strip():
        raise RuntimeError("Ollama generate failed: prompt is empty.")
    if not cfg.model:
        raise RuntimeError("Ollama generate failed: UPTOWES_LLM_MODEL is empty.")

    url = f"{cfg.base_url}/api/generate"
    payload = {
        "model": cfg.model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }

    try:
        resp = requests.post(url, json=payload, timeout=cfg.timeout_s)
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Ollama generate request error url={url} model={cfg.model} timeout_s={cfg.timeout_s}: {exc}"
        ) from exc

    if resp.status_code != 200:
        raise RuntimeError(
            f"Ollama generate failed url={url} model={cfg.model} HTTP {resp.status_code}: {resp.text[:400]}"
        )

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"Ollama generate invalid JSON response: {resp.text[:400]}") from exc

    output = data.get("response")
    if not isinstance(output, str):
        raise RuntimeError(f"Ollama generate missing 'response' field: {str(data)[:400]}")
    return output
