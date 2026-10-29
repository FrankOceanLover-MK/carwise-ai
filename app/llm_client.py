"""Provider-agnostic chat client for any OpenAI-compatible endpoint.

Works with free, open-source models served by Groq, Ollama, OpenRouter, Together,
Cerebras, vLLM, LM Studio, and others. Configure it entirely through environment
variables (see .env.example):

    LLM_BASE_URL   Base URL of the OpenAI-compatible API (default: Groq)
    LLM_MODEL      Model name to request
    LLM_API_KEY    API key (not needed for a local Ollama server)

Optional, for "reasoning" models such as gpt-oss and Qwen3:

    LLM_REASONING_EFFORT  low | medium | high (sent to the provider when set)
    LLM_MIN_TOKENS        Floor for max_tokens, because reasoning tokens count
                          against the limit and can leave the visible answer empty
"""
import logging
import os
import re
from typing import Any, Dict, List

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"


def _config() -> Dict[str, Any]:
    """Read settings at call time so they can be changed without re-importing."""
    base_url = os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    return {
        "base_url": base_url,
        "model": os.getenv("LLM_MODEL", DEFAULT_MODEL),
        "api_key": os.getenv("LLM_API_KEY", ""),
        "timeout": float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        "reasoning_effort": os.getenv("LLM_REASONING_EFFORT", "").strip().lower(),
        "min_tokens": int(os.getenv("LLM_MIN_TOKENS", "1024")),
    }


def _is_local(base_url: str) -> bool:
    return "localhost" in base_url or "127.0.0.1" in base_url


def get_llm_info() -> Dict[str, str]:
    """Non-secret details about the active model, for /health and the UI."""
    cfg = _config()
    return {"model": cfg["model"], "base_url": cfg["base_url"]}


class LLMError(RuntimeError):
    pass


def chat_completion(
    messages: List[Dict[str, str]],
    max_tokens: int = 256,
    temperature: float = 0.3,
) -> str:
    """Send a chat request to the configured LLM and return the reply text.

    Args:
        messages: List of {"role", "content"} dicts.
        max_tokens: Maximum tokens to generate.
        temperature: Sampling temperature.
    """
    cfg = _config()
    url = f"{cfg['base_url']}/chat/completions"
    logger.debug("Calling LLM at %s (model=%s, messages=%d)", url, cfg["model"], len(messages))

    if not cfg["api_key"] and not _is_local(cfg["base_url"]):
        raise LLMError(
            "LLM_API_KEY is not set. Add it to your .env file "
            "(or point LLM_BASE_URL at a local Ollama server, which needs no key)."
        )

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    payload: Dict[str, Any] = {
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": max(max_tokens, cfg["min_tokens"]),
        "temperature": temperature,
    }
    if cfg["reasoning_effort"]:
        payload["reasoning_effort"] = cfg["reasoning_effort"]

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=cfg["timeout"])
    except requests.exceptions.Timeout as e:
        logger.error("LLM request timed out: %s", e)
        raise LLMError(f"LLM request timed out after {cfg['timeout']} seconds.") from e
    except requests.RequestException as e:
        logger.error("LLM request failed: %s", e)
        raise LLMError(f"Error contacting LLM server at {url}: {e}") from e

    if not (200 <= resp.status_code < 300):
        try:
            err = resp.json()
        except ValueError:
            err = resp.text
        logger.error("LLM returned %s: %s", resp.status_code, err)
        raise LLMError(f"LLM server returned {resp.status_code}: {err}")

    try:
        data = resp.json()
    except ValueError as e:
        raise LLMError(f"Could not parse LLM response as JSON: {resp.text[:200]}") from e

    # OpenAI-compatible format: {"choices": [{"message": {"role": "assistant", "content": "..."}}]}
    choices = data.get("choices")
    if not choices:
        raise LLMError(f"LLM response missing 'choices': {data}")

    message = choices[0].get("message")
    if not message:
        raise LLMError(f"LLM response missing 'message' in choices[0]: {data}")

    content = message.get("content")
    if not isinstance(content, str):
        raise LLMError(f"LLM response missing 'message.content': {data}")

    # Some reasoning models inline their chain of thought in <think> tags; hide it.
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    if not content:
        raise LLMError(
            "The LLM returned an empty reply. If you are using a reasoning model, "
            "set LLM_REASONING_EFFORT=low and/or raise LLM_MIN_TOKENS."
        )

    logger.debug("LLM replied with %d characters", len(content))
    return content
