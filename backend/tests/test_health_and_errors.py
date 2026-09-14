"""Health/config endpoints and failure handling at the API boundary."""

from __future__ import annotations

import pytest

from app.core.config import LLMProviderName
from app.core.errors import ProviderTimeoutError, ProviderUnavailableError
from app.providers.factory import register_provider
from tests.conftest import ACTIVATION_CHUNKS, seed_transcript


async def _new_session(client) -> str:  # noqa: ANN001
    return (await client.post("/api/sessions", json={})).json()["id"]


# -------------------------------------------------------------------------- health
async def test_health_reports_each_component(client):  # noqa: ANN001
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["api"]["healthy"] is True
    assert body["database"]["healthy"] is True
    assert body["llm_provider"] == "ollama"
    assert body["agent_runtime"] == "router"
    assert body["active_runtime"] == "router"
    assert "ollama" in body and "cloud_provider" in body
    assert body["version"]


async def test_health_is_200_even_without_a_cloud_key(client):  # noqa: ANN001
    """An unconfigured optional provider must not make the service look broken."""
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["cloud_provider"]["healthy"] is False


async def test_health_reports_degraded_when_the_knowledge_base_is_empty(client):  # noqa: ANN001
    body = (await client.get("/health")).json()

    assert body["status"] == "degraded"
    assert body["knowledge_base"]["ready"] is False
    assert body["knowledge_base"]["chunks"] == 0


async def test_health_reports_knowledge_base_size_after_ingestion(client, db):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)

    knowledge_base = (await client.get("/health")).json()["knowledge_base"]

    assert knowledge_base["ready"] is True
    assert knowledge_base["transcripts"] == 1
    assert knowledge_base["chunks"] == len(ACTIVATION_CHUNKS)
    assert knowledge_base["embedding_dimensions"] == 768


async def test_config_exposes_provider_information(client):  # noqa: ANN001
    response = await client.get("/api/config")

    assert response.status_code == 200
    body = response.json()
    assert body["active_provider"] == "ollama"
    assert body["active_model"]
    assert {provider["name"] for provider in body["providers"]} == {"ollama", "anthropic"}
    by_name = {provider["name"]: provider for provider in body["providers"]}
    assert body["active_runtime"] == "router"
    assert body["agent_runtime"] == "router"
    assert by_name["ollama"]["runtime"] == "router"
    assert by_name["anthropic"]["runtime"] == "claude_agent_sdk"
    assert body["retrieval_top_k"] > 0
    assert body["essay_target_words"] == 1250


async def test_configured_api_key_value_is_never_returned(client, monkeypatch):  # noqa: ANN001
    """Naming the variable is helpful; revealing its value is not."""
    from app.core.config import get_settings
    from app.providers.anthropic import AnthropicProvider

    secret = "sk-ant-test-DO-NOT-LEAK-abcdef123456"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    get_settings.cache_clear()
    register_provider(LLMProviderName.ANTHROPIC, AnthropicProvider(api_key=secret, model="claude-sonnet-4-5"))

    config_body = (await client.get("/api/config")).text
    health_body = (await client.get("/health")).text

    assert secret not in config_body
    assert secret not in health_body
    assert "DO-NOT-LEAK" not in config_body + health_body
    get_settings.cache_clear()


async def test_config_reports_why_a_provider_is_unavailable(client):  # noqa: ANN001
    providers = {provider["name"]: provider for provider in (await client.get("/api/config")).json()["providers"]}

    assert providers["anthropic"]["available"] is False
    assert "ANTHROPIC_API_KEY" in providers["anthropic"]["detail"]


# ------------------------------------------------------------------ error handling
async def test_ollama_unavailable_surfaces_as_503_with_a_remedy(client, db, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    provider.raise_error = ProviderUnavailableError(
        "Could not reach Ollama at http://localhost:11434.", remedy="Start it with `ollama serve`."
    )
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat", json={"session_id": session_id, "message": "How do we measure activation?"}
    )

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "provider_unavailable"
    assert "ollama serve" in error["remedy"]


async def test_model_timeout_surfaces_as_504(client, db, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    provider.raise_error = ProviderTimeoutError("Ollama did not respond within 180s.")
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat", json={"session_id": session_id, "message": "How do we measure activation?"}
    )

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "provider_timeout"


async def test_the_user_message_survives_a_provider_failure(client, db, provider):  # noqa: ANN001
    """A failed turn must not lose what the user typed."""
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    provider.raise_error = ProviderUnavailableError("Ollama is down.")
    session_id = await _new_session(client)

    await client.post("/api/chat", json={"session_id": session_id, "message": "How do we measure activation?"})

    messages = (await client.get(f"/api/sessions/{session_id}/messages")).json()
    assert [message["role"] for message in messages] == ["user"]
    assert messages[0]["content"] == "How do we measure activation?"


async def test_explicit_ollama_provider_uses_the_local_model(client, db, provider):  # noqa: ANN001
    """The header's Ollama option must hit the local provider, not the cloud one."""
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    provider.queue("Measure the first meaningful action within seven days [S1].")
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "How do we measure activation?",
            "provider": "ollama",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "ollama"
    assert body["message"]["metadata"]["runtime"] == "router"
    assert provider.calls, "the Ollama stand-in must have been invoked"


async def test_explicit_anthropic_provider_uses_the_claude_agent_sdk(client, db, provider, monkeypatch):  # noqa: ANN001
    """Selecting Anthropic in the UI must enter ClaudeAgentSDKRuntime, not the router."""
    from app.core.config import get_settings
    from tests.conftest import FakeProvider
    from tests.test_claude_sdk_runtime import _install_stub_sdk

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    cloud = FakeProvider(model="claude-sonnet-4-5")
    cloud.name = "anthropic"
    cloud.queue("Measure the first meaningful action within seven days [S1].")
    register_provider(LLMProviderName.ANTHROPIC, cloud)
    _install_stub_sdk(
        monkeypatch,
        tool_to_call="answer_grounded_question",
        tool_args={"question": "How do we measure activation?"},
    )
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    session_id = await _new_session(client)

    try:
        response = await client.post(
            "/api/chat",
            json={
                "session_id": session_id,
                "message": "How do we measure activation?",
                "provider": "anthropic",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-sonnet-4-5"
    assert body["message"]["metadata"]["runtime"] == "claude_agent_sdk"
    assert cloud.calls, "the Anthropic stand-in must have been invoked"
    assert provider.calls == [], "Ollama must not be used when Anthropic is selected"


async def test_cloud_provider_without_a_key_is_reported_as_misconfigured(client, db, settings):  # noqa: ANN001
    """Selecting Anthropic with no key must name the missing variable, not 500."""
    from app.providers.anthropic import AnthropicProvider

    register_provider(LLMProviderName.ANTHROPIC, AnthropicProvider(api_key=None, model="claude-sonnet-4-5"))
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "How do we measure activation?", "provider": "anthropic"},
    )

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "provider_not_configured"
    assert "ANTHROPIC_API_KEY" in error["remedy"]
    assert "Anthropic" in error["message"]
    assert "Claude Agent SDK" in error["message"]


async def test_missing_anthropic_key_does_not_fall_back_to_ollama(client, db, provider):  # noqa: ANN001
    """A missing cloud key must fail the turn, not silently answer with Ollama."""
    from app.providers.anthropic import AnthropicProvider

    register_provider(LLMProviderName.ANTHROPIC, AnthropicProvider(api_key=None, model="claude-sonnet-4-5"))
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    provider.queue("This Ollama answer must never be returned.")
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "How do we measure activation?", "provider": "anthropic"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_not_configured"
    assert "Claude Agent SDK" in response.json()["error"]["message"]
    assert provider.calls == [], "Ollama must not be invoked as a fallback"
    assert "Ollama answer" not in (response.json()["error"].get("message") or "")


async def test_unknown_provider_value_is_rejected_by_validation(client):  # noqa: ANN001
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat", json={"session_id": session_id, "message": "hello", "provider": "gpt-9"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


async def test_oversized_body_is_rejected_before_parsing(client):  # noqa: ANN001
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "x" * 200},
        headers={"content-length": "2000000"},
    )

    assert response.status_code in (413, 422)


async def test_every_error_uses_the_same_envelope(client):  # noqa: ANN001
    responses = [
        await client.get("/api/sessions/00000000-0000-0000-0000-000000000000"),
        await client.post("/api/chat", json={}),
        await client.get("/api/nope"),
    ]

    for response in responses:
        assert response.status_code >= 400
        error = response.json()["error"]
        assert isinstance(error["code"], str) and error["code"]
        assert isinstance(error["message"], str) and error["message"]


async def test_requests_carry_a_correlation_id(client):  # noqa: ANN001
    response = await client.get("/health")

    assert response.headers["x-request-id"]


async def test_a_supplied_request_id_is_echoed(client):  # noqa: ANN001
    response = await client.get("/health", headers={"x-request-id": "trace-me-123"})

    assert response.headers["x-request-id"] == "trace-me-123"


@pytest.mark.parametrize("path", ["/health", "/api/config"])
async def test_read_endpoints_do_not_require_a_body(client, path):  # noqa: ANN001
    assert (await client.get(path)).status_code == 200
