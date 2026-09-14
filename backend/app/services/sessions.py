"""Session and message persistence.

Every read is filtered by ``session_id``. That is the whole of the session-isolation
guarantee: there is no code path that loads messages without scoping them to one session,
so switching sessions in the UI cannot leak context between conversations.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.models.artifact import Artifact
from app.models.chat import Message, MessageRole, Session

logger = get_logger(__name__)

_TITLE_MAX = 60


def derive_title(first_message: str) -> str:
    """Use the opening question as the session title, trimmed at a word boundary."""
    cleaned = " ".join(first_message.split())
    if len(cleaned) <= _TITLE_MAX:
        return cleaned or "New chat"
    return cleaned[:_TITLE_MAX].rsplit(" ", 1)[0] + "…"


class SessionService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._db = session
        self._settings = settings or get_settings()

    async def create(self, title: str | None = None) -> Session:
        record = Session(title=(title or "New chat").strip()[:200] or "New chat")
        self._db.add(record)
        await self._db.flush()
        logger.info("session_created", session_id=str(record.id))
        return record

    async def get(self, session_id: uuid.UUID) -> Session:
        record = await self._db.get(Session, session_id)
        if record is None:
            raise NotFoundError(f"Session {session_id} does not exist.")
        return record

    async def list_with_counts(self, limit: int = 100) -> list[tuple[Session, int]]:
        counts = (
            select(Message.session_id, func.count(Message.id).label("message_count"))
            .group_by(Message.session_id)
            .subquery()
        )
        statement = (
            select(Session, func.coalesce(counts.c.message_count, 0))
            .outerjoin(counts, counts.c.session_id == Session.id)
            .order_by(Session.updated_at.desc())
            .limit(limit)
        )
        return [(session, int(count)) for session, count in (await self._db.execute(statement)).all()]

    async def message_count(self, session_id: uuid.UUID) -> int:
        return int(
            await self._db.scalar(select(func.count(Message.id)).where(Message.session_id == session_id)) or 0
        )

    async def list_messages(self, session_id: uuid.UUID) -> list[Message]:
        await self.get(session_id)  # 404 rather than an empty list for an unknown session.
        statement = select(Message).where(Message.session_id == session_id).order_by(Message.seq)
        return list((await self._db.execute(statement)).unique().scalars().all())

    async def history_for_prompt(self, session_id: uuid.UUID) -> list[tuple[str, str]]:
        """Recent turns of this session, oldest first, bounded by count and characters.

        Bounding matters on local models with an 8k context: an unbounded transcript would
        crowd out the retrieved evidence, which is the part that must survive.
        """
        statement = (
            select(Message.role, Message.content)
            .where(Message.session_id == session_id)
            .order_by(Message.seq.desc())
            .limit(self._settings.max_history_messages)
        )
        rows = (await self._db.execute(statement)).all()

        history: list[tuple[str, str]] = []
        budget = self._settings.max_history_chars
        for role, content in rows:  # newest first, so the budget drops the oldest turns
            if budget - len(content) < 0:
                break
            budget -= len(content)
            history.append((str(role.value if hasattr(role, "value") else role), content))
        history.reverse()
        return history

    async def add_message(
        self,
        session_id: uuid.UUID,
        role: MessageRole,
        content: str,
        metadata: dict | None = None,
    ) -> Message:
        message = Message(session_id=session_id, role=role, content=content, meta=metadata or {})
        self._db.add(message)
        await self._db.flush()
        return message

    async def touch(self, session_id: uuid.UUID, *, title_from: str | None = None) -> None:
        """Bump ``updated_at`` and set the title from the first user message."""
        record = await self.get(session_id)
        if title_from and record.title in {"New chat", ""}:
            record.title = derive_title(title_from)
        record.updated_at = func.now()
        await self._db.flush()

    async def delete(self, session_id: uuid.UUID) -> None:
        await self.get(session_id)
        await self._db.execute(delete(Session).where(Session.id == session_id))
        logger.info("session_deleted", session_id=str(session_id))

    async def latest_artifact(self, session_id: uuid.UUID) -> Artifact | None:
        return await self._db.scalar(
            select(Artifact).where(Artifact.session_id == session_id).order_by(Artifact.created_at.desc()).limit(1)
        )
