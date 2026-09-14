"""LLM provider interface.

Everything above this layer (skills, agent runtimes, services) depends only on these
types, which is what lets ``LLM_PROVIDER`` switch between a local Ollama model and a
cloud model without any code change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class ChatMessage:
    role: Role
    content: str
    #: Set on ``tool`` messages to tell the model which call produced the result.
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(slots=True)
class ToolSpec:
    """JSON-schema description of a callable skill, in provider-neutral form."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    latency_ms: int = 0
    #: Token counts when the provider reports them; omitted rather than estimated.
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@dataclass(slots=True)
class ProviderHealth:
    available: bool
    detail: str | None = None


class LLMProvider(ABC):
    """A chat-completion backend."""

    #: Provider identifier as used by ``LLM_PROVIDER``.
    name: str
    #: Model currently configured for this provider.
    model: str
    #: Whether the backend can execute native tool calls.
    supports_tools: bool = False

    @abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Generate a plain text completion."""

    @abstractmethod
    async def chat_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """Generate a completion that may request tool calls."""

    @abstractmethod
    async def health(self) -> ProviderHealth:
        """Report reachability without raising."""

    async def aclose(self) -> None:
        """Release network resources."""
        return None
