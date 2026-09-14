"""Transcript loading, cleaning, chunking and idempotent indexing.

Fixture transcripts are written for this suite with invented speakers; they are not
real podcast content.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.core.errors import IngestionError
from app.models.transcript import Transcript, TranscriptChunk
from app.rag.chunking import chunk_transcript, chunk_turns, clean_transcript, split_turns
from app.rag.ingestion import IngestionService
from app.rag.loader import load_transcripts

SAMPLE = """\
Interviewer: Welcome to the show. Today we are talking about activation.
Guest Speaker: Thanks for having me. Activation is where most teams lose their users.
Interviewer: What should teams measure first?
Guest Speaker: Find the first meaningful action, then measure how many new users reach it.
"""


# ------------------------------------------------------------------------ cleaning
def test_vtt_cues_and_timestamps_are_removed():
    raw = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
Interviewer: Welcome to the show.

2
00:00:04.500 --> 00:00:08.000
Guest Speaker: Activation matters.
"""

    cleaned = clean_transcript(raw)

    assert "WEBVTT" not in cleaned
    assert "-->" not in cleaned
    assert "00:00:01" not in cleaned
    assert "Interviewer: Welcome to the show." in cleaned
    assert "Guest Speaker: Activation matters." in cleaned


def test_srt_cue_numbers_are_removed():
    cleaned = clean_transcript("1\n00:00:01,000 --> 00:00:04,000\nActivation matters.\n")

    assert cleaned == "Activation matters."


def test_filler_annotations_are_removed_but_speech_is_kept():
    cleaned = clean_transcript("Guest Speaker: We shipped it [laughs] and it worked [inaudible 00:12].")

    assert "[laughs]" not in cleaned
    assert "[inaudible" not in cleaned
    assert "We shipped it" in cleaned and "and it worked" in cleaned


def test_numbers_inside_sentences_are_not_mistaken_for_timestamps():
    cleaned = clean_transcript("Guest Speaker: Activation rose from 20:80 split to a 40 percent rate.")

    assert "40 percent" in cleaned


# ------------------------------------------------------------------------ chunking
def test_speaker_turns_are_detected_with_offsets():
    turns = split_turns(clean_transcript(SAMPLE))

    assert [turn.speaker for turn in turns] == ["Interviewer", "Guest Speaker", "Interviewer", "Guest Speaker"]
    assert all(turn.char_end >= turn.char_start for turn in turns)
    assert "first meaningful action" in turns[-1].text


def test_chunks_carry_offsets_and_token_estimates():
    _, chunks = chunk_transcript(SAMPLE, chunk_size=200, overlap=40)

    assert chunks
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert chunk.content.strip()
        assert chunk.char_end >= chunk.char_start
        assert chunk.token_estimate > 0


def test_chunks_never_exceed_the_configured_size():
    long_text = "Guest Speaker: " + " ".join(f"sentence number {index}." for index in range(300))
    _, chunks = chunk_transcript(long_text, chunk_size=500, overlap=100)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.content) <= 500, "an oversized chunk would blow the prompt budget"


def test_consecutive_chunks_overlap_so_boundary_claims_stay_whole():
    turns = "\n".join(f"Speaker {index % 2}: This is claim number {index} about activation." for index in range(60))
    _, chunks = chunk_transcript(turns, chunk_size=400, overlap=120)

    assert len(chunks) > 1
    overlapping = 0
    for earlier, later in zip(chunks, chunks[1:], strict=False):
        tail = earlier.content.strip().split("\n")[-1]
        if tail and tail in later.content:
            overlapping += 1
    assert overlapping >= 1, "at least one boundary turn should be replayed into the next chunk"


def test_speaker_is_recorded_only_when_a_chunk_has_one_voice():
    _, single = chunk_transcript("Guest Speaker: " + "word " * 50, chunk_size=2000, overlap=0)
    _, mixed = chunk_transcript(SAMPLE, chunk_size=5000, overlap=0)

    assert single[0].speaker == "Guest Speaker"
    assert mixed[0].speaker is None, "a multi-speaker chunk must not be attributed to one person"


def test_a_monologue_longer_than_one_chunk_is_split_on_sentences():
    monologue = "Guest Speaker: " + " ".join(f"This is sentence {index}." for index in range(120))
    _, chunks = chunk_transcript(monologue, chunk_size=400, overlap=0)

    assert len(chunks) > 1
    assert all(chunk.content.strip() for chunk in chunks)


def test_empty_transcript_produces_no_chunks():
    assert chunk_turns(split_turns(clean_transcript("\n\n   \n"))) == []


# -------------------------------------------------------------------------- loader
def test_front_matter_metadata_is_read(tmp_path):  # noqa: ANN001
    (tmp_path / "ep1.md").write_text(
        "---\ntitle: Activation Deep Dive\nepisode: Episode 42\nguest: Dana Okoye\n"
        "source_url: https://example.com/ep42\n---\n" + SAMPLE,
        encoding="utf-8",
    )

    loaded = load_transcripts(tmp_path)

    assert len(loaded) == 1
    assert loaded[0].title == "Activation Deep Dive"
    assert loaded[0].episode == "Episode 42"
    assert loaded[0].guest == "Dana Okoye"
    assert loaded[0].source_url == "https://example.com/ep42"
    assert "---" not in loaded[0].raw_text


def test_missing_metadata_is_left_none_and_never_invented(tmp_path):  # noqa: ANN001
    (tmp_path / "some_episode_name.txt").write_text(SAMPLE, encoding="utf-8")

    loaded = load_transcripts(tmp_path)

    assert loaded[0].guest is None
    assert loaded[0].source_url is None
    assert loaded[0].episode is None
    # Only the title falls back, and only to the filename — a visible, checkable source.
    assert loaded[0].title == "Some Episode Name"
    assert any("no source_url" in warning for warning in loaded[0].warnings)


def test_sidecar_metadata_file_is_applied(tmp_path):  # noqa: ANN001
    (tmp_path / "ep2.txt").write_text(SAMPLE, encoding="utf-8")
    (tmp_path / "metadata.json").write_text(
        json.dumps({"ep2.txt": {"title": "Pricing Teardown", "guest": "Rafael Mendes"}}), encoding="utf-8"
    )

    loaded = load_transcripts(tmp_path)

    assert loaded[0].title == "Pricing Teardown"
    assert loaded[0].guest == "Rafael Mendes"


def test_front_matter_wins_over_the_sidecar(tmp_path):  # noqa: ANN001
    (tmp_path / "ep3.md").write_text("---\ntitle: From Front Matter\n---\n" + SAMPLE, encoding="utf-8")
    (tmp_path / "metadata.json").write_text(
        json.dumps({"ep3.md": {"title": "From Sidecar", "guest": "Dana Okoye"}}), encoding="utf-8"
    )

    loaded = load_transcripts(tmp_path)

    assert loaded[0].title == "From Front Matter"
    assert loaded[0].guest == "Dana Okoye", "non-conflicting sidecar fields still apply"


def test_documentation_alongside_the_corpus_is_not_indexed(tmp_path):  # noqa: ANN001
    """Both transcript directories ship a README explaining what to put there.

    Indexing those would put our own instructions into the knowledge base and let the
    assistant cite "Readme" as if it were an episode.
    """
    (tmp_path / "README.md").write_text("Put transcript files here. " + SAMPLE, encoding="utf-8")
    (tmp_path / "LICENSE").write_text("MIT", encoding="utf-8")
    (tmp_path / "ep4.txt").write_text(SAMPLE, encoding="utf-8")

    loaded = load_transcripts(tmp_path)

    assert [item.source_file for item in loaded] == ["ep4.txt"]


def test_json_transcripts_are_supported(tmp_path):  # noqa: ANN001
    (tmp_path / "eps.json").write_text(
        json.dumps(
            [
                {"title": "One", "guest": "A", "transcript": SAMPLE},
                {"title": "Two", "guest": "B", "text": SAMPLE},
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_transcripts(tmp_path)

    assert [item.title for item in loaded] == ["One", "Two"]
    # Distinct source_file keys keep multi-episode files idempotent.
    assert len({item.source_file for item in loaded}) == 2


def test_missing_directory_fails_loudly(tmp_path):  # noqa: ANN001
    with pytest.raises(IngestionError) as exc_info:
        load_transcripts(tmp_path / "does-not-exist")

    assert "does not exist" in exc_info.value.message
    assert "docs/transcripts.md" in (exc_info.value.remedy or "")


def test_malformed_json_is_reported_with_the_filename(tmp_path):  # noqa: ANN001
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(IngestionError) as exc_info:
        load_transcripts(tmp_path)

    assert "broken.json" in exc_info.value.message


def test_unsupported_file_types_are_ignored(tmp_path):  # noqa: ANN001
    (tmp_path / "notes.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "ep.txt").write_text(SAMPLE, encoding="utf-8")

    assert [item.source_file for item in load_transcripts(tmp_path)] == ["ep.txt"]


# ----------------------------------------------------------------------- indexing
async def test_ingestion_indexes_chunks_with_metadata(db, settings, tmp_path):  # noqa: ANN001
    (tmp_path / "ep.md").write_text(
        "---\ntitle: Activation Deep Dive\nguest: Dana Okoye\nsource_url: https://example.com/x\n---\n" + SAMPLE * 3,
        encoding="utf-8",
    )

    report = await IngestionService(db, settings).ingest_directory(str(tmp_path))

    assert report.indexed == 1
    assert report.chunks_written > 0
    assert report.failures == []

    transcript = await db.scalar(select(Transcript))
    assert transcript.title == "Activation Deep Dive"
    assert transcript.guest == "Dana Okoye"
    assert transcript.source_url == "https://example.com/x"
    assert transcript.chunk_count == report.chunks_written

    chunks = int(await db.scalar(select(func.count()).select_from(TranscriptChunk)))
    assert chunks == report.chunks_written


async def test_reingesting_unchanged_files_is_a_no_op(db, settings, tmp_path):  # noqa: ANN001
    """Adding one transcript must not re-embed the whole corpus."""
    (tmp_path / "ep.txt").write_text(SAMPLE * 3, encoding="utf-8")
    service = IngestionService(db, settings)

    first = await service.ingest_directory(str(tmp_path))
    second = await service.ingest_directory(str(tmp_path))

    assert first.indexed == 1
    assert second.indexed == 0
    assert second.skipped == 1
    assert second.chunks_written == 0
    assert int(await db.scalar(select(func.count()).select_from(TranscriptChunk))) == first.chunks_written


async def test_changed_file_replaces_its_chunks(db, settings, tmp_path):  # noqa: ANN001
    path = tmp_path / "ep.txt"
    path.write_text(SAMPLE * 3, encoding="utf-8")
    service = IngestionService(db, settings)
    await service.ingest_directory(str(tmp_path))

    path.write_text("Guest Speaker: A completely rewritten transcript about pricing tiers.", encoding="utf-8")
    report = await service.ingest_directory(str(tmp_path))

    assert report.updated == 1
    assert report.indexed == 0
    assert int(await db.scalar(select(func.count()).select_from(Transcript))) == 1
    # Stale chunks must be gone, not merged with the new ones.
    remaining = (await db.execute(select(TranscriptChunk.content))).scalars().all()
    assert all("pricing tiers" in content for content in remaining)


async def test_force_reindexes_unchanged_files(db, settings, tmp_path):  # noqa: ANN001
    (tmp_path / "ep.txt").write_text(SAMPLE * 3, encoding="utf-8")
    service = IngestionService(db, settings)
    await service.ingest_directory(str(tmp_path))

    report = await service.ingest_directory(str(tmp_path), force=True)

    assert report.updated == 1
    assert report.skipped == 0


async def test_one_bad_file_does_not_abandon_the_rest(db, settings, tmp_path):  # noqa: ANN001
    (tmp_path / "good.txt").write_text(SAMPLE * 3, encoding="utf-8")
    # Only timestamps: nothing survives cleaning, so this file must fail on its own.
    (tmp_path / "empty.vtt").write_text("WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\n\n", encoding="utf-8")

    report = await IngestionService(db, settings).ingest_directory(str(tmp_path))

    assert report.indexed == 1
    assert len(report.failures) == 1
    assert "empty.vtt" in report.failures[0][0]
    assert "no usable text" in report.failures[0][1]


async def test_empty_directory_reports_nothing_indexed(db, settings, tmp_path):  # noqa: ANN001
    report = await IngestionService(db, settings).ingest_directory(str(tmp_path))

    assert report.indexed == 0 and report.chunks_written == 0
    assert "indexed 0 new" in report.summary()
