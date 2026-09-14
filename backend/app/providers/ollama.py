"""Ollama provider — the local model path, and the one the demo runs on.

Failures are deliberately loud and specific: a stopped daemon reports the URL and the
`ollama serve` fix, and a missing model reports the `ollama pull` fix. Hiding these
behind a generic 500 would make the local setup impossible to debug.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from app.core.errors import (
    EmbeddingError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.core.logging import get_logger
from app.providers.base import ChatMessage, LLMProvider, LLMResponse, ProviderHealth, ToolCall, ToolSpec

logger = get_logger(__name__)


class OllamaProvider(LLMProvider):
    name = "ollama"
    supports_tools = True

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout: float = 180.0,
        embedding_model: str = "nomic-embed-text",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.embedding_model = embedding_model
        self._timeout = timeout
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    # ------------------------------------------------------------------ helpers
    def _unavailable(self, exc: Exception) -> ProviderUnavailableError:
        return ProviderUnavailableError(
            f"Could not reach Ollama at {self.base_url}.",
            remedy="Start it with `ollama serve`, then confirm OLLAMA_BASE_URL is correct. "
            "From Docker the URL must be http://host.docker.internal:11434.",
            details={"base_url": self.base_url, "error": type(exc).__name__},
        )

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Ollama did not respond within {self._timeout:.0f}s.",
                details={"model": payload.get("model", self.model)},
            ) from exc
        except httpx.HTTPError as exc:
            raise self._unavailable(exc) from exc

        if response.status_code == 404:
            model = payload.get("model", self.model)
            raise ProviderResponseError(
                f"Ollama does not have the model '{model}'.",
                remedy=f"Pull it first: `ollama pull {model}`",
                details={"model": model},
            )
        if response.status_code >= 400:
            snippet = self._error_snippet(response)
            message = f"Ollama returned HTTP {response.status_code}."
            if snippet:
                message = f"{message} {snippet}"
            raise ProviderResponseError(
                message,
                remedy=self._error_remedy(snippet),
                details={"status_code": response.status_code},
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderResponseError("Ollama returned a malformed JSON response.") from exc

    @staticmethod
    def _to_wire(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        wire: list[dict[str, Any]] = []
        for message in messages:
            entry: dict[str, Any] = {"role": message.role, "content": message.content}
            # Ollama identifies tool results by tool name, not by call id.
            if message.role == "tool" and message.name:
                entry["tool_name"] = message.name
            wire.append(entry)
        return wire

    # -------------------------------------------------------------------- chat
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        return await self._chat(messages, tools=None, max_tokens=max_tokens, temperature=temperature)

    async def chat_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        return await self._chat(messages, tools=tools, max_tokens=max_tokens, temperature=temperature)

    async def _chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[ToolSpec] | None,
        max_tokens: int | None,
        temperature: float | None,
    ) -> LLMResponse:
        options: dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_wire(messages),
            "stream": False,
        }
        if options:
            payload["options"] = options
        if tools:
            payload["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]

        started = time.perf_counter()
        data = await self._post("/api/chat", payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        message = data.get("message") or {}
        tool_calls = [
            ToolCall(
                id=str(uuid.uuid4()),
                name=(call.get("function") or {}).get("name", ""),
                arguments=(call.get("function") or {}).get("arguments") or {},
            )
            for call in (message.get("tool_calls") or [])
            if (call.get("function") or {}).get("name")
        ]

        usage = {
            key: data[key]
            for key in ("prompt_eval_count", "eval_count")
            if isinstance(data.get(key), int)
        }
        logger.info(
            "llm_completed",
            provider=self.name,
            model=self.model,
            latency_ms=latency_ms,
            tool_calls=len(tool_calls),
        )
        return LLMResponse(
            text=(message.get("content") or "").strip(),
            tool_calls=tool_calls,
            model=self.model,
            latency_ms=latency_ms,
            usage=usage,
        )

    # -------------------------------------------------------------- embeddings
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts with ``embedding_model``."""
        if not texts:
            return []
        try:
            # Unload immediately so llama3.1:8b can claim the GPU. Leaving nomic resident
            # on a 6 GB card is what produced "llama runner process has terminated".
            data = await self._post(
                "/api/embed",
                {"model": self.embedding_model, "input": texts, "keep_alive": 0},
            )
        except (ProviderUnavailableError, ProviderTimeoutError, ProviderResponseError) as exc:
            raise EmbeddingError(
                f"Embedding failed: {exc.message}",
                remedy=getattr(exc, "remedy", None) or f"Ensure `ollama pull {self.embedding_model}` has been run.",
            ) from exc

        vectors = data.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingError(
                "Ollama returned an unexpected number of embeddings.",
                details={"expected": len(texts), "received": len(vectors) if isinstance(vectors, list) else 0},
            )
        return [[float(value) for value in vector] for vector in vectors]

    # ------------------------------------------------------------------ health
    async def health(self) -> ProviderHealth:
        try:
            response = await self._client.get("/api/tags", timeout=5.0)
            response.raise_for_status()
            names = {model.get("name", "") for model in response.json().get("models", [])}
        except Exception as exc:  # noqa: BLE001 - health must never raise
            return ProviderHealth(False, f"Not reachable at {self.base_url} ({type(exc).__name__})")

        # Ollama reports "llama3.1:8b" / "nomic-embed-text:latest"; tolerate a configured
        # name without its tag.
        missing = [
            wanted
            for wanted in (self.model, self.embedding_model)
            if wanted and not any(name == wanted or name.split(":")[0] == wanted.split(":")[0] for name in names)
        ]
        if missing:
            wanted = missing[0]
            return ProviderHealth(False, f"Reachable, but model '{wanted}' is not pulled (`ollama pull {wanted}`)")
        return ProviderHealth(True, f"Reachable at {self.base_url}")

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _error_snippet(response: httpx.Response) -> str:
        """Best-effort Ollama error text. Truncated so it stays safe to show in the UI."""
        try:
            data = response.json()
        except ValueError:
            return (response.text or "").strip()[:300]
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, str) and error.strip():
                return error.strip()[:300]
        return ""

    @staticmethod
    def _error_remedy(snippet: str) -> str | None:
        lowered = snippet.lower()
        if "runner" in lowered or "cuda" in lowered:
            return (
                "Restart the host Ollama app and retry. llama3.1:8b needs several GB of "
                "free GPU memory; another loaded model or a stuck CUDA runner will fail the load."
            )
        return None
