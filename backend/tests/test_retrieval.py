"""Retrieval behaviour: ranking, thresholds, source metadata, follow-up query building."""

from __future__ import annotations

from app.rag.retrieval import RetrievalService
from tests.conftest import ACTIVATION_CHUNKS, PRICING_CHUNKS, seed_transcript


async def test_retrieval_ranks_the_relevant_transcript_first(db, settings):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS, guest="Dana Okoye")
    await seed_transcript(db, title="Pricing teardown", chunks=PRICING_CHUNKS, guest="Rafael Mendes")

    result = await RetrievalService(db, settings).retrieve(
        "How do we measure activation for new users reaching a first meaningful action?"
    )

    assert result.has_evidence
    assert result.chunks[0].title == "Activation deep dive"
    # Distances must be ordered, since the answer prompt relies on [S1] being the best match.
    assert result.chunks == sorted(result.chunks, key=lambda chunk: chunk.distance)
    assert result.chunks[0].marker == 1


async def test_retrieved_chunks_carry_full_source_metadata(db, settings):  # noqa: ANN001
    """Citations must be traceable back to the exact indexed chunk."""
    transcript = await seed_transcript(
        db,
        title="Activation deep dive",
        chunks=ACTIVATION_CHUNKS,
        episode="Episode 42",
        guest="Dana Okoye",
        source_url="https://example.com/activation",
        source_file="activation.txt",
    )

    result = await RetrievalService(db, settings).retrieve("activation first meaningful action metric")
    chunk = result.chunks[0]

    assert chunk.transcript_id == str(transcript.id)
    assert (chunk.title, chunk.episode, chunk.guest) == ("Activation deep dive", "Episode 42", "Dana Okoye")
    assert chunk.source_url == "https://example.com/activation"
    assert chunk.source_file == "activation.txt"
    assert chunk.chunk_index >= 0
    assert chunk.content in ACTIVATION_CHUNKS


async def test_absent_metadata_stays_none_and_is_never_invented(db, settings):  # noqa: ANN001
    await seed_transcript(db, title="Untitled recording", chunks=ACTIVATION_CHUNKS)

    result = await RetrievalService(db, settings).retrieve("activation metric first meaningful action")

    assert result.chunks[0].guest is None
    assert result.chunks[0].source_url is None
    assert result.chunks[0].episode is None


async def test_irrelevant_question_returns_no_evidence(db, settings):  # noqa: ANN001
    """The relevance threshold is what makes the honest refusal deterministic."""
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)

    result = await RetrievalService(db, settings).retrieve(
        "What is the best sourdough hydration ratio for a home oven?"
    )

    assert not result.has_evidence
    assert result.chunks == []
    assert result.knowledge_base_empty is False


async def test_empty_knowledge_base_is_reported_distinctly(db, settings):  # noqa: ANN001
    result = await RetrievalService(db, settings).retrieve("How do I improve activation?")

    assert not result.has_evidence
    assert result.knowledge_base_empty is True


async def test_per_episode_cap_diversifies_sources(db, settings):  # noqa: ANN001
    """One verbose episode must not crowd out every other source."""
    settings.retrieval_max_chunks_per_episode = 1
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 3)

    result = await RetrievalService(db, settings).retrieve("activation first meaningful action metric")

    assert len(result.chunks) == 1


async def test_follow_up_query_inherits_the_previous_subject(db, settings):  # noqa: ANN001
    """"What about for B2B SaaS?" has no retrievable terms without conversation context."""
    service = RetrievalService(db, settings)

    standalone = service.build_query("What about for B2B SaaS?", [])
    contextual = service.build_query("What about for B2B SaaS?", ["How do I improve activation?"])

    assert standalone == "What about for B2B SaaS?"
    assert "activation" in contextual
    assert "B2B SaaS" in contextual


async def test_long_question_is_not_diluted_by_history(db, settings):  # noqa: ANN001
    service = RetrievalService(db, settings)
    question = "How should a B2B SaaS team instrument activation to find the first meaningful action for new accounts?"

    assert service.build_query(question, ["something about pricing"]) == question


async def test_evidence_block_numbers_sources_for_citation(db, settings):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS, guest="Dana Okoye")

    result = await RetrievalService(db, settings).retrieve("activation metric first meaningful action")
    block = result.evidence_block()

    assert "[S1]" in block
    assert "Activation deep dive" in block
    assert "guest: Dana Okoye" in block
    assert result.chunks[0].content in block


async def test_context_budget_limits_prompt_size(db, settings):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 4)
    settings.retrieval_max_chunks_per_episode = 10

    result = await RetrievalService(db, settings).retrieve(
        "activation first meaningful action metric", context_char_budget=400
    )

    # At least one chunk always survives so a tiny budget cannot cause a false refusal.
    assert len(result.chunks) >= 1
    assert sum(len(chunk.content) for chunk in result.chunks[1:]) <= 400
