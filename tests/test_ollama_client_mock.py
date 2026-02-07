from __future__ import annotations

import pytest

from uptowes.llm import ollama_client


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):  # noqa: ANN201
        return self._payload


def test_generate_calls_expected_ollama_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}

    def _fake_post(url, json, timeout):  # noqa: ANN001
        called["url"] = url
        called["json"] = dict(json)
        called["timeout"] = timeout
        return _FakeResponse(200, {"response": "{\"ok\":true}"})

    monkeypatch.setenv("UPTOWES_OLLAMA_URL", "http://localhost:11434")
    monkeypatch.setenv("UPTOWES_LLM_MODEL", "qwen2.5:14b")
    monkeypatch.setenv("UPTOWES_OLLAMA_TIMEOUT_S", "12")
    monkeypatch.setattr(ollama_client.requests, "post", _fake_post)

    out = ollama_client.generate("teste")
    assert out == "{\"ok\":true}"
    assert called["url"] == "http://localhost:11434/api/generate"
    assert called["json"]["model"] == "qwen2.5:14b"
    assert called["json"]["stream"] is False
    assert called["json"]["format"] == "json"
    assert called["json"]["options"]["temperature"] == 0
    assert called["timeout"] == 12


def test_generate_raises_auditable_error_on_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_post(url, json, timeout):  # noqa: ANN001
        _ = (url, json, timeout)
        return _FakeResponse(500, {"error": "boom"}, text="internal error")

    monkeypatch.setattr(ollama_client.requests, "post", _fake_post)

    with pytest.raises(RuntimeError, match="HTTP 500"):
        ollama_client.generate("teste")
