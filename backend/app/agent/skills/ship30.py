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


def _topic_terms(focus: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]{4,}", focus.lower())
        if token not in _TOPIC_STOPWORDS
    ]


def keep_on_topic_chunks(chunks: list[RetrievedChunk], focus: str) -> list[RetrievedChunk]:
    """Drop retrieved excerpts that never mention the essay topic. Markers are left unchanged."""
    terms = _topic_terms(focus)
    if not terms:
        return chunks
    kept: list[RetrievedChunk] = []
    for chunk in chunks:
        haystack = f"{chunk.content} {chunk.title} {chunk.guest or ''}".lower()
        if any(term in haystack for term in terms):
            kept.append(chunk)
        else:
            logger.info("ship30_dropped_off_topic_chunk", marker=chunk.marker, title=chunk.title[:80])
    if len(kept) >= _MIN_CHUNKS_FOR_ESSAY:
        return kept
    return chunks


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
                f"(hook, why it is hard, transcript evidence, practical lessons, one takeaway). "
                f"Do not add a heading per guest. Do not repeat the same thesis in a new section. "
                f"Use only EVIDENCE excerpts that directly support this topic; ignore the rest even if retrieved. "
                f"Aim for {target} words ({minimum}-{maximum}). "
                "Every sentence must be complete. Do not invent guests, quotes, URLs, numbers or claims. "
                "A [S#] marker is valid only when that excerpt actually states the claim.",
            ),
        ]

        # Essays need considerably more room than a Q&A turn: ~1,250 words plus markdown.
        max_tokens = max(settings.llm_max_output_tokens, 3000)
        response = await context.provider.complete(messages, max_tokens=max_tokens, temperature=0.6)
        essay = response.text.strip()
        words = count_words(essay)
        attempts = 1
        total_latency = response.latency_ms

        if essay and not (minimum <= words <= maximum):
            logger.info("ship30_length_revision", words=words, target=target)
            messages.extend(
                [
                    ChatMessage("assistant", essay),
                    ChatMessage("user", self._revision_prompt(words, target, minimum, maximum, focus)),
                ]
            )
            revision = await context.provider.complete(messages, max_tokens=max_tokens, temperature=0.5)
            total_latency += revision.latency_ms
            attempts = 2
            revised_words = count_words(revision.text)
            # Keep the revision only if it is genuinely closer to the target.
            if revision.text.strip() and abs(revised_words - target) < abs(words - target):
                essay, words = revision.text.strip(), revised_words

        # Local models often still undershoot after one rewrite. Continue the kept draft
        # from the same evidence rather than inventing a third full rewrite.
        while essay and words < minimum and attempts < _MAX_ATTEMPTS:
            logger.info("ship30_length_continue", words=words, target=target, attempt=attempts)
            messages.extend(
                [
                    ChatMessage("assistant", essay),
                    ChatMessage("user", self._revision_prompt(words, target, minimum, maximum, focus)),
                ]
            )
            continuation = await context.provider.complete(messages, max_tokens=max_tokens, temperature=0.5)
            total_latency += continuation.latency_ms
            attempts += 1
            continued_words = count_words(continuation.text)
            if continuation.text.strip() and abs(continued_words - target) < abs(words - target):
                essay, words = continuation.text.strip(), continued_words

        if not essay:
            return SkillResult(
                text=REFUSAL_MESSAGE,
                retrieval=retrieval,
                refused=True,
                meta={"refusal_reason": "empty_model_response"},
            )

        cleaned, cited, dropped, words = self._finalize_essay(essay, retrieval.chunks)

        # Citation cleanup can drop a draft that looked long enough. Use any remaining
        # generation budget to continue from the cleaned essay and the same evidence.
        while cleaned and words < minimum and attempts < _MAX_ATTEMPTS:
            logger.info("ship30_length_continue_after_cleanup", words=words, target=target, attempt=attempts)
            messages.extend(
                [
                    ChatMessage("assistant", cleaned),
                    ChatMessage("user", self._revision_prompt(words, target, minimum, maximum, focus)),
                ]
            )
            continuation = await context.provider.complete(messages, max_tokens=max_tokens, temperature=0.5)
            total_latency += continuation.latency_ms
            attempts += 1
            if not continuation.text.strip():
                break
            next_cleaned, next_cited, next_dropped, next_words = self._finalize_essay(
                continuation.text.strip(), retrieval.chunks
            )
            if next_cleaned and abs(next_words - target) < abs(words - target):
                cleaned, cited, dropped, words = next_cleaned, next_cited, next_dropped, next_words

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
        essay: str, chunks: list[RetrievedChunk]
    ) -> tuple[str, set[int], set[int], int]:
        """Verify citations, drop truncated tails, and count the essay that will be shown."""
        cleaned, cited, dropped = apply_citations(essay, chunks)
        cleaned = constrain_h2_sections(cleaned)
        cleaned = drop_incomplete_tail(cleaned)
        cited = extract_markers(cleaned) & {chunk.marker for chunk in chunks}
        return cleaned, cited, dropped, count_words(cleaned)

    @staticmethod
    def _revision_prompt(words: int, target: int, minimum: int, maximum: int, focus: str) -> str:
        if words < minimum:
            return (
                f"That draft is {words} words; the target is {target} ({minimum}-{maximum}). "
                f"Expand this draft in place. Keep every on-topic paragraph and continue the same essay "
                f"using only the EVIDENCE about: {focus}. "
                "Develop existing points with more concrete detail from the EVIDENCE. "
                "Stay at 4-6 H2 sections; fold extra ideas into those sections instead of adding headings. "
                "Do not add off-topic sections. Do not invent anything. Do not repeat the conclusion. "
                "Return the complete revised essay only."
            )
        return (
            f"That draft is {words} words; the target is {target} ({minimum}-{maximum}). "
            "Tighten it by cutting repetition, extra headings and weaker sections. "
            "Keep 4-6 H2 sections, the hook, and one closing takeaway. Return the complete revised essay only."
        )

    @staticmethod
    def _extract_title(markdown: str) -> str | None:
        for line in markdown.split("\n"):
            if line.strip().startswith("# "):
                return line.strip()[2:].strip()[:200] or None
        return None
