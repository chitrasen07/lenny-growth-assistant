"""Chat session and message models.

Sessions are independent by construction: messages are only ever reachable through a
``session_id`` foreign key, and every read path filters on it. There is no global
message table scan anywhere in the service layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Index, Integer, Sequence, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

#: Orders messages by insertion. `created_at` alone is not safe: PostgreSQL's now() is
#: transaction-scoped, so a user turn and its assistant reply written in one transaction
#: share a timestamp, and tie-breaking on a random UUID would scramble the conversation.
MESSAGE_SEQUENCE = Sequence("messages_seq")


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Message.seq",
        lazy="selectin",
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_session_seq", "session_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    #: Monotonic insertion order. Every read orders by this, never by created_at.
    seq: Mapped[int] = mapped_column(
        BigInteger, MESSAGE_SEQUENCE, server_default=MESSAGE_SEQUENCE.next_value(), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role", native_enum=False, length=20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    #: Provider, model, intent, latency, refusal flag, sanitiser summary. Never credentials.
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)

    session: Mapped[Session] = relationship(back_populates="messages")
    sources: Mapped[list[MessageSource]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="MessageSource.rank",
        lazy="selectin",
    )
    artifacts: Mapped[list[Artifact]] = relationship(  # noqa: F821 - resolved by registry
        back_populates="message", cascade="all, delete-orphan", lazy="selectin"
    )


class MessageSource(Base):
    """Join row linking an assistant message to the transcript chunk that supports it.

    Citations are stored as real foreign keys rather than free text so a reviewer can
    always resolve a citation back to the exact indexed chunk. ``cited`` records whether
    the model actually referenced the chunk, as opposed to it merely being retrieved.
    """

    __tablename__ = "message_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transcript_chunks.id", ondelete="CASCADE"))
    rank: Mapped[int] = mapped_column(Integer)
    distance: Mapped[float] = mapped_column(Float)
    cited: Mapped[bool] = mapped_column(default=False)

    message: Mapped[Message] = relationship(back_populates="sources")
    chunk: Mapped["TranscriptChunk"] = relationship(lazy="selectin")  # noqa: F821


from app.models.artifact import Artifact  # noqa: E402  (late import resolves the relationship)
from app.models.transcript import TranscriptChunk  # noqa: E402
