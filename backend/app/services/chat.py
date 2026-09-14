"""Chat orchestration: persist the turn, run the agent, persist the result.

The user's message is committed before the agent runs, so a provider failure mid-turn
still leaves the conversation intact and the user can retry without retyping.
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.service import AgentService
from app.agent.types import SkillResult
from app.core.config import LLMProviderName, Settings, get_settings
from app.core.errors import PayloadTooLargeError
from app.core.logging import get_logger
from app.models.artifact import Artifact
from app.models.chat import Message, MessageRole, MessageSource
from app.schemas.chat import ArtifactOut, ChatResponse, MessageOut, SourceOut
from app.services.sessions import SessionService

logger = get_logger(__name__)

#: Enough to show the claim in context without shipping a whole chunk to the browser.
EXCERPT_CHARS = 420


class ChatService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._db = session
        self._settings = settings or get_settings()
        self._sessions = SessionService(session, self._settings)
        self._agent = AgentService(session, self._settings)

    async def send(
        self,
        session_id: uuid.UUID,
        message: str,
        provider_name: LLMProviderName | None = None,
    ) -> ChatResponse:
        if len(message) > self._settings.max_message_chars:
            raise PayloadTooLargeError(
                f"Message exceeds the {self._settings.max_message_chars:,} character limit.",
                remedy="Shorten the message or split it into several questions.",
            )

        await self._sessions.get(session_id)
        started = time.perf_counter()

        history = await self._sessions.history_for_prompt(session_id)
        await self._sessions.add_message(session_id, MessageRole.USER, message)
        await self._sessions.touch(session_id, title_from=message)
        await self._db.commit()

        result, route, provider = await self._agent.handle(
            message, history=history, provider_name=provider_name
        )

        total_ms = int((time.perf_counter() - started) * 1000)
        timings = {
            "total_ms": total_ms,
            "retrieval_ms": result.retrieval.latency_ms if result.retrieval else 0,
            "model_ms": int(result.meta.get("model_latency_ms", 0) or 0),
        }

        assistant = await self.record_assistant_turn(
            session_id, result, route_intent=route.intent.value, provider=provider, timings=timings
        )
        await self._db.commit()

        logger.info(
            "chat_completed",
            session_id=str(session_id),
            intent=route.intent.value,
            provider=provider.name,
            model=provider.model,
            refused=result.refused,
            sources=len(result.retrieval.chunks) if result.retrieval else 0,
            artifact=bool(result.artifact),
            **timings,
        )

        return ChatResponse(
            session_id=session_id,
            message=self.to_message_out(assistant),
            provider=LLMProviderName(provider.name),
            model=provider.model,
            intent=route.intent.value,
            grounded=not result.refused,
            timings_ms=timings,
        )

    async def record_assistant_turn(
        self,
        session_id: uuid.UUID,
        result: SkillResult,
        *,
        route_intent: str,
        provider,  # noqa: ANN001 - LLMProvider, kept loose to avoid a circular import
        timings: dict[str, int],
    ) -> Message:
        """Persist an assistant reply with its verified citations and any artifact."""
        cited = set(result.meta.get("cited_markers") or [])
        metadata = {
            "provider": provider.name,
            "model": provider.model,
            "intent": route_intent,
            "refused": result.refused,
            "timings_ms": timings,
            **{key: value for key, value in result.meta.items() if key != "sanitiser_report"},
        }

        assistant = await self._sessions.add_message(session_id, MessageRole.ASSISTANT, result.text, metadata)

        if result.retrieval and result.retrieval.chunks:
            self._db.add_all(
                [
                    MessageSource(
                        message_id=assistant.id,
                        chunk_id=uuid.UUID(chunk.chunk_id),
                        rank=chunk.rank,
                        distance=chunk.distance,
                        cited=chunk.marker in cited,
                    )
                    for chunk in result.retrieval.chunks
                ]
            )

        if result.artifact:
            self._db.add(
                Artifact(
                    session_id=session_id,
                    message_id=assistant.id,
                    type=result.artifact.type,
                    title=result.artifact.title,
                    content=result.artifact.content,
                    sanitised=bool(result.meta.get("sanitised")),
                    sanitiser_report=result.meta.get("sanitiser_report") or {},
                )
            )

        await self._db.flush()
        await self._db.refresh(assistant)
        return assistant

    # ------------------------------------------------------------- serialisation
    @staticmethod
    def to_message_out(message: Message) -> MessageOut:
        sources = [
            SourceOut(
                chunk_id=link.chunk_id,
                transcript_id=link.chunk.transcript_id,
                title=link.chunk.transcript.title,
                episode=link.chunk.transcript.episode,
                guest=link.chunk.transcript.guest,
                source_url=link.chunk.transcript.source_url,
                source_file=link.chunk.transcript.source_file,
                chunk_index=link.chunk.chunk_index,
                speaker=link.chunk.speaker,
                excerpt=_excerpt(link.chunk.content),
                distance=link.distance,
                marker=link.rank + 1,
                cited=link.cited,
            )
            for link in message.sources
            if link.chunk is not None
        ]
        artifact = message.artifacts[0] if message.artifacts else None
        return MessageOut(
            id=message.id,
            session_id=message.session_id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            metadata=message.meta or {},
            sources=sources,
            artifact=ArtifactOut.model_validate(artifact) if artifact else None,
        )


def _excerpt(content: str) -> str:
    if len(content) <= EXCERPT_CHARS:
        return content
    return content[:EXCERPT_CHARS].rsplit(" ", 1)[0] + "…"
