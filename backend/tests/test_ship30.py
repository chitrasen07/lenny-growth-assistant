"""Ship 30 for 30 essay skill: length control, grounding and refusal."""

from __future__ import annotations

from app.agent.prompts import REFUSAL_MESSAGE
from app.agent.skills.ship30 import (
    Ship30EssaySkill,
    constrain_h2_sections,
    count_h2_sections,
    count_words,
    drop_incomplete_tail,
    topic_focus,
)
from app.agent.types import SkillContext
from app.rag.retrieval import RetrievalService
from tests.conftest import ACTIVATION_CHUNKS, seed_transcript


_TITLE = "Activation Is A Promise"  # 4 words
_HEADING = "The hook"  # 2 words
_OVERHEAD_WORDS = len(_TITLE.split()) + len(_HEADING.split())


def _essay(words: int) -> str:
    """Markdown essay whose ``count_words`` is exactly ``words``."""
    body = " ".join(f"word{index}" for index in range(words - _OVERHEAD_WORDS))
    return f"# {_TITLE}\n\n## {_HEADING}\n\n{body} [S1]"


def test_essay_helper_produces_the_requested_word_count():
    """Guards the helper the length assertions below depend on."""
    for target in (200, 1000, 1250):
        assert count_words(_essay(target)) == target


def test_word_count_ignores_markdown_syntax_and_citation_markers():
    markdown = "# Title\n\n## Section\n\nOne two three [S1] four **five** [S2, S3].\n\n- bullet six\n"

    # Prose words only: Title, Section, One, two, three, four, five, bullet, six.
    assert count_words(markdown) == 9


def test_word_count_excludes_code_blocks():
    assert count_words("Real words here\n\n```\nignored code tokens\n```\n") == 3


async def test_essay_is_generated_with_citations_and_metadata(db, settings, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2, guest="Dana Okoye")
    provider.queue(_essay(settings.essay_target_words))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="improving activation")

    assert result.refused is False
    assert result.meta["word_count"] == settings.essay_target_words
    assert result.meta["within_tolerance"] is True
    assert result.meta["attempts"] == 1
    assert result.meta["title"] == _TITLE
    assert result.meta["cited_markers"] == [1]
    assert result.retrieval is not None and result.retrieval.chunks


async def test_essay_targets_roughly_1250_words(db, settings, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2)
    provider.queue(_essay(1250))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    words = count_words(result.text)
    assert 1250 * 0.85 <= words <= 1250 * 1.15


async def test_short_draft_triggers_one_revision_pass(db, settings, provider):  # noqa: ANN001
    """Local models routinely undershoot a long target; one bounded retry recovers it."""
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2)
    provider.queue(_essay(300), _essay(1240))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert result.meta["attempts"] == 2
    assert result.meta["within_tolerance"] is True
    assert count_words(result.text) == 1240
    # The revision prompt must state the actual and target counts.
    revision_prompt = provider.last_prompt
    assert "300 words" in revision_prompt
    assert "Expand" in revision_prompt


async def test_revision_is_discarded_when_it_moves_further_from_target(db, settings, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2)
    # 1000 is still below the 1,062-word floor, so a second continue is attempted and
    # also discarded when it is worse than the kept draft.
    provider.queue(_essay(1000), _essay(200), _essay(150))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert count_words(result.text) == 1000, "the closer draft should be kept"
    assert result.meta["attempts"] == 3


async def test_still_short_draft_gets_a_second_continue(db, settings, provider):  # noqa: ANN001
    """A 700-word first draft should be expanded from evidence, not left undersized."""
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2)
    provider.queue(_essay(300), _essay(800), _essay(1240))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert result.meta["attempts"] == 3
    assert result.meta["within_tolerance"] is True
    assert count_words(result.text) == 1240


async def test_essay_refuses_when_evidence_is_too_thin(db, settings, provider):  # noqa: ANN001
    """One matching excerpt cannot support 1,250 grounded words."""
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS[:1])
    provider.queue(_essay(1250))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert result.refused is True
    assert REFUSAL_MESSAGE in result.text
    assert result.meta["refusal_reason"] == "insufficient_evidence"
    assert provider.calls == [], "no generation should happen without enough evidence"


async def test_essay_refuses_on_an_empty_knowledge_base(db, settings, provider):  # noqa: ANN001
    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))

    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert result.refused is True
    assert "No transcripts have been ingested" in result.text


async def test_essay_prompt_encodes_the_writing_principles(db, settings, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2)
    provider.queue(_essay(1250))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    await Ship30EssaySkill(settings).run(context, topic="activation")

    prompt = provider.last_prompt
    assert "hook" in prompt.lower()
    assert "skimmable" in prompt.lower()
    assert "4-6" in prompt
    assert "per guest" in prompt.lower()
    assert "repeat" in prompt.lower()
    assert "1250 words" in prompt or "1250" in prompt
    assert "EVIDENCE" in prompt
    # Anti-fabrication instruction must be present in the essay prompt too.
    assert "invent" in prompt.lower()


async def test_hallucinated_markers_are_stripped_from_the_essay(db, settings, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2)
    body = " ".join(f"word{index}" for index in range(1250))
    provider.queue(f"# Title\n\n{body} [S1] and also [S99].")

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert "[S99]" not in result.text
    assert 99 in result.meta["dropped_markers"]


async def test_empty_topic_asks_for_clarification(db, settings, provider):  # noqa: ANN001
    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))

    result = await Ship30EssaySkill(settings).run(context, topic="   ")

    assert result.refused is True
    assert provider.calls == []


def test_topic_focus_strips_essay_boilerplate():
    assert topic_focus("Write a Ship 30 for 30 essay about activation.") == "activation"
    assert topic_focus("Write a Ship 30 for 30 essay about activation") == "activation"
    assert topic_focus("improving activation") == "improving activation"
    assert topic_focus("activation") == "activation"


async def test_essay_retrieves_on_the_focused_topic_not_the_boilerplate(db, settings, provider):  # noqa: ANN001
    """'Write a Ship 30 essay about activation' must not pull loosely related writing episodes."""
    token_chunks = [
        "Sherwin Wu: Token Maxing is dumping every document into the prompt until the window fills. "
        "We measured token spend per request and the extra tokens did not improve quality.",
        "Sherwin Wu: Token Maxing also increases latency. The team capped retrieved tokens and quality held.",
    ]
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2, guest="Dana Okoye")
    await seed_transcript(db, title="Token Maxing", chunks=token_chunks * 2, guest="Sherwin Wu")
    provider.queue(_essay(1250))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(
        context, topic="Write a Ship 30 for 30 essay about activation."
    )

    assert result.refused is False
    assert result.retrieval is not None
    assert result.retrieval.query == "activation"
    evidence = result.retrieval.evidence_block()
    assert "activation" in evidence.lower()
    assert "Token Maxing" not in evidence
    write_prompt = "\n".join(message.content for message in provider.calls[0])
    assert "TOPIC: activation" in write_prompt
    assert "loosely related" in write_prompt.lower() or "directly support this topic" in write_prompt


async def test_cited_markers_are_traceable_to_retrieved_chunks(db, settings, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2)
    provider.queue(_essay(1250))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    retrieved = {chunk.marker for chunk in result.retrieval.chunks}
    cited = set(result.meta["cited_markers"])
    assert cited
    assert cited <= retrieved
    for marker in cited:
        assert f"[S{marker}]" in result.text


async def test_unsupported_host_attribution_is_stripped_from_the_essay(db, settings, provider):  # noqa: ANN001
    await seed_transcript(
        db,
        title="Activation deep dive",
        chunks=ACTIVATION_CHUNKS * 2,
        guest="Dana Okoye",
        speakers=["Dana Okoye"] * 4,
    )
    filler = " ".join(f"word{index}" for index in range(1240))
    provider.queue(
        f"# Title\n\n{filler}. Lenny Rachitsky said activation is a promise you keep [S1]."
    )

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert result.refused is False
    assert "Lenny Rachitsky" not in result.text


def test_incomplete_trailing_fragment_is_dropped():
    text = "# Title\n\nActivation is a promise you keep. [S1]\n\nit's hard to measure"
    cleaned = drop_incomplete_tail(text)
    assert "it's hard to measure" not in cleaned
    assert "promise you keep" in cleaned


def test_complete_short_takeaway_is_kept():
    text = "# Title\n\nActivation is a promise you keep. [S1]\n\nStart this week."
    assert drop_incomplete_tail(text) == text


async def test_essay_strips_incomplete_trailing_fragment(db, settings, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2)
    provider.queue(_essay(1250).rstrip() + "\n\nit's hard to measure")

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert "it's hard to measure" not in result.text
    assert count_words(result.text) == 1250


async def test_unsupported_topic_still_refuses(db, settings, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2)
    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))

    result = await Ship30EssaySkill(settings).run(
        context, topic="Write a Ship 30 for 30 essay about sourdough hydration."
    )

    assert result.refused is True
    assert REFUSAL_MESSAGE in result.text
    assert result.meta["refusal_reason"] == "insufficient_evidence"
    assert provider.calls == []


_HOST_SENTENCE = "Lenny Rachitsky said activation is a promise you keep [S1]."


def _essay_that_shrinks_after_cleanup(valid_words: int = 1000, host_sentences: int = 20) -> str:
    """In-range draft whose citation cleanup drops it below the 1,062-word floor."""
    return _essay(valid_words) + "\n\n" + " ".join([_HOST_SENTENCE] * host_sentences)


async def test_cleanup_shortfall_triggers_a_continuation(db, settings, provider):  # noqa: ANN001
    await seed_transcript(
        db,
        title="Activation deep dive",
        chunks=ACTIVATION_CHUNKS * 2,
        guest="Dana Okoye",
        speakers=["Dana Okoye"] * 4,
    )
    padded = _essay_that_shrinks_after_cleanup()
    assert count_words(padded) >= int(settings.essay_target_words * (1 - settings.essay_word_tolerance))
    provider.queue(padded, _essay(1240))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert result.meta["attempts"] == 2
    assert len(provider.calls) == 2
    assert result.meta["within_tolerance"] is True
    assert count_words(result.text) == 1240
    assert "Lenny Rachitsky" not in result.text
    assert "Expand" in provider.last_prompt
    assert "1000 words" in provider.last_prompt


async def test_in_range_final_essay_does_not_continue(db, settings, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2)
    provider.queue(_essay(1250), _essay(1300))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert result.meta["attempts"] == 1
    assert len(provider.calls) == 1
    assert result.meta["within_tolerance"] is True
    assert count_words(result.text) == 1250


async def test_word_count_metadata_matches_final_cleaned_essay(db, settings, provider):  # noqa: ANN001
    await seed_transcript(
        db,
        title="Activation deep dive",
        chunks=ACTIVATION_CHUNKS * 2,
        guest="Dana Okoye",
        speakers=["Dana Okoye"] * 4,
    )
    provider.queue(_essay_that_shrinks_after_cleanup(), _essay(1240))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert result.meta["word_count"] == count_words(result.text) == 1240


async def test_at_most_three_generations(db, settings, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2)
    provider.queue(_essay(300), _essay(400), _essay(500), _essay(1240))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert len(provider.calls) == 3
    assert result.meta["attempts"] == 3
    assert count_words(result.text) == 500
    assert result.meta["word_count"] == 500
    assert result.meta["within_tolerance"] is False


async def test_citation_validation_runs_after_cleanup_continuation(db, settings, provider):  # noqa: ANN001
    await seed_transcript(
        db,
        title="Activation deep dive",
        chunks=ACTIVATION_CHUNKS * 2,
        guest="Dana Okoye",
        speakers=["Dana Okoye"] * 4,
    )
    body = " ".join(f"word{index}" for index in range(1250))
    provider.queue(
        _essay_that_shrinks_after_cleanup(),
        f"# Title\n\n{body} [S1] and also [S99].",
    )

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert result.meta["attempts"] == 2
    assert "[S99]" not in result.text
    assert "[S1]" in result.text
    assert 99 in result.meta["dropped_markers"]
    assert result.meta["cited_markers"] == [1]
    assert result.meta["word_count"] == count_words(result.text)


def test_constrain_h2_demotes_extra_headings_without_deleting_prose():
    markdown = "# Title\n\n" + "\n\n".join(f"## Heading {index}\n\nParagraph {index} stays here." for index in range(8))
    cleaned = constrain_h2_sections(markdown)

    assert count_h2_sections(cleaned) == 6
    assert "## Heading 0" in cleaned
    assert "## Heading 5" in cleaned
    assert "## Heading 6" not in cleaned
    assert "**Heading 6**" in cleaned
    assert "Paragraph 7 stays here." in cleaned


async def test_essay_caps_h2_sections_at_six(db, settings, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2)
    heading_words = 3 * 8  # "Heading Number {i}"
    remaining = 1250 - len(_TITLE.split()) - heading_words
    body = " ".join(f"word{index}" for index in range(remaining))
    sections = [f"# {_TITLE}"]
    for index in range(8):
        heading = f"## Heading Number {index}"
        sections.append(f"{heading}\n\n{body} [S1]" if index == 0 else heading)
    essay = "\n\n".join(sections)
    assert count_words(essay) == 1250
    assert count_h2_sections(essay) == 8
    provider.queue(essay)

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert count_h2_sections(result.text) == 6
    assert "Heading Number 7" in result.text
    assert result.meta["word_count"] == count_words(result.text)
    assert result.meta["attempts"] == 1


async def test_off_topic_retrieved_chunks_are_not_used_as_evidence(db, settings, provider):  # noqa: ANN001
    talent_chunks = [
        "Adam Ward: Talent density is hiring people who raise the average of the room. "
        "Cursor ships because the team is dense, not because headcount grew.",
        "Adam Ward: Do not hire for headcount. Hire so every person raises talent density.",
    ]
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS * 2, guest="Dana Okoye")
    await seed_transcript(db, title="Adam Ward", chunks=talent_chunks * 2, guest="Adam Ward")
    provider.queue(_essay(1250))

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    evidence = result.retrieval.evidence_block()
    assert "activation" in evidence.lower()
    assert "Talent density" not in evidence
    assert "Adam Ward" not in evidence


async def test_unsupported_numeric_claim_is_stripped_when_guest_matches(db, settings, provider):  # noqa: ANN001
    await seed_transcript(
        db,
        title="Activation deep dive",
        chunks=ACTIVATION_CHUNKS * 2,
        guest="Dana Okoye",
        speakers=["Dana Okoye"] * 4,
    )
    filler = " ".join(f"word{index}" for index in range(1240))
    provider.queue(f"# Title\n\n{filler}. Dana Okoye notes that activation improved 47% [S1].")

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert "47%" not in result.text
    assert result.meta["word_count"] == count_words(result.text)


async def test_supported_numeric_claim_is_kept_when_guest_matches(db, settings, provider):  # noqa: ANN001
    chunks = [
        "Dana Okoye: Activation rose 47% after we removed four onboarding steps.",
        "Dana Okoye: Activation is the moment a new user reaches the outcome they signed up for.",
        "Dana Okoye: We measured activation as the percentage of signups completing a first meaningful action.",
        "Dana Okoye: That single activation metric moved retention more than acquisition spend.",
    ]
    await seed_transcript(db, title="Activation deep dive", chunks=chunks, guest="Dana Okoye", speakers=["Dana Okoye"] * 4)
    filler = " ".join(f"word{index}" for index in range(1240))
    provider.queue(f"# Title\n\n{filler}. Dana Okoye notes that activation rose 47% [S1].")

    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings))
    result = await Ship30EssaySkill(settings).run(context, topic="activation")

    assert "47%" in result.text
    assert "Dana Okoye" in result.text
    assert result.meta["word_count"] == count_words(result.text)
