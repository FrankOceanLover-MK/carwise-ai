"""Tests for the provider-agnostic LLM client (HTTP is mocked)."""
import pytest

from app import llm_client
from app.llm_client import LLMError, chat_completion, get_llm_info


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {"choices": [{"message": {"content": "  hi there  "}}]}
        self.text = str(self._body)

    def json(self):
        return self._body


def test_uses_env_config_and_strips_reply(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1/")
    monkeypatch.setenv("LLM_MODEL", "my-model")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return FakeResponse()

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    assert chat_completion([{"role": "user", "content": "yo"}]) == "hi there"
    assert seen["url"] == "https://example.test/v1/chat/completions"
    assert seen["json"]["model"] == "my-model"
    assert seen["headers"]["Authorization"] == "Bearer secret"


def test_missing_key_for_remote_provider_raises(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(LLMError):
        chat_completion([{"role": "user", "content": "yo"}])


def test_local_ollama_needs_no_key(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    chat_completion([{"role": "user", "content": "yo"}])
    assert "Authorization" not in seen["headers"]


def test_http_error_raises(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: FakeResponse(429, {"error": "rate limited"}))
    with pytest.raises(LLMError):
        chat_completion([{"role": "user", "content": "yo"}])


def test_get_llm_info_hides_key(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "secret")
    info = get_llm_info()
    assert "secret" not in str(info)
    assert set(info) == {"model", "base_url"}


def test_reasoning_effort_and_token_floor_are_sent(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(json)
        return FakeResponse()

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    chat_completion([{"role": "user", "content": "yo"}], max_tokens=256)
    assert seen["reasoning_effort"] == "low"
    assert seen["max_tokens"] >= 1024


def test_think_tags_are_stripped(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    body = {"choices": [{"message": {"content": "<think>hmm</think>The answer."}}]}
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: FakeResponse(200, body))
    assert chat_completion([{"role": "user", "content": "yo"}]) == "The answer."


def test_empty_reply_raises(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "k")
    body = {"choices": [{"message": {"content": ""}}]}
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: FakeResponse(200, body))
    with pytest.raises(LLMError):
        chat_completion([{"role": "user", "content": "yo"}])
