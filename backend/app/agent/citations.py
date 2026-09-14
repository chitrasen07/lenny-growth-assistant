"""Citation parsing and verification.

Turns the ``[Sn]`` markers a model wrote into verified links to indexed chunks. Two things
matter here:

* a marker that does not correspond to a retrieved chunk is **removed** from the text,
  so the UI can never show a citation that resolves to nothing;
* which sources were genuinely cited is recorded, so the sources panel can distinguish
  "supported this answer" from "was retrieved but unused".

A third check sits on top of the markers: a claim that names a known speaker or guest is
kept only when the cited chunk actually supports that person. This includes verb-style
attribution ("X said") and marker-adjacent naming ("X from Y [S1]", "X's approach [S2]").
Marker validity alone is not enough — citing Jason Cohen's excerpt does not make it legal
to credit the line to Lenny Rachitsky.

A fourth check covers specific figures: a percentage, dollar amount, or million/billion
quantity must appear in the cited excerpt. Naming the right guest does not make an
invented 47% lift true.
"""

from __future__ import annotations

import re

from app.core.logging import get_logger
from app.rag.chunking import _SPEAKER_PATTERN
from app.rag.retrieval import RetrievedChunk

logger = get_logger(__name__)

#: Matches [S1], [S2], and grouped forms like [S1, S3] or [S1][S2].
_MARKER_PATTERN = re.compile(r"\[\s*S\s*(\d+(?:\s*,\s*S?\s*\d+)*)\s*\]", re.IGNORECASE)

#: Capitalised person-name span. Kept tight so we do not swallow the rest of a sentence.
_NAME = r"[A-Z][\w.'’\-]+(?:\s+[A-Z][\w.'’\-]+){0,4}"

#: Verbs that, next to a name, assert the person made the claim.
_ATTRIBUTION_VERBS = (
    r"said|says|suggests|suggested|argues|argued|mentions|mentioned|"
    r"explains|explained|notes|noted|recommends|recommended|"
    r"emphasizes|emphasised|emphasized|describes|described|claims|claimed|"
    r"observes|observed|adds|added|warns|warned"
)

#: Captures a name in an attribution construction. Case-sensitive on purpose: IGNORECASE
#: would make ``[A-Z]`` match any letter and over-capture.
_ATTRIBUTION_CAPTURE = re.compile(
    rf"(?:according\s+to|as\s+(?:mentioned|said|noted|explained|described|argued|suggested)\s+by)\s+({_NAME})"
    rf"|(?:mentioned|said|noted|explained|described)\s+by\s+({_NAME})"
    rf"|\bby\s+({_NAME})\s+in\s+\[S"
    rf"|({_NAME})(?:\s+(?:also|then|further|now|even))?\s+(?:{_ATTRIBUTION_VERBS})\b",
)

#: The podcast host. Always considered a known person so a Jason-only excerpt cannot be
#: credited to him just because the model typed his name.
_HOST_NAMES = ("Lenny Rachitsky",)


def extract_markers(text: str) -> set[int]:
    markers: set[int] = set()
    for match in _MARKER_PATTERN.finditer(text):
        for part in match.group(1).split(","):
            digits = re.sub(r"\D", "", part)
            if digits:
                markers.add(int(digits))
    return markers


def strip_invalid_markers(text: str, valid: set[int]) -> tuple[str, set[int]]:
    """Remove markers outside ``valid``. Returns the cleaned text and dropped markers."""
    dropped: set[int] = set()

    def replace(match: re.Match[str]) -> str:
        numbers = [int(re.sub(r"\D", "", part)) for part in match.group(1).split(",") if re.sub(r"\D", "", part)]
        kept = [number for number in numbers if number in valid]
        dropped.update(number for number in numbers if number not in valid)
        if not kept:
            return ""
        return "[" + ", ".join(f"S{number}" for number in kept) + "]"

    cleaned = _MARKER_PATTERN.sub(replace, text)
    # Tidy the spacing left behind by a removed marker.
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r" +([.,;:!?])", r"\1", cleaned)
    return cleaned.strip(), dropped


def apply_citations(text: str, chunks: list[RetrievedChunk]) -> tuple[str, set[int], set[int]]:
    """Validate the markers in ``text`` against ``chunks``.

    Returns ``(cleaned_text, cited_markers, dropped_markers)``.
    """
    valid = {chunk.marker for chunk in chunks}
    cleaned, dropped = strip_invalid_markers(text, valid)
    cleaned = strip_mismatched_attributions(cleaned, chunks)
    cleaned = strip_unsupported_specifics(cleaned, chunks)
    return cleaned, extract_markers(cleaned), dropped


def strip_mismatched_attributions(text: str, chunks: list[RetrievedChunk]) -> str:
    """Drop sentences that credit a person the cited excerpt does not support."""
    if not text.strip():
        return text

    by_marker = {chunk.marker: chunk for chunk in chunks}
    known = _known_people(chunks)
    kept_lines: list[str] = []

    for line in text.split("\n"):
        if not line.strip():
            kept_lines.append("")
            continue
        sentences = re.split(r"(?<=[.!?])\s+", line.strip())
        kept = [sentence for sentence in sentences if not _is_mismatched_attribution(sentence, by_marker, known)]
        if kept:
            kept_lines.append(" ".join(kept))

    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines))
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r" +([.,;:!?])", r"\1", cleaned)
    return cleaned.strip()


#: Percentages, currency, and magnitude figures that must appear in the cited excerpt.
_SPECIFIC_CLAIM = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?(?:\s*(?:million|billion|k))?"
    r"|\b\d[\d,]*(?:\.\d+)?\s*%"
    r"|\b\d[\d,]*(?:\.\d+)?\s*(?:percent|million|billion)\b",
    re.IGNORECASE,
)


def strip_unsupported_specifics(text: str, chunks: list[RetrievedChunk]) -> str:
    """Drop sentences whose percentages/figures are not in the cited excerpt.

    Guest match is not enough: "Elena Verna notes a 47% lift [S1]" is removed unless
    that excerpt actually contains 47%. Uncited figures are removed too.
    """
    if not text.strip():
        return text

    by_marker = {chunk.marker: chunk for chunk in chunks}
    kept_lines: list[str] = []

    for line in text.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            kept_lines.append(line)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", line.strip())
        kept = [sentence for sentence in sentences if not _is_unsupported_specific(sentence, by_marker)]
        if kept:
            kept_lines.append(" ".join(kept))

    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines))
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r" +([.,;:!?])", r"\1", cleaned)
    return cleaned.strip()


def _is_unsupported_specific(sentence: str, by_marker: dict[int, RetrievedChunk]) -> bool:
    tokens = _specific_tokens(sentence)
    if not tokens:
        return False

    markers = extract_markers(sentence)
    if not markers:
        logger.warning("specific_claim_uncited", tokens=tokens)
        return True

    haystacks = []
    for marker in markers:
        chunk = by_marker.get(marker)
        if chunk is not None:
            haystacks.append(chunk.content)
    if not haystacks:
        return True

    combined = "\n".join(haystacks)
    for token in tokens:
        if not _content_covers_specific(combined, token):
            logger.warning("specific_claim_unsupported", token=token, markers=sorted(markers))
            return True
    return False


def _specific_tokens(sentence: str) -> list[str]:
    stripped = _MARKER_PATTERN.sub(" ", sentence)
    return [match.group(0) for match in _SPECIFIC_CLAIM.finditer(stripped)]


def _content_covers_specific(content: str, token: str) -> bool:
    hay = _normalize_specific(content)
    needle = _normalize_specific(token)
    if needle and needle in hay:
        return True
    percent = re.fullmatch(r"([0-9.]+)\s*%", needle)
    if percent:
        value = percent.group(1)
        return f"{value}%" in hay or f"{value} percent" in hay
    percent = re.fullmatch(r"([0-9.]+)\s*percent", needle)
    if percent:
        value = percent.group(1)
        return f"{value}%" in hay or f"{value} percent" in hay
    return False


def _normalize_specific(value: str) -> str:
    value = value.lower().replace(",", "").replace("$", " ")
    return re.sub(r"\s+", " ", value).strip()


def chunk_supports_person(chunk: RetrievedChunk, name: str) -> bool:
    """True when ``name`` is a speaker this excerpt can honestly be credited to."""
    if _name_matches(name, chunk.speaker):
        return True
    if chunk.speaker:
        # Single-speaker excerpt: only that speaker is attributable.
        return False

    labels = _speaker_labels(chunk.content)
    if len(labels) == 1:
        only = next(iter(labels))
        return _name_matches(name, only)

    # Mixed or unlabelled excerpt: the episode guest is the attributable party. A host
    # one-liner packed into the same window must not take credit for the guest's point.
    return _name_matches(name, chunk.guest)


def _is_mismatched_attribution(
    sentence: str,
    by_marker: dict[int, RetrievedChunk],
    known: list[str],
) -> bool:
    names = _attributed_names(sentence, known)
    if not names:
        return False

    markers = extract_markers(sentence)
    if not markers:
        logger.warning("attribution_uncited", persons=names)
        return True

    for name in names:
        for marker in markers:
            chunk = by_marker.get(marker)
            if chunk is None or not chunk_supports_person(chunk, name):
                logger.warning(
                    "attribution_mismatch",
                    person=name,
                    marker=marker,
                    speaker=None if chunk is None else chunk.speaker,
                    guest=None if chunk is None else chunk.guest,
                )
                return True
    return False


def _attributed_names(sentence: str, known: list[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        cleaned = name.strip().strip(" ,;:")
        key = _norm(cleaned)
        if not key or key in seen:
            return
        # One-token captures ("The", "So") are noise unless they match a known speaker.
        if " " not in key and not any(_name_matches(cleaned, person) for person in known):
            return
        seen.add(key)
        found.append(cleaned)

    for match in _ATTRIBUTION_CAPTURE.finditer(sentence):
        captured = next((group for group in match.groups() if group), None)
        if captured:
            add(captured)
    for person in known:
        if _person_attributed_in(sentence, person):
            add(person)
    # A valid [S#] next to a known guest still needs to be that guest's excerpt, even
    # when the model wrote "X from Y [S1]" instead of "X said [S1]".
    if extract_markers(sentence):
        for person in known:
            if _person_named_in(sentence, person):
                add(person)
    return found


def _person_named_in(sentence: str, person: str) -> bool:
    """True when a known speaker/guest is named in ``sentence``, including possessives."""
    return any(
        re.search(rf"\b{re.escape(form)}(?:['’]s)?\b", sentence, flags=re.IGNORECASE)
        for form in _name_surface_forms(person)
    )


def _name_surface_forms(person: str) -> list[str]:
    """Full name plus forms with a trailing episode suffix stripped (e.g. ``Elena Verna 4.0``)."""
    tokens = person.split()
    if not tokens:
        return []
    forms = [" ".join(tokens)]
    while len(tokens) >= 2 and re.fullmatch(r"[0-9.]+", tokens[-1]):
        tokens = tokens[:-1]
        forms.append(" ".join(tokens))
    return forms


def _person_attributed_in(sentence: str, person: str) -> bool:
    name = re.escape(person)
    verbs = _ATTRIBUTION_VERBS
    patterns = (
        rf"\baccording\s+to\s+{name}\b",
        rf"\bas\s+(?:mentioned|said|noted|explained|described|argued|suggested)\s+by\s+{name}\b",
        rf"\b(?:mentioned|said|noted|explained|described)\s+by\s+{name}\b",
        rf"\bby\s+{name}\s+in\s+\[S",
        rf"\b{name}(?:\s+(?:also|then|further|now|even))?\s+(?:{verbs})\b",
        rf"\b(?:{verbs})\s+{name}\b",
    )
    return any(re.search(pattern, sentence, re.IGNORECASE) for pattern in patterns)


def _known_people(chunks: list[RetrievedChunk]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(raw: str | None) -> None:
        if not raw:
            return
        key = _norm(raw)
        if not key or key in seen:
            return
        seen.add(key)
        names.append(raw)

    for host in _HOST_NAMES:
        add(host)
    for chunk in chunks:
        add(chunk.speaker)
        add(chunk.guest)
        for label in _speaker_labels(chunk.content):
            add(label)
    names.sort(key=lambda value: len(_norm(value)), reverse=True)
    return names


def _speaker_labels(content: str) -> set[str]:
    labels: set[str] = set()
    for line in content.splitlines():
        match = _SPEAKER_PATTERN.match(line.strip())
        if not match:
            continue
        label = (match.group("bracket") or match.group("plain") or "").strip()
        if label:
            labels.add(label)
    return labels


def _name_matches(attributed: str, field: str | None) -> bool:
    if not field:
        return False
    attributed_norm = _norm(attributed)
    field_norm = _norm(field)
    if not attributed_norm or not field_norm:
        return False
    if attributed_norm == field_norm:
        return True
    if field_norm.startswith(attributed_norm + " "):
        return True
    if attributed_norm.startswith(field_norm + " "):
        return True
    return False


def _norm(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"[^\w\s'-]", " ", value)
    value = re.sub(r"['’]s\b", "", value)
    return re.sub(r"\s+", " ", value).strip()
