"""Claude Agent SDK runtime.

The SDK is exercised against a stub module: it bundles a Claude Code CLI and needs real
Anthropic credentials, so calling it for real would make the suite non-deterministic and
billable. What is verified here is our integration contract — that skills are registered
as SDK tools, that a tool's structured result (sources, artifact) is preserved rather
than flattened to text, and that missing configuration fails with a clear message.

Verifying the runtime against the live API is a manual step; see
docs/manual-test-plan.md ("Claude Agent SDK runtime").
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from app.agent.registry import SkillRegistry
from app.agent.runtimes.claude_sdk import ClaudeAgentSDKRuntime
from app.agent.types import SkillContext
from app.core.config import AgentRuntimeName, Settings
from app.core.errors import ProviderConfigurationError, ProviderResponseError
from app.rag.retrieval import RetrievalService
from tests.conftest import ACTIVATION_CHUNKS, seed_transcript


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _Message:
    def __init__(self, blocks: list[_TextBlock]) -> None:
        self.content = blocks


def _install_stub_sdk(monkeypatch, *, tool_to_call: str | None, tool_args: dict[str, Any] | None = None,
                      final_text: str = "Here is the grounded answer.", raise_on_query: Exception | None = None):  # noqa: ANN001
    """Install a minimal in-memory stand-in for the claude_agent_sdk package."""
    module = types.ModuleType("claude_agent_sdk")
    registered: dict[str, Any] = {}
    state: dict[str, Any] = {"options": None, "prompts": []}

    def tool(name: str, description: str, schema: dict):  # noqa: ANN202
        def decorator(handler):  # noqa: ANN001, ANN202
            registered[name] = handler
            return {"name": name, "description": description, "schema": schema, "handler": handler}

        return decorator

    def create_sdk_mcp_server(name: str, version: str, tools: list[Any]):  # noqa: ANN202
        return {"name": name, "version": version, "tools": tools}

    class ClaudeAgentOptions:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)
            state["options"] = self

    class ClaudeSDKClient:
        def __init__(self, options: Any) -> None:
            self.options = options

        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def query(self, prompt: str) -> None:
            state["prompts"].append(prompt)
            if raise_on_query is not None:
                raise raise_on_query

        async def receive_response(self):  # noqa: ANN202
            if tool_to_call:
                await registered[tool_to_call](tool_args or {})
            yield _Message([_TextBlock(final_text)])

    module.tool = tool
    module.create_sdk_mcp_server = create_sdk_mcp_server
    module.ClaudeAgentOptions = ClaudeAgentOptions
    module.ClaudeSDKClient = ClaudeSDKClient
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", module)
    return state


def _settings() -> Settings:
    return Settings(
        anthropic_api_key="test-key",
        agent_runtime=AgentRuntimeName.CLAUDE_AGENT_SDK,
        embedding_provider="hash",
        retrieval_max_distance=0.90,
    )


async def test_runtime_registers_every_skill_as_an_sdk_tool(db, provider, monkeypatch):  # noqa: ANN001
    settings = _settings()
    state = _install_stub_sdk(monkeypatch, tool_to_call=None)
    registry = SkillRegistry(settings)
    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))

    await ClaudeAgentSDKRuntime(registry, settings).run("How do I improve activation?", context)

    options = state["options"]
    assert set(options.mcp_servers) == {"lenny"}
    tool_names = {entry["name"] for entry in options.mcp_servers["lenny"]["tools"]}
    assert tool_names == set(registry.names())
    # Tools must be pre-approved, or the SDK would block on a permission prompt.
    assert options.allowed_tools == [f"mcp__lenny__{name}" for name in registry.names()]
    assert options.strict_mcp_config is True


async def test_a_tools_structured_result_is_preserved(db, provider, monkeypatch):  # noqa: ANN001
    """Sources must survive the SDK round trip, not be flattened into prose."""
    settings = _settings()
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS, guest="Dana Okoye")
    provider.queue("Measure the first meaningful action [S1].")
    _install_stub_sdk(
        monkeypatch,
        tool_to_call="answer_grounded_question",
        tool_args={"question": "How do we measure activation?"},
    )
    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))

    result, route = await ClaudeAgentSDKRuntime(SkillRegistry(settings), settings).run(
        "How do we measure activation?", context
    )

    assert result.retrieval is not None
    assert result.retrieval.chunks[0].title == "Activation deep dive"
    assert result.meta["runtime"] == "claude_agent_sdk"
    assert result.meta["sdk_tools_invoked"] == 1
    assert route.intent.value == "question"


async def test_an_artifact_produced_by_a_tool_is_returned(db, provider, monkeypatch):  # noqa: ANN001
    settings = _settings()
    provider.queue("# Activation Playbook\n\nBody.")
    _install_stub_sdk(
        monkeypatch,
        tool_to_call="generate_artifact",
        tool_args={"artifact_type": "markdown", "instruction": "one-pager"},
    )
    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))

    result, _ = await ClaudeAgentSDKRuntime(SkillRegistry(settings), settings).run(
        "Create a markdown one-pager", context
    )

    assert result.artifact is not None
    assert result.artifact.title == "Activation Playbook"


async def test_conversation_history_is_passed_to_the_agent(db, provider, monkeypatch):  # noqa: ANN001
    settings = _settings()
    state = _install_stub_sdk(monkeypatch, tool_to_call=None)
    context = SkillContext(
        provider=provider,
        retrieval=RetrievalService(db, settings),
        history=[("user", "How do I improve activation?"), ("assistant", "Focus on first value.")],
    )

    await ClaudeAgentSDKRuntime(SkillRegistry(settings), settings).run("What about for B2B SaaS?", context)

    prompt = state["prompts"][0]
    assert "How do I improve activation?" in prompt
    assert "What about for B2B SaaS?" in prompt


async def test_text_only_reply_without_a_tool_call_is_reported(db, provider, monkeypatch):  # noqa: ANN001
    settings = _settings()
    _install_stub_sdk(monkeypatch, tool_to_call=None, final_text="I answered without tools.")
    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))

    result, _ = await ClaudeAgentSDKRuntime(SkillRegistry(settings), settings).run("hello", context)

    assert result.text == "I answered without tools."
    assert result.meta["sdk_tools_invoked"] == 0
    assert result.meta["skill"] == "none"


async def test_missing_api_key_fails_with_a_clear_remedy(db, provider, monkeypatch):  # noqa: ANN001
    settings = Settings(anthropic_api_key=None, agent_runtime=AgentRuntimeName.CLAUDE_AGENT_SDK)
    _install_stub_sdk(monkeypatch, tool_to_call=None)
    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))

    with pytest.raises(ProviderConfigurationError) as exc_info:
        await ClaudeAgentSDKRuntime(SkillRegistry(settings), settings).run("hello", context)

    assert "ANTHROPIC_API_KEY" in (exc_info.value.remedy or "")
    assert "Ollama" in (exc_info.value.remedy or "")


async def test_missing_package_fails_with_an_install_hint(db, provider, monkeypatch):  # noqa: ANN001
    settings = _settings()
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))

    with pytest.raises(ProviderConfigurationError) as exc_info:
        await ClaudeAgentSDKRuntime(SkillRegistry(settings), settings).run("hello", context)

    assert "Claude Agent SDK" in exc_info.value.message
    assert "not installed" in exc_info.value.message


async def test_sdk_failure_is_normalised_for_the_api(db, provider, monkeypatch):  # noqa: ANN001
    settings = _settings()
    _install_stub_sdk(monkeypatch, tool_to_call=None, raise_on_query=RuntimeError("CLI crashed"))
    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))

    with pytest.raises(ProviderResponseError) as exc_info:
        await ClaudeAgentSDKRuntime(SkillRegistry(settings), settings).run("hello", context)

    assert exc_info.value.status_code == 502
    assert "Ollama" in (exc_info.value.remedy or "")


def test_agent_service_selects_runtime_from_the_resolved_provider(db, provider):  # noqa: ANN001
    from app.agent.service import AgentService
    from tests.conftest import FakeProvider

    service = AgentService(db, Settings(agent_runtime=AgentRuntimeName.ROUTER))
    cloud = FakeProvider(model="claude-sonnet-4-5")
    cloud.name = "anthropic"

    assert service.runtime(provider).name == "router"
    assert service.runtime(cloud).name == "claude_agent_sdk"


async def test_handle_uses_claude_agent_sdk_runtime_for_anthropic(db, provider, monkeypatch):  # noqa: ANN001
    """An Anthropic chat turn must enter ClaudeAgentSDKRuntime, not the router."""
    from app.agent.service import AgentService
    from tests.conftest import FakeProvider

    settings = _settings()
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    cloud = FakeProvider(model="claude-sonnet-4-5")
    cloud.name = "anthropic"
    cloud.queue("Measure the first meaningful action [S1].")
    _install_stub_sdk(
        monkeypatch,
        tool_to_call="answer_grounded_question",
        tool_args={"question": "How do we measure activation?"},
    )

    result, _route, used = await AgentService(db, settings).handle(
        "How do we measure activation?",
        history=[],
        provider=cloud,
    )

    assert used.name == "anthropic"
    assert result.meta["runtime"] == "claude_agent_sdk"
    assert cloud.calls, "the Anthropic provider must still run the skill"
    assert provider.calls == [], "Ollama must not be invoked for an Anthropic request"


async def test_handle_uses_router_runtime_for_ollama(db, provider):  # noqa: ANN001
    from app.agent.service import AgentService

    settings = Settings(embedding_provider="hash", retrieval_max_distance=0.90)
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    provider.queue("Measure the first meaningful action [S1].")

    result, _route, used = await AgentService(db, settings).handle(
        "How do we measure activation?",
        history=[],
        provider=provider,
    )

    assert used.name == "ollama"
    assert result.meta["runtime"] == "router"
    assert provider.calls


async def test_sdk_assistant_text_does_not_replace_validated_skill_text(db, provider, monkeypatch):  # noqa: ANN001
    """Citation-validated skill output must win over the SDK model's restatement."""
    settings = _settings()
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS, guest="Dana Okoye")
    validated = "Measure the first meaningful action [S1]."
    provider.queue(validated)
    restatement = "According to a made-up guest, activation jumped 73% with no citation."
    _install_stub_sdk(
        monkeypatch,
        tool_to_call="answer_grounded_question",
        tool_args={"question": "How do we measure activation?"},
        final_text=restatement,
    )
    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))

    result, _ = await ClaudeAgentSDKRuntime(SkillRegistry(settings), settings).run(
        "How do we measure activation?", context
    )

    assert result.text != restatement
    assert "73%" not in result.text
    assert "made-up guest" not in result.text
    assert "[S1]" in result.text
    assert "first meaningful action" in result.text
    assert result.retrieval is not None
    assert 1 in (result.meta.get("cited_markers") or [])
    assert result.meta["runtime"] == "claude_agent_sdk"
