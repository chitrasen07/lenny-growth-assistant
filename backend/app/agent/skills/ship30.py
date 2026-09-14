"""`generate_ship30_essay` — long-form grounded essay writing.

A separate skill rather than a branch in the chat handler because it differs from Q&A in
every dimension that matters: a wider evidence budget, a different system prompt, and a
post-generation length check with a bounded revision pass. Keeping it separate also keeps
it testable in isolation and keeps the writing principles in one reviewable place.
"""

from __future__ import annotations

import re
from typing import Any

from app.agent.citations import apply_citations, extract_markers
from app.agent.prompts import REFUSAL_MESSAGE, ship30_system_prompt
from app.agent.types import Skill, SkillContext, SkillResult
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.providers.base import ChatMessage
from app.rag.retrieval import RetrievedChunk

logger = get_logger(__name__)

#: Below this, the evidence is too thin to sustain ~1,250 grounded words and the essay
#: would inevitably drift into invented generic advice.
_MIN_CHUNKS_FOR_ESSAY = 3

#: Initial draft plus at most two continue/tighten passes. Local models often undershoot
#: a 1,250-word target twice; a third generation still keeps the loop bounded.
_MAX_ATTEMPTS = 3

#: Ship 30 essays stay skimmable: a heading per guest produces a catalogue, not a narrative.
_MAX_H2_SECTIONS = 6

_TOPIC_STOPWORDS = {
    "about",
    "after",
    "and",
    "for",
    "from",
    "how",
    "into",
    "improving",
    "the",
    "this",
    "that",
    "with",
    "your",
}

#: A trailing paragraph longer than this is the essay body, even if the model omitted a
#: final period. Shorter tails without terminal punctuation are truncated fragments.
_MAX_INCOMPLETE_TAIL_WORDS = 24

_ESSAY_PREFIX = re.compile(
    r"""
    ^(?:please\s+|can\s+you\s+|could\s+you\s+|i\s+want\s+you\s+to\s+)?
    (?:(?:write|draft|generate|create|compose)\s+(?:me\s+)?(?:a\s+|an\s+)?)?
    (?:ship\s*30(?:\s*for\s*30)?\s+(?:style\s+)?)?
    (?:essay|piece|article|post)\s+
    (?:about|on|regarding|on\s+the\s+topic\s+of)\s+
    """,
    re.IGNORECASE | re.VERBOSE,
)
_TERMINAL_PUNCTUATION = re.compile(r"""[.!?]["')\]]*$""")
_STANDALONE_BOLD = re.compile(r"^\*\*(.+?)\*\*\s*$")


def count_words(markdown: str) -> int:
    """Count prose words, ignoring markdown syntax and citation markers."""
    text = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"\[\s*S\s*\d+(?:\s*,\s*S?\s*\d+)*\s*\]", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[#>*_`~\-|]+", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return len([word for word in text.split() if any(char.isalnum() for char in word)])


def topic_focus(raw: str) -> str:
    """Strip 'write a Ship 30 essay about …' boilerplate so retrieval targets the topic."""
    text = raw.strip()
    if not text:
        return text
    stripped = _ESSAY_PREFIX.sub("", text, count=1).strip()
    if stripped and stripped != text:
        stripped = re.sub(r"\s+(?:for\s+me|please)\.?$", "", stripped, flags=re.I)
        return stripped.strip(" .,:;") or text
    leftover = re.sub(r"\bship\s*30(?:\s*for\s*30)?\b", " ", text, flags=re.I)
    leftover = re.sub(
        r"\b(?:please|write|draft|generate|create|compose|essay|piece|article|post)\b",
        " ",
        leftover,
        flags=re.I,
    )
    leftover = re.sub(r"\s+", " ", leftover).strip(" .,:;")
    return leftover or text


def count_h2_sections(markdown: str) -> int:
    """Count markdown H2 headings (``## ``), ignoring H1 and H3+."""
    return sum(1 for line in markdown.splitlines() if re.match(r"^##\s+\S", line) and not line.startswith("###"))


def constrain_h2_sections(markdown: str, maximum: int = _MAX_H2_SECTIONS) -> str:
    """Keep at most ``maximum`` H2s; demote extras to bold lead-ins so prose is not deleted."""
    count = 0
    lines: list[str] = []
    for line in markdown.split("\n"):
        match = re.match(r"^##\s+(.+)$", line)
        if match and not line.startswith("###"):
            count += 1
            if count > maximum:
                heading = match.group(1).strip()
                lines.append(f"**{heading}**.")
                logger.info("ship30_demoted_extra_h2", heading=heading[:80])
                continue
        lines.append(line)
    return "\n".join(lines)


def promote_bold_headings(markdown: str) -> str:
    """Treat a standalone bold line as an H2. Local models often skip ``##``."""
    lines: list[str] = []
    for line in markdown.split("\n"):
        match = _STANDALONE_BOLD.fullmatch(line.strip())
        heading = match.group(1).strip() if match else ""
        if heading and 1 <= len(heading.split()) <= 12 and not heading.startswith("["):
            lines.append(f"## {heading}")
        else:
            lines.append(line)
    return "\n".join(lines)


def merge_continuation(base: str, addition: str) -> str:
    """Append a continue-pass onto the cleaned draft without repeating the H1."""
    add = addition.strip()
    if not add:
        return base
    add = re.sub(r"^#\s+.+\n+", "", add)
    return f"{base.rstrip()}\n\n{add}"


def trim_to_maximum(markdown: str, maximum: int) -> str:
    """Drop trailing words until the essay is at most ``maximum`` words."""
    if count_words(markdown) <= maximum:
        return markdown
    lines = markdown.split("\n")
    kept: list[str] = []
    for line in lines:
        candidate = "\n".join(kept + [line]) if kept else line
        if count_words(candidate) <= maximum:
            kept.append(line)
            continue
        remaining = maximum - count_words("\n".join(kept)) if kept else maximum
        prefix: list[str] = []
        for token in line.split():
            if count_words(" ".join(prefix + [token])) > remaining:
                break
            prefix.append(token)
        if prefix:
            kept.append(" ".join(prefix))
        break
    return "\n".join(kept).rstrip()


def drop_process_notes(markdown: str) -> str:
    """Remove leaked drafting notes that mention the evidence block or word target."""
    kept: list[str] = []
    for line in markdown.split("\n"):
        if re.match(r"(?i)^\s*note:", line) and re.search(
            r"(?i)evidence|h2|word target|these instructions", line
        ):
            logger.info("ship30_dropped_process_note")
            continue
        kept.append(line)
    return "\n".join(kept).rstrip()


def _topic_terms(focus: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]{4,}", focus.lower())
        if token not in _TOPIC_STOPWORDS
    ]


def keep_on_topic_chunks(chunks: list[RetrievedChunk], focus: str) -> list[RetrievedChunk]:
    """Keep excerpts whose body mentions the essay topic.

    Retrieved neighbours are candidates, not mandatory content. A chunk about pricing or
    distribution is dropped unless it actually names the topic. Markers on kept chunks
    are left unchanged so citations still resolve. If too few remain, the skill refuses
    rather than writing from off-topic leftovers.
    """
    terms = _topic_terms(focus)
    if not terms:
        return chunks
    kept: list[RetrievedChunk] = []
    for chunk in chunks:
        haystack = chunk.content.lower()
        if any(term in haystack for term in terms):
            kept.append(chunk)
        else:
            logger.info("ship30_dropped_off_topic_chunk", marker=chunk.marker, title=chunk.title[:80])
    return kept


def drop_incomplete_tail(markdown: str) -> str:
    """Drop a short trailing fragment that was cut off mid-sentence, and empty headings."""
    lines = markdown.rstrip().split("\n")
    while lines:
        last = lines[-1].rstrip()
        if not last:
            lines.pop()
            continue
        if last.startswith("#"):
            lines.pop()
            logger.info("ship30_dropped_trailing_heading")
            continue
        if last.startswith(("- ", "* ", ">")):
            break
        if _TERMINAL_PUNCTUATION.search(last):
            break
        prose = re.sub(r"\[\s*S\s*\d+(?:\s*,\s*S?\s*\d+)*\s*\]", " ", last, flags=re.I)
        words = [word for word in prose.split() if any(char.isalnum() for char in word)]
        if len(words) > _MAX_INCOMPLETE_TAIL_WORDS:
            break
        lines.pop()
        logger.info("ship30_dropped_incomplete_tail", words=len(words))
        break
    return "\n".join(lines).rstrip()


_CAUSAL_MARK = re.compile(
    r"(?i)\b(?:this is because|that's because|because|therefore|thus|hence|"
    r"as a result|which means|which causes|which makes|"
    r"making (?:users|customers|people) more likely)\b"
)
_CAUSAL_SPLIT = re.compile(
    r"(?i)\b(?:this is because|that's because|because|therefore|thus|hence|"
    r"as a result|which means|which causes|which makes)\b"
)
_CAUSAL_STOP = {
    "about",
    "after",
    "because",
    "being",
    "could",
    "hence",
    "likely",
    "makes",
    "making",
    "means",
    "more",
    "people",
    "result",
    "should",
    "their",
    "therefore",
    "users",
    "using",
    "which",
    "would",
}


def _split_sentences(line: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", line.strip()) if part]


def strip_unsupported_causation(text: str, chunks: list[RetrievedChunk]) -> str:
    """Drop sentences that invent a causal chain the cited excerpt does not state."""
    if not text.strip():
        return text
    by_marker = {chunk.marker: chunk for chunk in chunks}
    kept_lines: list[str] = []
    for line in text.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            kept_lines.append(line)
            continue
        kept = [
            sentence
            for sentence in _split_sentences(line)
            if not _is_unsupported_causal(sentence, by_marker)
        ]
        if kept:
            kept_lines.append(" ".join(kept))
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines))
    return cleaned.strip()


def _is_unsupported_causal(sentence: str, by_marker: dict[int, RetrievedChunk]) -> bool:
    if not _CAUSAL_MARK.search(sentence):
        return False
    markers = extract_markers(sentence)
    haystacks = [
        by_marker[marker].content.lower()
        for marker in markers
        if marker in by_marker
    ]
    combined = "\n".join(haystacks)
    parts = _CAUSAL_SPLIT.split(sentence, maxsplit=1)
    explanation = parts[1] if len(parts) > 1 else sentence
    explanation = re.sub(r"\[\s*S\s*\d+(?:\s*,\s*S?\s*\d+)*\s*\]", " ", explanation, flags=re.I)
    tokens = [
        token
        for token in re.findall(r"[a-z]{5,}", explanation.lower())
        if token not in _CAUSAL_STOP
    ]
    if not tokens:
        return not any(word in combined for word in ("because", "therefore", "thus"))
    hits = sum(1 for token in tokens if token in combined)
    unsupported = hits / len(tokens) < 0.5
    if unsupported:
        logger.info("ship30_dropped_unsupported_causal", preview=sentence[:120])
    return unsupported


def _person_key(raw: str | None) -> str:
    if not raw:
        return ""
    tokens = raw.split()
    while tokens and re.fullmatch(r"[0-9.]+", tokens[-1]):
        tokens.pop()
    return " ".join(tokens).lower()


def _people_from_chunks(chunks: list[RetrievedChunk]) -> set[str]:
    names: set[str] = set()
    for chunk in chunks:
        for raw in (chunk.speaker, chunk.guest):
            key = _person_key(raw)
            if key:
                names.add(key)
    return names


def drop_outsider_guest_sentences(
    text: str,
    kept_chunks: list[RetrievedChunk],
    original_chunks: list[RetrievedChunk],
) -> str:
    """Drop claims credited to guests whose excerpts were filtered out as off-topic."""
    if not text.strip():
        return text
    allowed = _people_from_chunks(kept_chunks)
    banned = {
        name
        for name in _people_from_chunks(original_chunks)
        if name not in allowed and "rachitsky" not in name
    }
    if not banned:
        return text
    patterns = [
        re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
        for name in sorted(banned, key=len, reverse=True)
    ]
    kept_lines: list[str] = []
    for line in text.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            kept_lines.append(line)
            continue
        kept = [
            sentence
            for sentence in _split_sentences(line)
            if not any(pattern.search(sentence) for pattern in patterns)
        ]
        if kept:
            kept_lines.append(" ".join(kept))
        elif any(pattern.search(line) for pattern in patterns):
            logger.info("ship30_dropped_outsider_guest", preview=line[:120])
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines))
    return cleaned.strip()


def drop_off_topic_cited_sentences(text: str, chunks: list[RetrievedChunk], focus: str) -> str:
    """Drop cited sentences whose excerpts never mention the essay topic."""
    terms = _topic_terms(focus)
    if not text.strip() or not terms:
        return text
    by_marker = {chunk.marker: chunk for chunk in chunks}
    kept_lines: list[str] = []
    for line in text.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            kept_lines.append(line)
            continue
        kept: list[str] = []
        for sentence in _split_sentences(line):
            markers = extract_markers(sentence)
            if not markers:
                kept.append(sentence)
                continue
            cited = [by_marker[marker] for marker in markers if marker in by_marker]
            if not cited or any(any(term in chunk.content.lower() for term in terms) for chunk in cited):
                kept.append(sentence)
            else:
                logger.info("ship30_dropped_off_topic_sentence", preview=sentence[:120])
        if kept:
            kept_lines.append(" ".join(kept))
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines))
    return cleaned.strip()


class Ship30EssaySkill(Skill):
    name = "generate_ship30_essay"
    description = (
        "Write a Ship 30 for 30-style essay of roughly 1,250 words on a product or growth "
        "topic, grounded in Lenny's Podcast transcripts with inline citations. Use when the "
        "user asks for an essay or a Ship 30 for 30 piece."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "The essay topic, e.g. 'improving activation for B2B SaaS'.",
            }
        },
        "required": ["topic"],
    }

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def run(self, context: SkillContext, **kwargs: Any) -> SkillResult:
        topic = str(kwargs.get("topic", "")).strip()
        if not topic:
            return SkillResult(text="Tell me what the essay should be about and I'll draft it.", refused=True)

        focus = topic_focus(topic)
        settings = self._settings
        retrieval = await context.retrieval.retrieve(
            focus,
            history=context.user_turns(),
            top_k=settings.essay_top_k,
            context_char_budget=settings.essay_context_char_budget,
            # Q&A caps chunks per episode to diversify sources, but an essay legitimately
            # draws deeply on the one episode that covers the topic best. Without this,
            # a small corpus could never supply enough evidence to write an essay at all.
            max_chunks_per_episode=settings.essay_max_chunks_per_episode,
        )
        original_chunks = list(retrieval.chunks)
        retrieval.chunks = keep_on_topic_chunks(retrieval.chunks, focus)

        if len(retrieval.chunks) < _MIN_CHUNKS_FOR_ESSAY:
            detail = (
                "No transcripts have been ingested yet."
                if retrieval.knowledge_base_empty
                else f"I found only {len(retrieval.chunks)} relevant excerpt(s) on that topic, which is not enough "
                f"to write a {settings.essay_target_words}-word essay without inventing material."
            )
            logger.info("ship30_refused", chunks=len(retrieval.chunks), topic=focus[:120])
            return SkillResult(
                text=f"{REFUSAL_MESSAGE}\n\n{detail} Try a topic the podcast covers in depth, or ingest more transcripts.",
                retrieval=retrieval,
                refused=True,
                meta={"refusal_reason": "insufficient_evidence", "chunks": len(retrieval.chunks)},
            )

        target = settings.essay_target_words
        tolerance = settings.essay_word_tolerance
        system = ship30_system_prompt(target, tolerance)
        minimum, maximum = int(target * (1 - tolerance)), int(target * (1 + tolerance))

        messages = [
            ChatMessage("system", system),
            ChatMessage(
                "user",
                f"EVIDENCE:\n{retrieval.evidence_block()}\n\n"
                f"TOPIC: {focus}\n\n"
                f"Write one coherent Ship 30 essay on that topic only, with 4-6 H2 sections "
                f"that all advance the same thesis (why it matters, what gets in the way, "
                f"how to think about it, lessons from the evidence, one takeaway). "
                f"Do not add a heading per guest. Do not repeat the same thesis in a new section. "
                f"Retrieved excerpts are candidates: use only those that directly support this topic "
                f"and ignore the rest, even if they mention growth, revenue, pricing, distribution "
                f"or relationships. Do not invent causal explanations the excerpts do not state. "
                f"Aim for {target} words ({minimum}-{maximum}). "
                "Every sentence must be complete. Do not invent guests, quotes, URLs, numbers or claims. "
                "A [S#] marker is valid only when that excerpt actually states the claim.",
            ),
        ]

        # Essays need considerably more room than a Q&A turn: ~1,250 words plus markdown.
        max_tokens = max(settings.llm_max_output_tokens, 3000)
        response = await context.provider.complete(messages, max_tokens=max_tokens, temperature=0.6)
        essay = response.text.strip()
        attempts = 1
        total_latency = response.latency_ms

        if not essay:
            return SkillResult(
                text=REFUSAL_MESSAGE,
                retrieval=retrieval,
                refused=True,
                meta={"refusal_reason": "empty_model_response"},
            )

        cleaned, cited, dropped, words = self._finalize_essay(
            essay, retrieval.chunks, focus, original_chunks, maximum
        )

        # Length is the cleaned, citation-validated essay — never the raw model draft.
        while cleaned and attempts < _MAX_ATTEMPTS:
            if minimum <= words <= maximum:
                break
            logger.info(
                "ship30_length_continue_after_cleanup",
                words=words,
                target=target,
                attempt=attempts,
            )
            messages.extend(
                [
                    ChatMessage("assistant", cleaned),
                    ChatMessage("user", self._revision_prompt(words, target, minimum, maximum, focus)),
                ]
            )
            continuation = await context.provider.complete(
                messages, max_tokens=max_tokens, temperature=0.5
            )
            total_latency += continuation.latency_ms
            attempts += 1
            if not continuation.text.strip():
                break
            raw = continuation.text.strip()
            replaced = self._finalize_essay(
                raw, retrieval.chunks, focus, original_chunks, maximum
            )
            candidates = [(cleaned, cited, dropped, words), replaced]
            if words < minimum:
                merged = self._finalize_essay(
                    merge_continuation(cleaned, raw),
                    retrieval.chunks,
                    focus,
                    original_chunks,
                    maximum,
                )
                candidates.append(merged)
            cleaned, cited, dropped, words = self._pick_draft(
                target, minimum, maximum, *candidates
            )

        title = self._extract_title(cleaned) or f"Ship 30: {focus}"

        logger.info(
            "ship30_completed",
            words=words,
            target=target,
            within_tolerance=minimum <= words <= maximum,
            attempts=attempts,
            cited=len(cited),
            evidence_chunks=len(retrieval.chunks),
        )
        return SkillResult(
            text=cleaned,
            retrieval=retrieval,
            meta={
                "word_count": words,
                "target_words": target,
                "within_tolerance": minimum <= words <= maximum,
                "attempts": attempts,
                "cited_markers": sorted(cited),
                "dropped_markers": sorted(dropped),
                "title": title,
                "model_latency_ms": total_latency,
            },
        )

    @staticmethod
    def _finalize_essay(
        essay: str,
        chunks: list[RetrievedChunk],
        focus: str = "",
        original_chunks: list[RetrievedChunk] | None = None,
        maximum: int | None = None,
    ) -> tuple[str, set[int], set[int], int]:
        """Verify citations, drop off-topic padding, and count the essay that will be shown.

        Word count is always taken from this cleaned text, never from the raw model draft.
        """
        cleaned, cited, dropped = apply_citations(essay, chunks)
        cleaned = strip_unsupported_causation(cleaned, chunks)
        cleaned = drop_outsider_guest_sentences(cleaned, chunks, original_chunks or chunks)
        cleaned = drop_off_topic_cited_sentences(cleaned, chunks, focus)
        cleaned = drop_process_notes(cleaned)
        cleaned = promote_bold_headings(cleaned)
        cleaned = constrain_h2_sections(cleaned)
        cleaned = drop_incomplete_tail(cleaned)
        if maximum is not None:
            cleaned = trim_to_maximum(cleaned, maximum)
        cited = extract_markers(cleaned) & {chunk.marker for chunk in chunks}
        return cleaned, cited, dropped, count_words(cleaned)

    @staticmethod
    def _pick_draft(
        target: int,
        minimum: int,
        maximum: int,
        *drafts: tuple[str, set[int], set[int], int] | None,
    ) -> tuple[str, set[int], set[int], int]:
        viable = [draft for draft in drafts if draft and draft[0]]
        in_range = [draft for draft in viable if minimum <= draft[3] <= maximum]
        if in_range:
            return min(in_range, key=lambda draft: abs(draft[3] - target))
        under = [draft for draft in viable if draft[3] <= maximum]
        if under:
            return max(under, key=lambda draft: draft[3])
        return min(viable, key=lambda draft: draft[3])

    @staticmethod
    def _revision_prompt(words: int, target: int, minimum: int, maximum: int, focus: str) -> str:
        if words < minimum:
            missing = minimum - words
            return (
                f"That cleaned draft is {words} words; the target is {target} ({minimum}-{maximum}). "
                f"It is {missing} words short. Continue the same essay on {focus} from the end of "
                "the draft. Output only new complete paragraphs and H2 sections; do not repeat the "
                "title or existing sections. Use only the same EVIDENCE. Stay at a total of 4-6 H2 "
                "sections. Do not add off-topic sections. Do not invent causal explanations. "
                "Return new prose only."
            )
        return (
            f"That cleaned draft is {words} words; the target is {target} ({minimum}-{maximum}). "
            "Tighten it by cutting repetition, extra headings and weaker sections. "
            "Keep 4-6 H2 sections, the hook, and one closing takeaway. Return the complete revised essay only."
        )

    @staticmethod
    def _extract_title(markdown: str) -> str | None:
        for line in markdown.split("\n"):
            if line.strip().startswith("# "):
                return line.strip()[2:].strip()[:200] or None
        return None
