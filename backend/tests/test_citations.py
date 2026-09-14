"""Citation marker verification and speaker-attribution checks."""

from __future__ import annotations

from app.agent.citations import apply_citations, chunk_supports_person
from app.rag.retrieval import RetrievedChunk


def _chunk(
    *,
    rank: int,
    content: str,
    speaker: str | None,
    guest: str | None,
    title: str = "5 questions to ask when your product stops growing",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{rank}",
        transcript_id="transcript-1",
        content=content,
        distance=0.2,
        rank=rank,
        chunk_index=rank,
        speaker=speaker,
        title=title,
        episode=None,
        guest=guest,
        source_url=None,
        source_file="jason-cohen.md",
    )


def test_host_cannot_be_credited_for_a_guest_excerpt():
    """The live failure: a valid [S4] marker on Jason Cohen's chunk, credited to Lenny."""
    chunks = [
        _chunk(
            rank=0,
            speaker="Jason Cohen",
            guest="Jason Cohen",
            content="Jason Cohen: When your product stops growing, ask whether customers are leaving.",
        ),
        _chunk(
            rank=3,
            speaker="Jason Cohen",
            guest="Jason Cohen",
            content="Jason Cohen: The next step is pricing and positioning.",
        ),
    ]
    text = (
        "When a product stops growing, Jason Cohen says to ask whether customers are leaving [S1]. "
        "The next step is to consider pricing and positioning, as mentioned by Lenny Rachitsky in [S4]."
    )

    cleaned, cited, dropped = apply_citations(text, chunks)

    assert "Lenny Rachitsky" not in cleaned
    assert "as mentioned by" not in cleaned
    assert "Jason Cohen" in cleaned
    assert "[S1]" in cleaned
    assert "[S4]" not in cleaned
    assert cited == {1}
    assert dropped == set()


def test_matching_guest_attribution_is_kept():
    chunk = _chunk(
        rank=0,
        speaker="Jason Cohen",
        guest="Jason Cohen",
        content="Jason Cohen: The next step is pricing and positioning.",
    )
    text = "Jason Cohen says the next step is pricing and positioning [S1]."

    cleaned, cited, dropped = apply_citations(text, [chunk])

    assert cleaned == text
    assert cited == {1}
    assert dropped == set()


def test_mixed_excerpt_cannot_credit_the_host_for_the_guest_point():
    chunk = _chunk(
        rank=0,
        speaker=None,
        guest="Jason Cohen",
        content=(
            "Lenny Rachitsky: Step two is pricing, positioning.\n"
            "Jason Cohen: Your prices are way too low because you just guessed."
        ),
    )
    text = "The next step is to consider pricing and positioning, as mentioned by Lenny Rachitsky in [S1]."

    cleaned, cited, _dropped = apply_citations(text, [chunk])

    assert cleaned == ""
    assert cited == set()
    assert chunk_supports_person(chunk, "Lenny Rachitsky") is False
    assert chunk_supports_person(chunk, "Jason Cohen") is True


def test_host_only_excerpt_can_be_attributed_to_the_host():
    chunk = _chunk(
        rank=0,
        speaker="Lenny Rachitsky",
        guest="Jason Cohen",
        content="Lenny Rachitsky: Step two is pricing, positioning.",
    )
    text = "Lenny Rachitsky says step two is pricing and positioning [S1]."

    cleaned, cited, _dropped = apply_citations(text, [chunk])

    assert "Lenny Rachitsky" in cleaned
    assert "[S1]" in cleaned
    assert cited == {1}


def test_guest_cannot_be_credited_for_a_host_only_excerpt():
    chunk = _chunk(
        rank=0,
        speaker="Lenny Rachitsky",
        guest="Jason Cohen",
        content="Lenny Rachitsky: What comes next?",
    )
    text = "Jason Cohen says the next question is what comes next [S1]."

    cleaned, cited, _dropped = apply_citations(text, [chunk])

    assert cleaned == ""
    assert cited == set()


def test_invalid_markers_are_still_stripped():
    chunk = _chunk(
        rank=0,
        speaker="Jason Cohen",
        guest="Jason Cohen",
        content="Jason Cohen: Ask whether customers are leaving.",
    )
    text = "Jason Cohen says ask whether customers are leaving [S1] and retention triples [S9]."

    cleaned, cited, dropped = apply_citations(text, [chunk])

    assert "[S9]" not in cleaned
    assert "[S1]" in cleaned
    assert cited == {1}
    assert dropped == {9}


def test_uncited_named_attribution_is_removed():
    chunk = _chunk(
        rank=0,
        speaker="Jason Cohen",
        guest="Jason Cohen",
        content="Jason Cohen: Ask whether customers are leaving.",
    )
    text = "Jason Cohen also recommends you should check in with yourself annually."

    cleaned, cited, _dropped = apply_citations(text, [chunk])

    assert cleaned == ""
    assert cited == set()


def _elena(*, rank: int) -> RetrievedChunk:
    return _chunk(
        rank=rank,
        speaker="Elena Verna",
        guest="Elena Verna 4.0",
        title="Elena Verna 4.0",
        content="Elena Verna: Activation is the moment a new user reaches value.",
    )


def _amol(*, rank: int) -> RetrievedChunk:
    return _chunk(
        rank=rank,
        speaker="Amol Avasare",
        guest="Amol Avasare",
        title="Anthropic's $1B to $19B growth run | Amol Avasare",
        content="Amol Avasare: We hired people who had already done the job.",
    )


def _alexander(*, rank: int) -> RetrievedChunk:
    return _chunk(
        rank=rank,
        speaker="Alexander Embiricos",
        guest="Alexander Embiricos",
        title="Alexander Embiricos",
        content="Alexander Embiricos: Codex is a coding agent that writes production code.",
    )


def test_elena_cannot_be_cited_with_amol_marker():
    """Live failure: 'At Lovable, Elena Verna... [S3]' when S3 is Amol."""
    chunks = [_elena(rank=0), _elena(rank=1), _amol(rank=2)]
    text = "At Lovable, Elena Verna shortened time-to-value for new users [S3]."

    cleaned, cited, _dropped = apply_citations(text, chunks)

    assert "Elena Verna" not in cleaned
    assert "[S3]" not in cleaned
    assert cited == set()


def test_amol_cannot_be_cited_with_elena_marker():
    """Live failure: 'Amol Avasare from Anthropic... [S1]' when S1 is Elena."""
    chunks = [_elena(rank=0), _elena(rank=1), _amol(rank=2)]
    text = "Amol Avasare from Anthropic hired operators who had done the job before [S1]."

    cleaned, cited, _dropped = apply_citations(text, chunks)

    assert "Amol Avasare" not in cleaned
    assert "[S1]" not in cleaned
    assert cited == set()


def test_alexander_cannot_be_cited_with_elena_marker():
    """Live failure: 'Alexander Embiricos from Codex... [S2]' when S2 is Elena."""
    chunks = [_elena(rank=0), _elena(rank=1), _amol(rank=2), _alexander(rank=3)]
    text = "Alexander Embiricos from Codex raised the bar for what activation looks like [S2]."

    cleaned, cited, _dropped = apply_citations(text, chunks)

    assert "Alexander Embiricos" not in cleaned
    assert "[S2]" not in cleaned
    assert cited == set()


def test_valid_elena_from_company_citation_is_kept():
    chunks = [_elena(rank=0), _amol(rank=2)]
    text = "At Lovable, Elena Verna shortened time-to-value for new users [S1]."

    cleaned, cited, dropped = apply_citations(text, chunks)

    assert cleaned == text
    assert cited == {1}
    assert dropped == set()


def test_valid_amol_from_company_citation_is_kept():
    chunks = [_elena(rank=0), _amol(rank=2)]
    text = "Amol Avasare from Anthropic hired operators who had done the job before [S3]."

    cleaned, cited, dropped = apply_citations(text, chunks)

    assert cleaned == text
    assert cited == {3}
    assert dropped == set()


def test_possessive_known_name_with_wrong_marker_is_stripped():
    chunks = [_elena(rank=0), _amol(rank=2)]
    text = "Elena Verna's approach is to measure time-to-value [S3]."

    cleaned, cited, _dropped = apply_citations(text, chunks)

    assert "Elena Verna" not in cleaned
    assert cited == set()


def test_possessive_known_name_with_matching_marker_is_kept():
    chunks = [_elena(rank=0), _amol(rank=2)]
    text = "Elena Verna's approach is to measure time-to-value [S1]."

    cleaned, cited, dropped = apply_citations(text, chunks)

    assert cleaned == text
    assert cited == {1}
    assert dropped == set()


def test_company_name_is_not_treated_as_a_person():
    chunks = [_elena(rank=0), _amol(rank=2)]
    text = "Anthropic grew from one billion to nineteen billion [S3]."

    cleaned, cited, dropped = apply_citations(text, chunks)

    assert cleaned == text
    assert cited == {3}
    assert dropped == set()


def test_unsupported_percentage_is_stripped_even_when_guest_matches():
    chunk = _chunk(
        rank=0,
        speaker="Elena Verna",
        guest="Elena Verna 4.0",
        content="Elena Verna: Activation is the moment a new user reaches value.",
    )
    text = "Elena Verna notes that activation improved 47% after the onboarding cut [S1]."

    cleaned, cited, _dropped = apply_citations(text, [chunk])

    assert "47%" not in cleaned
    assert "Elena Verna" not in cleaned
    assert cited == set()


def test_supported_percentage_is_kept_when_guest_matches():
    chunk = _chunk(
        rank=0,
        speaker="Elena Verna",
        guest="Elena Verna 4.0",
        content="Elena Verna: Activation rose 47% after we cut onboarding.",
    )
    text = "Elena Verna notes that activation rose 47% after the onboarding cut [S1]."

    cleaned, cited, dropped = apply_citations(text, [chunk])

    assert cleaned == text
    assert cited == {1}
    assert dropped == set()


def test_uncited_percentage_is_stripped():
    chunk = _chunk(
        rank=0,
        speaker="Elena Verna",
        guest="Elena Verna 4.0",
        content="Elena Verna: Activation rose 47% after we cut onboarding.",
    )
    text = "Activation improved 47% overnight."

    cleaned, cited, _dropped = apply_citations(text, [chunk])

    assert cleaned == ""
    assert cited == set()
