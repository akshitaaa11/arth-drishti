"""Groq chat client with tool calling and primary -> backup model failover (README Phase 11).

The key and model names come from the environment (``GROQ_API_KEY``, ``GROQ_MODEL``, ``GROQ_BACKUP_MODEL``); the key is never logged or returned.
A ``transport`` callable can be injected, which is how the tests exercise the whole path without the network.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import requests

URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_BACKUP = "openai/gpt-oss-20b"

Transport = Callable[[dict[str, Any], str], tuple[int, dict[str, Any]]]


class LLMUnavailable(Exception):
    """Neither the primary nor the backup model produced a usable reply."""


def _http_transport(payload: dict[str, Any], key: str) -> tuple[int, dict[str, Any]]:
    resp = requests.post(URL, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=60)
    try:
        body = resp.json()
    except ValueError:
        body = {"error": {"message": resp.text[:200]}}
    return resp.status_code, body  # type: ignore[no-any-return]


class GroqClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, backup_model: str | None = None, transport: Transport | None = None,
                 retries: int = 2, sleep: Callable[[float], None] = time.sleep) -> None:
        self._key = api_key if api_key is not None else os.environ.get("GROQ_API_KEY", "")
        self.model = model or os.environ.get("GROQ_MODEL") or DEFAULT_MODEL
        self.backup_model = backup_model or os.environ.get("GROQ_BACKUP_MODEL") or DEFAULT_BACKUP
        self.transport = transport or _http_transport
        self.retries = retries
        self.sleep = sleep
        self.disabled: set[str] = set()  # models switched off (tests / outage drills)
        self.calls: list[dict[str, Any]] = []  # model, status only: no key, no content

    @property
    def available(self) -> bool:
        return bool(self._key)

    def _try(self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, max_tokens: int) -> dict[str, Any] | None:
        payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]
            payload["tool_choice"] = "auto"
        for attempt in range(self.retries + 1):
            try:
                status, body = self.transport(payload, self._key)
            except requests.RequestException:
                status, body = 599, {}
            self.calls.append({"model": model, "status": status})
            if status == 200 and body.get("choices"):
                return body["choices"][0]["message"]  # type: ignore[no-any-return]
            if status == 429 and attempt < self.retries:
                self.sleep(min(2.0 * (attempt + 1), 8.0))
                continue
            return None  # 4xx model errors, tool_use_failed, 5xx, exhausted rate limit: fail over
        return None

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, max_tokens: int = 1500) -> tuple[dict[str, Any], str]:
        """Return (assistant message, model used). Raises LLMUnavailable when both models fail."""
        if not self.available:
            raise LLMUnavailable("no GROQ_API_KEY configured")
        for model in (self.model, self.backup_model):
            if model in self.disabled:
                continue
            msg = self._try(model, messages, tools, max_tokens)
            if msg is not None:
                return msg, model
        raise LLMUnavailable("primary and backup models both failed")
