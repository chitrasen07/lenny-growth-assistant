"""Agent service — assembles a runtime, its skills and the request context."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.registry import SkillRegistry
from app.agent.routing import Route
from app.agent.runtimes.claude_sdk import ClaudeAgentSDKRuntime
from app.agent.runtimes.router import RouterRuntime
from app.agent.types import SkillContext, SkillResult
from app.core.config import LLMProviderName, Settings, get_settings
from app.core.logging import get_logger
from app.providers.base import LLMProvider
from app.providers.factory import get_provider
from app.rag.retrieval import RetrievalService

logger = get_logger(__name__)


def runtime_name_for_provider(name: str | LLMProviderName | None) -> str:
    """Return the runtime ``AgentService`` actually constructs for a provider.

    Dispatch is by provider, not ``AGENT_RUNTIME``: Anthropic uses the Claude Agent SDK;
    Ollama uses the deterministic router because the SDK cannot drive a local model.
    """
    resolved = name.value if isinstance(name, LLMProviderName) else str(name or "")
    if resolved == LLMProviderName.ANTHROPIC.value:
        return ClaudeAgentSDKRuntime.name
    return RouterRuntime.name


class AgentRuntime(Protocol):
    name: str

    def plan(self, message: str) -> Route: ...

    async def run(
        self, message: str, context: SkillContext, *, plan: Route | None = None
    ) -> tuple[SkillResult, Route]: ...


class AgentService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._registry = SkillRegistry(self._settings)

    @property
    def registry(self) -> SkillRegistry:
        return self._registry

    def runtime(self, provider: LLMProvider | None = None) -> AgentRuntime:
        """Pick the agent runtime from the *resolved* LLM provider.

        Anthropic uses the Claude Agent SDK so the agent layer is actually built on it.
        Ollama stays on the deterministic router — the SDK cannot drive a local model.
        """
        name = provider.name if provider is not None else self._settings.llm_provider.value
        if runtime_name_for_provider(name) == ClaudeAgentSDKRuntime.name:
            return ClaudeAgentSDKRuntime(self._registry, self._settings)
        return RouterRuntime(self._registry)

    async def handle(
        self,
        message: str,
        *,
        history: list[tuple[str, str]],
        provider: LLMProvider | None = None,
        provider_name: LLMProviderName | None = None,
    ) -> tuple[SkillResult, Route, LLMProvider]:
        resolved = provider or get_provider(provider_name, self._settings)
        context = SkillContext(
            provider=resolved,
            retrieval=RetrievalService(self._session, self._settings),
            history=history,
        )
        runtime = self.runtime(resolved)
        logger.info("agent_started", runtime=runtime.name, provider=resolved.name, model=resolved.model, history_turns=len(history))
        result, route = await runtime.run(message, context)
        return result, route, resolved
