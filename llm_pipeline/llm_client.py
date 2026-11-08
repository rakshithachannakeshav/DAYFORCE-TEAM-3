"""LLM client abstraction + Ollama implementation.

The pipeline depends only on the ``LLMClient`` protocol, so:
* tests inject a fake client (no Ollama needed), and
* the model/provider can be swapped without touching pipeline logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .config import LLMSettings
from .errors import EmptyResponseError, LLMError, LLMTimeoutError, LLMUnavailableError

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    content: str
    truncated: bool = False  # True if generation stopped because it hit the token limit
    raw: dict[str, Any] | None = None


class LLMClient(Protocol):
    model: str

    async def chat(self, messages: list[ChatMessage], *, json_schema: dict[str, Any] | None = None) -> LLMResponse: ...

    async def health(self) -> dict[str, Any]: ...


def inline_json_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace local ``$ref``s with their definitions.

    Pydantic emits ``$defs`` + ``$ref``; inlining them makes the schema safe
    for every Ollama version's JSON-schema-to-grammar converter.
    """
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return resolve(defs[name])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(x) for x in node]
        return node

    return resolve(schema)


class OllamaClient:
    """Thin async wrapper around Ollama's ``/api/chat`` endpoint."""

    def __init__(self, settings: LLMSettings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.model = settings.model
        self._transport = transport  # lets tests inject httpx.MockTransport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.settings.ollama_host, timeout=timeout, transport=self._transport)

    async def chat(self, messages: list[ChatMessage], *, json_schema: dict[str, Any] | None = None) -> LLMResponse:
        s = self.settings
        payload: dict[str, Any] = {
            "model": s.model,
            "messages": [m.to_dict() for m in messages],
            "stream": False,
            # Constrained decoding: either a full JSON schema or generic JSON mode.
            "format": json_schema if (json_schema and s.use_json_schema_format) else "json",
            "keep_alive": s.keep_alive,
            "options": {
                "temperature": s.temperature,
                "num_ctx": s.num_ctx,
                "num_predict": s.num_predict,
            },
        }
        try:
            async with self._client(s.request_timeout_s) as client:
                resp = await client.post("/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Ollama did not respond within {s.request_timeout_s:.0f}s") from exc
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(
                f"Cannot connect to Ollama at {s.ollama_host}. Is it running? Try: `ollama serve`"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"HTTP error talking to Ollama: {exc}") from exc

        if resp.status_code == 404:
            raise LLMUnavailableError(f"Model '{s.model}' is not available in Ollama. Run: `ollama pull {s.model}`")
        if resp.status_code >= 400:
            raise LLMError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:300]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise LLMError("Ollama returned a non-JSON HTTP body") from exc

        content = (data.get("message") or {}).get("content") or ""
        if not content.strip():
            raise EmptyResponseError("The model returned an empty response")

        truncated = data.get("done_reason") == "length"
        logger.debug(
            "ollama chat done: model=%s eval_count=%s truncated=%s", s.model, data.get("eval_count"), truncated
        )
        return LLMResponse(content=content, truncated=truncated, raw=data)

    async def health(self) -> dict[str, Any]:
        """Report whether Ollama is reachable and the configured model is pulled."""
        try:
            async with self._client(5.0) as client:
                resp = await client.get("/api/tags")
                resp.raise_for_status()
                models = [m.get("name", "") for m in resp.json().get("models", [])]
        except httpx.HTTPError as exc:
            return {"ollama_reachable": False, "model": self.model, "model_available": False, "error": str(exc)}

        wanted = self.model if ":" in self.model else f"{self.model}:latest"
        return {
            "ollama_reachable": True,
            "model": self.model,
            "model_available": wanted in models,
            "installed_models": models,
        }
