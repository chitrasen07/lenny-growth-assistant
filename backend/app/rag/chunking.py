"""Transcript cleaning and chunking.

Chunks are built from speaker turns rather than a blind character window, because a
podcast answer loses its meaning when it is cut mid-sentence and attributed to whoever
happened to be speaking at the boundary. Each chunk keeps its character offsets so a
citation can be traced back to an exact span of the source file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: "Lenny Rachitsky:" / "GUEST:" / "[Lenny]" style speaker labels at line start.
_SPEAKER_PATTERN = re.compile(r"^\s*(?:\[(?P<bracket>[^\]\n]{1,60})\]|(?P<plain>[A-Z][\w.'\- ]{1,58}))\s*:\s*")
#: "00:12:34", "00:12:34.567 --> 00:12:39.000", "[00:12:34]"
_TIMESTAMP_PATTERN = re.compile(r"^\s*\[?\d{1,2}:\d{2}(?::\d{2})?([.,]\d{1,3})?\]?(\s*-->\s*\S+)?\s*$")
_INLINE_TIMESTAMP = re.compile(r"\[?\b\d{1,2}:\d{2}(?::\d{2})?([.,]\d{1,3})?\b\]?")
_CUE_NUMBER = re.compile(r"^\s*\d{1,5}\s*$")
_FILLER_PATTERN = re.compile(r"\[(?:inaudible|crosstalk|laughs?|laughter|music|applause)[^\]]*\]", re.IGNORECASE)


@dataclass(slots=True)
class Turn:
    speaker: str | None
    text: str
    char_start: int
    char_end: int


@dataclass(slots=True)
class Chunk:
    index: int
    content: str
    speaker: str | None
    char_start: int
    char_end: int
    token_estimate: int


def clean_transcript(raw: str) -> str:
    """Drop subtitle scaffolding and normalise whitespace, preserving speaker labels."""
    if raw.startswith("WEBVTT"):
        raw = raw.split("\n", 1)[-1]

    kept: list[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            kept.append("")
            continue
        if _TIMESTAMP_PATTERN.match(stripped) or _CUE_NUMBER.match(stripped):
            continue
        stripped = _FILLER_PATTERN.sub("", stripped)
        # Strip leading in-line timestamps but keep digits inside real sentences.
        stripped = _INLINE_TIMESTAMP.sub("", stripped, count=1) if _INLINE_TIMESTAMP.match(stripped) else stripped
        stripped = re.sub(r"[ \t]{2,}", " ", stripped).strip()
        if stripped:
            kept.append(stripped)

    text = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def split_turns(text: str) -> list[Turn]:
    """Split cleaned text into speaker turns, carrying offsets into ``text``."""
    turns: list[Turn] = []
    speaker: str | None = None
    buffer: list[str] = []
    start = 0
    cursor = 0

    def flush(end: int) -> None:
        if buffer:
            body = " ".join(buffer).strip()
            if body:
                turns.append(Turn(speaker, body, start, end))
        buffer.clear()

    for line in text.split("\n"):
        line_start = cursor
        cursor += len(line) + 1
        stripped = line.strip()
        if not stripped:
            continue
        match = _SPEAKER_PATTERN.match(stripped)
        if match:
            flush(line_start)
            speaker = (match.group("bracket") or match.group("plain") or "").strip() or None
            remainder = stripped[match.end() :].strip()
            start = line_start
            if remainder:
                buffer.append(remainder)
        else:
            if not buffer:
                start = line_start
            buffer.append(stripped)

    flush(len(text))
    if not turns and text.strip():
        return [Turn(None, text.strip(), 0, len(text))]
    return turns


def chunk_turns(turns: list[Turn], *, chunk_size: int = 1200, overlap: int = 200) -> list[Chunk]:
    """Pack turns into overlapping chunks, each at most ``chunk_size`` characters.

    Overlap is applied by replaying trailing turns into the next chunk, so a claim that
    straddles a boundary still appears whole in at least one chunk.

    The size bound holds because two rules work together: a turn is pre-split to at most
    ``chunk_size - overlap``, and the replayed overlap never exceeds ``overlap``. Lengths
    are measured on the *rendered* text (including the "Speaker: " prefix), which is what
    actually gets embedded.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    overlap = max(0, min(overlap, chunk_size // 2))
    piece_limit = max(1, chunk_size - overlap)

    chunks: list[Chunk] = []
    current: list[Turn] = []
    length = 0

    def emit() -> None:
        if not current:
            return
        content = "\n".join(_render(turn) for turn in current).strip()
        if not content:
            return
        speakers = {turn.speaker for turn in current if turn.speaker}
        chunks.append(
            Chunk(
                index=len(chunks),
                content=content,
                speaker=next(iter(speakers)) if len(speakers) == 1 else None,
                char_start=current[0].char_start,
                char_end=current[-1].char_end,
                token_estimate=max(1, len(content) // 4),
            )
        )

    for turn in turns:
        for piece in _split_long_turn(turn, piece_limit):
            piece_len = len(_render(piece)) + 1  # +1 for the newline used to join turns
            if current and length + piece_len > chunk_size:
                emit()
                carry: list[Turn] = []
                carried = 0
                # Stop *before* exceeding the overlap budget. Carrying past it could
                # replay a full-size turn and then append another, doubling the chunk.
                for previous in reversed(current):
                    previous_len = len(_render(previous)) + 1
                    if carried + previous_len > overlap:
                        break
                    carry.insert(0, previous)
                    carried += previous_len
                current = carry
                length = carried
            current.append(piece)
            length += piece_len

    emit()
    return chunks


def _render(turn: Turn) -> str:
    return f"{turn.speaker}: {turn.text}" if turn.speaker else turn.text


def _split_long_turn(turn: Turn, limit: int) -> list[Turn]:
    """Break a turn on sentence boundaries so each piece renders within ``limit``."""
    # The rendered form carries a "Speaker: " prefix, so budget for it.
    limit = max(1, limit - (len(turn.speaker) + 2 if turn.speaker else 0))
    if len(turn.text) <= limit:
        return [turn]

    pieces: list[Turn] = []
    sentences = re.split(r"(?<=[.!?])\s+", turn.text)
    buffer: list[str] = []
    offset = turn.char_start
    for sentence in sentences:
        candidate = (" ".join(buffer + [sentence])).strip()
        if buffer and len(candidate) > limit:
            body = " ".join(buffer).strip()
            pieces.append(Turn(turn.speaker, body, offset, offset + len(body)))
            offset += len(body) + 1
            buffer = [sentence]
        else:
            buffer.append(sentence)
    if buffer:
        body = " ".join(buffer).strip()
        pieces.append(Turn(turn.speaker, body, offset, min(turn.char_end, offset + len(body))))
    return pieces


def chunk_transcript(raw: str, *, chunk_size: int = 1200, overlap: int = 200) -> tuple[str, list[Chunk]]:
    """Clean then chunk. Returns the cleaned text and its chunks."""
    cleaned = clean_transcript(raw)
    return cleaned, chunk_turns(split_turns(cleaned), chunk_size=chunk_size, overlap=overlap)
