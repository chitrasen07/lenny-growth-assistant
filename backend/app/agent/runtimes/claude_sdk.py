"""Anthropic Claude Agent SDK runtime.

Registers the same skills from ``SkillRegistry`` as in-process MCP tools and lets Claude
choose which to call. Because the tool handlers execute inside this process, the retrieval
results and artifacts a skill produces are captured in a run-scoped collector and returned
alongside the model's text — so citations and the Artifact Viewer work identically to the
router runtime.

Operational notes (see README "Cloud LLM Setup"):
* Requires ``claude-agent-sdk`` (production ``requirements.txt``; it ships a bundled
  Claude Code CLI binary) and a valid ``ANTHROPIC_API_KEY``.
* Cloud-only by nature — the SDK drives Anthropic models, so it cannot serve the local
  Ollama demo. ``AgentService`` selects this runtime when the resolved provider is
  Anthropic; Ollama stays on ``RouterRuntime``.
"""

from __future__ import annotations

from typing import Any

from app.agent.registry import SkillRegistry
from app.agent.routing import Route, route
from app.agent.types import Intent, SkillContext, SkillResult
from app.core.config import Settings, get_settings
from app.core.errors import ProviderConfigurationError, ProviderResponseError
from app.core.logging import get_logger

logger = get_logger(__name__)

_SERVER_NAME = "lenny"

_SYSTEM_PROMPT = """\
You are the Lenny Growth Assistant. You help with product management and growth questions \
using ONLY knowledge retrieved from Lenny's Podcast transcripts.

Always use your tools:
- answer_grounded_question for questions about product, growth or strategy;
- generate_ship30_essay when the user wants an essay or a Ship 30 for 30 piece;
- generate_artifact when the user wants a landing page, web page or document;
- search_transcripts when you need raw excerpts before deciding.

Return the tool's output as your answer, preserving its [S1]-style citation markers \
exactly. Never add facts the tools did not return, and never invent episode titles, guest \
names or URLs.
"""


class ClaudeAgentSDKRuntime:
    """Agent runtime backed by ``claude-agent-sdk``."""

    name = "claude_agent_sdk"

    def __init__(self, registry: SkillRegistry, settings: Settings | None = None) -> None:
        self._registry = registry
        self._settings = settings or get_settings()

    def plan(self, message: str) -> Route:
        # Claude picks the tool itself; this is recorded only so logs and message metadata
        # stay comparable between runtimes.
        return route(message)

    def _load_sdk(self) -> Any:
        try:
            import claude_agent_sdk
        except ImportError as exc:
            raise ProviderConfigurationError(
                "The Claude Agent SDK package is not installed.",
                remedy="pip install claude-agent-sdk (it is in backend/requirements.txt), or switch the provider to Ollama.",
            ) from exc
        if not self._settings.anthropic_api_key:
            raise ProviderConfigurationError(
                "The Anthropic provider requires an API key (Claude Agent SDK runtime).",
                remedy="Set ANTHROPIC_API_KEY in .env, or switch the header back to Ollama (local).",
            )
        return claude_agent_sdk

    def _build_tools(self, sdk: Any, context: SkillContext, collected: list[SkillResult]) -> list[Any]:
        """Wrap each registered skill as an SDK tool that records its structured result."""
        tools: list[Any] = []
        for name in self._registry.names():
            skill = self._registry.require(name)

            def make_handler(skill_name: str) -> Any:
                async def handler(args: dict[str, Any]) -> dict[str, Any]:
                    target = self._registry.require(skill_name)
                    try:
                        result = await target.run(context, **(args or {}))
                    except Exception as exc:  # noqa: BLE001 - reported back to the model
                        logger.error("sdk_tool_failed", skill=skill_name, error=type(exc).__name__)
                        return {"content": [{"type": "text", "text": f"Tool '{skill_name}' failed: {exc}"}], "isError": True}
                    collected.append(result)
                    return {"content": [{"type": "text", "text": result.text}]}

                return handler

            tools.append(sdk.tool(skill.name, skill.description, skill.parameters)(make_handler(skill.name)))
        return tools

    async def run(self, message: str, context: SkillContext, *, plan: Route | None = None) -> tuple[SkillResult, Route]:
        sdk = self._load_sdk()
        decision = plan or self.plan(message)
        collected: list[SkillResult] = []

        server = sdk.create_sdk_mcp_server(
            name=_SERVER_NAME, version="1.0.0", tools=self._build_tools(sdk, context, collected)
        )
        options = sdk.ClaudeAgentOptions(
            mcp_servers={_SERVER_NAME: server},
            allowed_tools=[f"mcp__{_SERVER_NAME}__{name}" for name in self._registry.names()],
            system_prompt=_SYSTEM_PROMPT,
            model=self._settings.anthropic_model,
            max_turns=4,
            # Ignore any repo-level .mcp.json so behaviour does not vary by checkout.
            strict_mcp_config=True,
        )

        transcript = self._render_history(context)
        prompt = f"{transcript}\n\nUser: {message}" if transcript else message

        text_parts: list[str] = []
        try:
            async with sdk.ClaudeSDKClient(options=options) as client:
                await client.query(prompt)
                async for event in client.receive_response():
                    text_parts.extend(self._extract_text(event))
        except ProviderConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalised for the API layer
            logger.error("claude_sdk_run_failed", error=type(exc).__name__)
            raise ProviderResponseError(
                f"The Claude Agent SDK run failed ({type(exc).__name__}).",
                remedy="Check ANTHROPIC_API_KEY and network access, or switch the provider to Ollama.",
            ) from exc

        answer = "\n".join(part for part in text_parts if part.strip()).strip()

        # Prefer a skill's own structured output: it already ran citation validation and
        # carries verified sources and any artifact. Never replace that text with the SDK
        # model's unvalidated restatement.
        primary = self._primary_result(collected, decision)
        if primary is not None:
            primary.meta.setdefault("runtime", self.name)
            primary.meta["sdk_tools_invoked"] = len(collected)
            return primary, decision

        logger.warning("claude_sdk_no_tool_used")
        return (
            SkillResult(
                text=answer or "The agent returned no content.",
                refused=not answer,
                meta={"runtime": self.name, "sdk_tools_invoked": 0, "skill": "none"},
            ),
            decision,
        )

    @staticmethod
    def _primary_result(collected: list[SkillResult], decision: Route) -> SkillResult | None:
        if not collected:
            return None
        # An artifact is the user-visible deliverable, so it wins regardless of call order.
        for result in reversed(collected):
            if result.artifact is not None:
                return result
        if decision.intent is Intent.QUESTION:
            for result in reversed(collected):
                if result.retrieval is not None:
                    return result
        return collected[-1]

    @staticmethod
    def _extract_text(event: Any) -> list[str]:
        """Pull text blocks out of an SDK message, tolerating unknown event types."""
        parts: list[str] = []
        for block in getattr(event, "content", None) or []:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        if not parts and isinstance(getattr(event, "result", None), str):
            parts.append(event.result)
        return parts

    def _render_history(self, context: SkillContext) -> str:
        if not context.history:
            return ""
        lines = [f"{'User' if role == 'user' else 'Assistant'}: {content}" for role, content in context.history]
        rendered = "\n".join(lines)
        limit = self._settings.max_history_chars
        return rendered if len(rendered) <= limit else rendered[-limit:]
