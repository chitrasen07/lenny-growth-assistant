"""End-to-end chat behaviour: grounding, citations, refusal, follow-up context."""

from __future__ import annotations

import uuid

from app.agent.prompts import REFUSAL_MESSAGE
from tests.conftest import ACTIVATION_CHUNKS, PRICING_CHUNKS, seed_transcript


async def _new_session(client) -> str:  # noqa: ANN001
    response = await client.post("/api/sessions", json={})
    assert response.status_code == 201
    return response.json()["id"]


async def test_grounded_answer_returns_citations_resolvable_to_chunks(client, db, provider):  # noqa: ANN001
    transcript = await seed_transcript(
        db,
        title="Activation deep dive",
        chunks=ACTIVATION_CHUNKS,
        episode="Episode 42",
        guest="Dana Okoye",
        source_url="https://example.com/activation",
    )
    provider.queue("Measure the first meaningful action within seven days [S1].")
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "How do we measure activation for new users?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is True
    assert body["intent"] == "question"

    sources = body["message"]["sources"]
    assert sources, "a grounded answer must expose its sources"
    cited = [source for source in sources if source["cited"]]
    assert cited, "the [S1] marker must be recorded as a citation"
    assert cited[0]["transcript_id"] == str(transcript.id)
    assert cited[0]["title"] == "Activation deep dive"
    assert cited[0]["guest"] == "Dana Okoye"
    assert cited[0]["source_url"] == "https://example.com/activation"
    assert cited[0]["excerpt"]
    # The excerpt must genuinely come from the indexed chunk, not from the model.
    assert cited[0]["excerpt"].rstrip("…") in "\n".join(ACTIVATION_CHUNKS)


async def test_model_sees_retrieved_evidence_in_its_prompt(client, db, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    session_id = await _new_session(client)

    await client.post(
        "/api/chat", json={"session_id": session_id, "message": "How do we measure activation?"}
    )

    prompt = provider.last_prompt
    assert "EVIDENCE" in prompt
    assert "[S1]" in prompt
    assert "activation" in prompt.lower()


async def test_unsupported_question_is_refused_without_calling_the_model(client, db, provider):  # noqa: ANN001
    """The refusal must not be a model behaviour we merely hope for."""
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    provider.queue("Sourdough needs 75% hydration and a hot Dutch oven.")
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "What is the best sourdough hydration ratio?"},
    )

    body = response.json()
    assert body["grounded"] is False
    assert body["message"]["content"] == REFUSAL_MESSAGE
    assert body["message"]["sources"] == []
    assert provider.calls == [], "no LLM call should be made when there is no evidence"


async def test_empty_knowledge_base_refuses_with_a_distinct_reason(client, provider):  # noqa: ANN001
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat", json={"session_id": session_id, "message": "How do I improve activation?"}
    )

    body = response.json()
    assert body["grounded"] is False
    assert body["message"]["content"] == REFUSAL_MESSAGE
    assert body["message"]["metadata"]["refusal_reason"] == "knowledge_base_empty"


async def test_guest_claim_cannot_be_attributed_to_the_host(client, db, provider):  # noqa: ANN001
    """A valid [Sn] is not enough if the cited speaker is not the named person."""
    await seed_transcript(
        db,
        title="5 questions to ask when your product stops growing",
        guest="Jason Cohen",
        speakers=["Jason Cohen"],
        chunks=[
            "Jason Cohen: When your product stops growing, ask whether customers are leaving. "
            "The next step is pricing and positioning.",
        ],
    )
    provider.queue(
        "When a product stops growing, Jason Cohen says to ask whether customers are leaving [S1]. "
        "The next step is to consider pricing and positioning, as mentioned by Lenny Rachitsky in [S1]."
    )
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "What questions should I ask when my product stops growing?"},
    )

    body = response.json()
    content = body["message"]["content"]
    assert body["grounded"] is True
    assert "Lenny Rachitsky" not in content
    assert "as mentioned by" not in content
    assert "Jason Cohen" in content
    assert "[S1]" in content
    assert "customers are leaving" in content


async def test_unsupported_host_attribution_refuses_when_nothing_verifiable_remains(client, db, provider):  # noqa: ANN001
    await seed_transcript(
        db,
        title="5 questions to ask when your product stops growing",
        guest="Jason Cohen",
        speakers=["Jason Cohen"],
        chunks=[
            "Jason Cohen: When your product stops growing, the next step is pricing and positioning.",
        ],
    )
    provider.queue(
        "The next step is to consider pricing and positioning, as mentioned by Lenny Rachitsky in [S1]."
    )
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "What questions should I ask when my product stops growing?"},
    )

    body = response.json()
    assert body["grounded"] is False
    assert body["message"]["content"] == REFUSAL_MESSAGE
    assert body["message"]["metadata"]["refusal_reason"] == "attribution_unverified"


async def test_citation_markers_without_a_matching_source_are_stripped(client, db, provider):  # noqa: ANN001
    """A model may hallucinate [S9]; the UI must never show a dangling citation."""
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS[:1])
    provider.queue("Activation matters [S1] and retention triples [S9].")
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat", json={"session_id": session_id, "message": "How do we measure activation?"}
    )

    body = response.json()
    assert "[S9]" not in body["message"]["content"]
    assert "[S1]" in body["message"]["content"]
    assert body["message"]["metadata"]["dropped_markers"] == [9]


async def test_follow_up_question_uses_prior_turns_of_the_same_session(client, db, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    session_id = await _new_session(client)

    await client.post(
        "/api/chat", json={"session_id": session_id, "message": "How do I improve activation?"}
    )
    follow_up = await client.post(
        "/api/chat", json={"session_id": session_id, "message": "What about for B2B SaaS?"}
    )

    assert follow_up.status_code == 200
    body = follow_up.json()
    # The vague follow-up still retrieved evidence, which only works via inherited context.
    assert body["message"]["sources"], "follow-up should still be grounded"
    prompt = provider.last_prompt
    assert "How do I improve activation?" in prompt, "prior turn must reach the prompt"


async def test_context_does_not_leak_between_sessions(client, db, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    await seed_transcript(db, title="Pricing teardown", chunks=PRICING_CHUNKS)

    first = await _new_session(client)
    second = await _new_session(client)

    await client.post("/api/chat", json={"session_id": first, "message": "How do I improve activation?"})
    await client.post("/api/chat", json={"session_id": second, "message": "How should I package pricing tiers?"})

    prompt = provider.last_prompt
    assert "How do I improve activation?" not in prompt, "second session must not see the first's turns"

    second_messages = (await client.get(f"/api/sessions/{second}/messages")).json()
    assert all("activation" not in message["content"].lower() for message in second_messages if message["role"] == "user")


async def test_conversation_is_persisted_across_requests(client, db, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    session_id = await _new_session(client)

    await client.post("/api/chat", json={"session_id": session_id, "message": "How do we measure activation?"})

    messages = (await client.get(f"/api/sessions/{session_id}/messages")).json()
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["metadata"]["provider"] == "ollama"
    assert messages[1]["metadata"]["intent"] == "question"

    listed = (await client.get("/api/sessions")).json()
    session = next(item for item in listed if item["id"] == session_id)
    assert session["message_count"] == 2
    # The session title should come from the opening question.
    assert "activation" in session["title"].lower()


async def test_chat_against_unknown_session_returns_404(client):  # noqa: ANN001
    response = await client.post(
        "/api/chat", json={"session_id": str(uuid.uuid4()), "message": "How do I improve activation?"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_response_reports_provider_model_and_timings(client, db, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    session_id = await _new_session(client)

    body = (
        await client.post("/api/chat", json={"session_id": session_id, "message": "How do we measure activation?"})
    ).json()

    assert body["provider"] == "ollama"
    assert body["model"] == "fake-model"
    assert body["timings_ms"]["total_ms"] >= 0
    assert "retrieval_ms" in body["timings_ms"]
