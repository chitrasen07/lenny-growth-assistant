"""Session lifecycle, persistence, isolation and request validation."""

from __future__ import annotations

import uuid

import pytest

from app.models.chat import MessageRole
from app.services.sessions import SessionService, derive_title


async def _create_session(client, title=None):  # noqa: ANN001
    response = await client.post("/api/sessions", json={"title": title} if title else {})
    assert response.status_code == 201
    return response.json()


async def test_create_session_returns_persisted_record(client):  # noqa: ANN001
    body = await _create_session(client, "Activation research")

    assert body["title"] == "Activation research"
    assert body["message_count"] == 0
    assert uuid.UUID(body["id"])  # server-generated identifier

    fetched = await client.get(f"/api/sessions/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


async def test_sessions_listed_most_recently_updated_first(client):  # noqa: ANN001
    first = await _create_session(client, "Older")
    second = await _create_session(client, "Newer")

    listed = (await client.get("/api/sessions")).json()
    ids = [item["id"] for item in listed]

    assert set(ids) == {first["id"], second["id"]}
    assert ids.index(second["id"]) < ids.index(first["id"])


async def test_messages_persist_with_role_content_and_timestamp(client, db, session_factory):  # noqa: ANN001
    created = await _create_session(client, "Persistence")
    session_id = uuid.UUID(created["id"])

    async with session_factory() as writer:
        service = SessionService(writer)
        await service.add_message(session_id, MessageRole.USER, "How do I improve activation?")
        await service.add_message(session_id, MessageRole.ASSISTANT, "Focus on first value.", {"provider": "ollama"})
        await writer.commit()

    messages = (await client.get(f"/api/sessions/{session_id}/messages")).json()

    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "How do I improve activation?"
    assert messages[1]["metadata"]["provider"] == "ollama"
    assert messages[0]["created_at"] <= messages[1]["created_at"]
    # Ordering must come from the database, not from insertion luck.
    assert all(message["session_id"] == str(session_id) for message in messages)


async def test_sessions_are_isolated(client, session_factory):  # noqa: ANN001
    """Messages written to one session must never surface in another."""
    first = uuid.UUID((await _create_session(client, "Session A"))["id"])
    second = uuid.UUID((await _create_session(client, "Session B"))["id"])

    async with session_factory() as writer:
        service = SessionService(writer)
        await service.add_message(first, MessageRole.USER, "Question about activation")
        await service.add_message(second, MessageRole.USER, "Question about pricing")
        await writer.commit()

    first_messages = (await client.get(f"/api/sessions/{first}/messages")).json()
    second_messages = (await client.get(f"/api/sessions/{second}/messages")).json()

    assert [message["content"] for message in first_messages] == ["Question about activation"]
    assert [message["content"] for message in second_messages] == ["Question about pricing"]


async def test_prompt_history_is_scoped_to_one_session(session_factory):  # noqa: ANN001
    """The agent's context builder must not read another session's turns."""
    async with session_factory() as writer:
        service = SessionService(writer)
        first = await service.create("A")
        second = await service.create("B")
        await service.add_message(first.id, MessageRole.USER, "activation question")
        await service.add_message(second.id, MessageRole.USER, "pricing question")
        await writer.commit()

        history = await service.history_for_prompt(first.id)

    assert history == [("user", "activation question")]


async def test_history_is_bounded_and_chronological(session_factory, settings):  # noqa: ANN001
    async with session_factory() as writer:
        service = SessionService(writer, settings)
        session = await service.create("Long")
        for index in range(settings.max_history_messages + 6):
            await service.add_message(session.id, MessageRole.USER, f"message {index}")
        await writer.commit()

        history = await service.history_for_prompt(session.id)

    assert len(history) <= settings.max_history_messages
    # Oldest first, and the most recent turn is always retained.
    assert history[-1][1] == f"message {settings.max_history_messages + 5}"
    assert sum(len(content) for _, content in history) <= settings.max_history_chars


async def test_deleting_a_session_cascades_to_messages(client, session_factory):  # noqa: ANN001
    created = await _create_session(client, "Doomed")
    session_id = uuid.UUID(created["id"])

    async with session_factory() as writer:
        await SessionService(writer).add_message(session_id, MessageRole.USER, "hello")
        await writer.commit()

    assert (await client.delete(f"/api/sessions/{session_id}")).status_code == 204
    assert (await client.get(f"/api/sessions/{session_id}")).status_code == 404
    assert (await client.get(f"/api/sessions/{session_id}/messages")).status_code == 404


async def test_unknown_session_returns_structured_not_found(client):  # noqa: ANN001
    response = await client.get(f"/api/sessions/{uuid.uuid4()}")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert "does not exist" in error["message"]


async def test_malformed_session_id_is_rejected(client):  # noqa: ANN001
    response = await client.get("/api/sessions/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


@pytest.mark.parametrize(
    ("payload", "expected_field"),
    [
        ({"message": "hi"}, "session_id"),
        ({"session_id": str(uuid.uuid4())}, "message"),
        ({"session_id": str(uuid.uuid4()), "message": "   "}, "message"),
        ({"session_id": str(uuid.uuid4()), "message": "x" * 8001}, "message"),
    ],
)
async def test_chat_request_validation(client, payload, expected_field):  # noqa: ANN001
    response = await client.post("/api/chat", json=payload)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert any(expected_field in field["field"] for field in error["details"]["fields"])


def test_title_derived_from_first_message_is_trimmed_at_a_word_boundary():
    title = derive_title("How should I think about improving activation for a self-serve product in 2026 and beyond?")

    assert len(title) <= 61
    assert title.endswith("…")
    assert not title.rstrip("…").endswith(" ")
