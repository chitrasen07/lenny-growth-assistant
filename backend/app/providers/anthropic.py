"""Anthropic Claude provider — the cloud path.

Uses the official SDK's native tool-use blocks so the agent's tool loop behaves the same
way it does on Ollama. The API key is read from configuration only and is never logged
or echoed in an error message.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.errors import (
    ProviderConfigurationError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.core.logging import get_logger
from app.providers.base import ChatMessage, LLMProvider, LLMResponse, ProviderHealth, ToolCall, ToolSpec

logger = get_logger(__name__)


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    supports_tools = True

    def __init__(self, api_key: str | None, model: str, *, timeout: float = 180.0, client: Any | None = None) -> None:
        self.model = model
        self._api_key = api_key
        self._timeout = timeout
        self._client = client

    def _require_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ProviderConfigurationError(
                "The Anthropic provider is selected but no API key is configured.",
                remedy="Set ANTHROPIC_API_KEY in .env, or switch back to Ollama (local) in the header.",
            )
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - dependency is pinned
            raise ProviderConfigurationError(
                "The 'anthropic' package is not installed.",
                remedy="Install backend requirements: pip install -r backend/requirements.txt",
            ) from exc

        self._client = AsyncAnthropic(api_key=self._api_key, timeout=self._timeout)
        return self._client

    @staticmethod
    def _split_messages(messages: list[ChatMessage]) -> tuple[str | None, list[dict[str, Any]]]:
        """Anthropic takes the system prompt as a separate argument, not as a message."""
        system_parts: list[str] = []
        turns: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                system_parts.append(message.content)
            elif message.role == "tool":
                turns.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id or "",
                                "content": message.content,
                            }
                        ],
                    }
                )
            else:
                turns.append({"role": message.role, "content": message.content})
        return ("\n\n".join(system_parts) or None), turns

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        return await self._create(messages, tools=None, max_tokens=max_tokens, temperature=temperature)

    async def chat_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        return await self._create(messages, tools=tools, max_tokens=max_tokens, temperature=temperature)

    async def _create(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[ToolSpec] | None,
        max_tokens: int | None,
        temperature: float | None,
    ) -> LLMResponse:
        client = self._require_client()
        system, turns = self._split_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or 4096,
            "messages": turns,
        }
        if system:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
            ]

        started = time.perf_counter()
        try:
            response = await client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - normalised into typed errors below
            raise self._translate(exc) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in getattr(response, "content", []) or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(getattr(block, "text", ""))
            elif block_type == "tool_use":
                arguments = getattr(block, "input", None)
                tool_calls.append(
                    ToolCall(
                        id=getattr(block, "id", ""),
                        name=getattr(block, "name", ""),
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )

        usage_obj = getattr(response, "usage", None)
        usage = {
            "input_tokens": getattr(usage_obj, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage_obj, "output_tokens", 0) or 0,
        } if usage_obj else {}

        logger.info(
            "llm_completed",
            provider=self.name,
            model=self.model,
            latency_ms=latency_ms,
            tool_calls=len(tool_calls),
        )
        return LLMResponse(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            model=self.model,
            latency_ms=latency_ms,
            usage=usage,
        )

    def _translate(self, exc: Exception) -> Exception:
        """Map SDK exceptions onto typed app errors without leaking request details."""
        if isinstance(exc, ProviderConfigurationError):
            return exc
        name = type(exc).__name__
        if "Timeout" in name:
            return ProviderTimeoutError(f"Anthropic did not respond within {self._timeout:.0f}s.")
        if "Authentication" in name or "PermissionDenied" in name:
            return ProviderConfigurationError(
                "Anthropic rejected the API key.",
                remedy="Check ANTHROPIC_API_KEY in .env.",
            )
        if "RateLimit" in name:
            return ProviderResponseError("Anthropic rate limit reached.", remedy="Wait a moment and retry.")
        if "APIConnection" in name or "Connection" in name:
            return ProviderUnavailableError("Could not reach the Anthropic API.", remedy="Check network connectivity.")
        return ProviderResponseError(f"Anthropic request failed ({name}).")

    async def health(self) -> ProviderHealth:
        if not self._api_key and self._client is None:
            return ProviderHealth(False, "ANTHROPIC_API_KEY missing (optional unless LLM_PROVIDER=anthropic)")
        # A live probe would bill a token on every health poll, so this reports
        # configuration readiness only. Real errors surface on the first chat request.
        return ProviderHealth(True, f"API key configured for {self.model}")
