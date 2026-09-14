"""Provider abstraction: routing, configuration failures and unavailability.

These tests assert that each failure mode produces a *specific, actionable* error rather
than a generic 500, and that no provider silently substitutes for another.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import LLMProviderName, Settings
from app.core.errors import (
    EmbeddingError,
    ProviderConfigurationError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.providers.anthropic import AnthropicProvider
from app.providers.base import ChatMessage
from app.providers.factory import get_provider
from app.providers.ollama import OllamaProvider


def _ollama(handler, **kwargs) -> OllamaProvider:  # noqa: ANN001
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://localhost:11434", timeout=5.0)
    return OllamaProvider("http://localhost:11434", kwargs.pop("model", "llama3.1:8b"), client=client, **kwargs)


# ------------------------------------------------------------------ factory routing
def test_factory_returns_the_configured_provider():
    settings = Settings(llm_provider=LLMProviderName.OLLAMA, ollama_model="llama3.1:8b")

    provider = get_provider(settings=settings)

    assert provider.name == "ollama"
    assert provider.model == "llama3.1:8b"


def test_factory_honours_a_per_request_override():
    """The UI toggle must switch provider without restarting the app."""
    settings = Settings(llm_provider=LLMProviderName.OLLAMA, anthropic_api_key="test-key")

    provider = get_provider(LLMProviderName.ANTHROPIC, settings=settings)

    assert provider.name == "anthropic"
    assert provider.model == settings.anthropic_model


def test_switching_provider_changes_no_calling_code():
    settings = Settings(anthropic_api_key="test-key")

    for name in (LLMProviderName.OLLAMA, LLMProviderName.ANTHROPIC):
        provider = get_provider(name, settings=settings)
        # Both satisfy the same interface, which is what makes the toggle safe.
        assert hasattr(provider, "complete") and hasattr(provider, "chat_with_tools")
        assert provider.supports_tools is True


# ------------------------------------------------------------------- ollama failures
async def test_ollama_unavailable_reports_the_url_and_the_fix():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ProviderUnavailableError) as exc_info:
        await _ollama(handler).complete([ChatMessage("user", "hello")])

    error = exc_info.value
    assert error.status_code == 503
    assert error.code == "provider_unavailable"
    assert "11434" in error.message
    assert "ollama serve" in (error.remedy or "")


async def test_ollama_timeout_is_distinct_from_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(ProviderTimeoutError) as exc_info:
        await _ollama(handler).complete([ChatMessage("user", "hello")])

    assert exc_info.value.status_code == 504
    assert exc_info.value.code == "provider_timeout"


async def test_missing_ollama_model_tells_the_user_to_pull_it():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(ProviderResponseError) as exc_info:
        await _ollama(handler, model="llama3.1:8b").complete([ChatMessage("user", "hello")])

    assert "ollama pull llama3.1:8b" in (exc_info.value.remedy or "")


async def test_ollama_parses_text_and_tool_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": "Using a tool.",
                    "tool_calls": [{"function": {"name": "search_transcripts", "arguments": {"query": "activation"}}}],
                },
                "prompt_eval_count": 120,
                "eval_count": 30,
            },
        )

    response = await _ollama(handler).chat_with_tools([ChatMessage("user", "hi")], [])

    assert response.text == "Using a tool."
    assert [call.name for call in response.tool_calls] == ["search_transcripts"]
    assert response.tool_calls[0].arguments == {"query": "activation"}
    assert response.usage == {"prompt_eval_count": 120, "eval_count": 30}
    assert response.latency_ms >= 0


async def test_ollama_health_flags_a_model_that_is_not_pulled():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "mistral:7b"}]})

    health = await _ollama(handler, model="llama3.1:8b").health()

    assert health.available is False
    assert "ollama pull llama3.1:8b" in (health.detail or "")


async def test_ollama_health_accepts_a_pulled_model():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"models": [{"name": "llama3.1:8b"}, {"name": "nomic-embed-text:latest"}]},
        )

    assert (await _ollama(handler, model="llama3.1:8b").health()).available is True


async def test_ollama_health_flags_a_missing_embedding_model():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})

    health = await _ollama(handler, model="llama3.1:8b").health()

    assert health.available is False
    assert "nomic-embed-text" in (health.detail or "")


async def test_ollama_http_error_includes_the_provider_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "llama runner process has terminated"})

    with pytest.raises(ProviderResponseError) as exc_info:
        await _ollama(handler).complete([ChatMessage("user", "hello")])

    assert "llama runner process has terminated" in exc_info.value.message
    assert "Restart the host Ollama" in (exc_info.value.remedy or "")


async def test_embedding_failure_surfaces_as_embedding_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(EmbeddingError) as exc_info:
        await _ollama(handler).embed(["some text"])

    assert exc_info.value.code == "embedding_failed"


async def test_embedding_count_mismatch_is_rejected():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    with pytest.raises(EmbeddingError):
        await _ollama(handler).embed(["first", "second"])


# ---------------------------------------------------------------- anthropic failures
async def test_anthropic_without_a_key_raises_a_configuration_error():
    provider = AnthropicProvider(api_key=None, model="claude-sonnet-4-5")

    with pytest.raises(ProviderConfigurationError) as exc_info:
        await provider.complete([ChatMessage("user", "hello")])

    error = exc_info.value
    assert error.code == "provider_not_configured"
    assert "ANTHROPIC_API_KEY" in (error.remedy or "")


async def test_anthropic_health_is_unavailable_but_never_raises():
    health = await AnthropicProvider(api_key=None, model="claude-sonnet-4-5").health()

    assert health.available is False
    assert "ANTHROPIC_API_KEY" in (health.detail or "")


async def test_anthropic_error_messages_never_include_the_key():
    provider = AnthropicProvider(api_key="sk-ant-supersecret", model="claude-sonnet-4-5")

    class FailingMessages:
        async def create(self, **kwargs):  # noqa: ANN003, ANN201
            raise RuntimeError("AuthenticationError: invalid key")

    class FailingClient:
        messages = FailingMessages()

    provider._client = FailingClient()  # noqa: SLF001 - injecting a stub client

    with pytest.raises(Exception) as exc_info:
        await provider.complete([ChatMessage("user", "hello")])

    assert "sk-ant-supersecret" not in str(exc_info.value)


async def test_anthropic_splits_the_system_prompt_and_parses_tool_use():
    captured: dict = {}

    class Block:
        def __init__(self, **kwargs):  # noqa: ANN003
            self.__dict__.update(kwargs)

    class Messages:
        async def create(self, **kwargs):  # noqa: ANN003, ANN201
            captured.update(kwargs)
            return Block(
                content=[
                    Block(type="text", text="Here is the answer."),
                    Block(type="tool_use", id="tool_1", name="search_transcripts", input={"query": "activation"}),
                ],
                usage=Block(input_tokens=50, output_tokens=12),
            )

    class Client:
        messages = Messages()

    provider = AnthropicProvider(api_key="test-key", model="claude-sonnet-4-5", client=Client())
    response = await provider.complete(
        [ChatMessage("system", "You are grounded."), ChatMessage("user", "How do I activate users?")]
    )

    # Anthropic takes 'system' as a top-level argument, not as a message.
    assert captured["system"] == "You are grounded."
    assert [message["role"] for message in captured["messages"]] == ["user"]
    assert response.text == "Here is the answer."
    assert [call.name for call in response.tool_calls] == ["search_transcripts"]
    assert response.usage == {"input_tokens": 50, "output_tokens": 12}
