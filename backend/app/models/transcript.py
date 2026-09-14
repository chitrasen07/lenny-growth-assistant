"""Transcript and chunk models.

Metadata fields are nullable on purpose: if a transcript file does not state its guest
or source URL, the value stays ``NULL`` and the UI omits it. Nothing is inferred or
invented, because a fabricated citation is worse than a missing one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.core.config import get_settings


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    source_file: Mapped[str] = mapped_column(String(500), unique=True)
    #: SHA-256 of the normalised text; lets ingestion skip unchanged files.
    content_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500))
    episode: Mapped[str | None] = mapped_column(String(300), nullable=True)
    guest: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list[TranscriptChunk]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan", order_by="TranscriptChunk.chunk_index"
    )


class TranscriptChunk(Base):
    __tablename__ = "transcript_chunks"
    __table_args__ = (
        UniqueConstraint("transcript_id", "chunk_index", name="uq_chunk_position"),
        Index("ix_chunk_transcript", "transcript_id", "chunk_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    transcript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    speaker: Mapped[str | None] = mapped_column(String(200), nullable=True)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[float]] = mapped_column(Vector(get_settings().embedding_dimensions))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transcript: Mapped[Transcript] = relationship(back_populates="chunks", lazy="joined")
