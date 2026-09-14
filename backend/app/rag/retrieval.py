"""Vector retrieval over indexed transcript chunks.

The relevance threshold is the mechanism behind the product's honesty guarantee: when
nothing clears ``retrieval_max_distance`` the caller is told there is no evidence and
answers the user with a refusal, *without* asking an LLM anything. That makes the
"I couldn't find this in the transcripts" path deterministic rather than a request that
the model please behave.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.transcript import Transcript, TranscriptChunk
from app.rag.embeddings import Embedder, get_embedder

logger = get_logger(__name__)


@dataclass(slots=True)
class RetrievedChunk:
    """A chunk plus everything needed to cite it."""

    chunk_id: str
    transcript_id: str
    content: str
    distance: float
    rank: int
    chunk_index: int
    speaker: str | None
    title: str
    episode: str | None
    guest: str | None
    source_url: str | None
    source_file: str

    @property
    def marker(self) -> int:
        """1-based citation marker, i.e. ``[S1]`` for rank 0."""
        return self.rank + 1

    def label(self) -> str:
        parts = [self.title]
        if self.episode and self.episode != self.title:
            parts.append(f"episode: {self.episode}")
        if self.guest:
            parts.append(f"guest: {self.guest}")
        return " — ".join(parts)


@dataclass(slots=True)
class RetrievalResult:
    chunks: list[RetrievedChunk]
    query: str
    latency_ms: int
    #: True when the index itself is empty, as opposed to holding nothing relevant.
    knowledge_base_empty: bool = False

    @property
    def has_evidence(self) -> bool:
        return bool(self.chunks)

    def evidence_block(self) -> str:
        """Render the numbered evidence the prompts cite as ``[S1]``…``[Sn]``."""
        return "\n\n".join(
            f"[S{chunk.marker}] {chunk.label()}\n\"\"\"\n{chunk.content}\n\"\"\"" for chunk in self.chunks
        )


class RetrievalService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None, embedder: Embedder | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._embedder = embedder or get_embedder(self._settings)

    def build_query(self, question: str, history: list[str] | None = None) -> str:
        """Expand a follow-up into a self-contained retrieval query.

        "What about for B2B SaaS?" carries no retrievable terms on its own, so recent user
        turns are prepended. This is a deliberate cheap alternative to an LLM query-rewrite
        call: it costs nothing, cannot fail, and is enough to recover the missing subject.
        Only *user* turns are used, so the model's own wording cannot pull retrieval
        off-topic.
        """
        question = question.strip()
        if not history:
            return question
        # Short questions are the ones that depend on context; long ones stand alone.
        if len(question.split()) > 12:
            return question
        recent = " ".join(history[-2:]).strip()
        if not recent:
            return question
        combined = f"{recent} {question}"
        return combined[-1000:]

    async def count_chunks(self) -> int:
        return int(await self._session.scalar(select(func.count()).select_from(TranscriptChunk)) or 0)

    async def retrieve(
        self,
        question: str,
        *,
        history: list[str] | None = None,
        top_k: int | None = None,
        max_distance: float | None = None,
        context_char_budget: int | None = None,
        max_chunks_per_episode: int | None = None,
    ) -> RetrievalResult:
        settings = self._settings
        top_k = top_k or settings.retrieval_top_k
        max_distance = settings.retrieval_max_distance if max_distance is None else max_distance
        budget = context_char_budget or settings.retrieval_context_char_budget
        per_episode_cap = (
            max_chunks_per_episode
            if max_chunks_per_episode is not None
            else settings.retrieval_max_chunks_per_episode
        )

        query = self.build_query(question, history)
        started = time.perf_counter()

        if await self.count_chunks() == 0:
            logger.warning("retrieval_knowledge_base_empty")
            return RetrievalResult([], query, int((time.perf_counter() - started) * 1000), knowledge_base_empty=True)

        embedding = await self._embedder.embed_query(query)

        # Over-fetch so per-episode capping still leaves top_k candidates.
        distance = TranscriptChunk.embedding.cosine_distance(embedding).label("distance")
        statement = (
            select(TranscriptChunk, Transcript, distance)
            .join(Transcript, Transcript.id == TranscriptChunk.transcript_id)
            .order_by(distance)
            .limit(top_k * 3)
        )
        rows = (await self._session.execute(statement)).all()

        selected: list[RetrievedChunk] = []
        per_episode: dict[str, int] = {}
        used_chars = 0
        for chunk, transcript, chunk_distance in rows:
            if len(selected) >= top_k:
                break
            if chunk_distance is None or float(chunk_distance) > max_distance:
                continue
            key = str(transcript.id)
            if per_episode.get(key, 0) >= per_episode_cap:
                continue
            if used_chars + len(chunk.content) > budget and selected:
                continue
            per_episode[key] = per_episode.get(key, 0) + 1
            used_chars += len(chunk.content)
            selected.append(
                RetrievedChunk(
                    chunk_id=str(chunk.id),
                    transcript_id=str(transcript.id),
                    content=chunk.content,
                    distance=round(float(chunk_distance), 4),
                    rank=len(selected),
                    chunk_index=chunk.chunk_index,
                    speaker=chunk.speaker,
                    title=transcript.title,
                    episode=transcript.episode,
                    guest=transcript.guest,
                    source_url=transcript.source_url,
                    source_file=transcript.source_file,
                )
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "retrieval_completed",
            candidates=len(rows),
            selected=len(selected),
            best_distance=selected[0].distance if selected else None,
            max_distance=max_distance,
            per_episode_cap=per_episode_cap,
            latency_ms=latency_ms,
            context_chars=used_chars,
        )
        return RetrievalResult(selected, query, latency_ms)
