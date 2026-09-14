"""Artifact model.

``content`` holds the *sanitised* document for HTML artifacts — the raw model output is
never persisted, so nothing unsafe can be served later even if a future endpoint skips
sanitisation. ``sanitiser_report`` records what was removed, which the viewer surfaces.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ArtifactType(StrEnum):
    MARKDOWN = "markdown"
    HTML = "html"


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    type: Mapped[ArtifactType] = mapped_column(Enum(ArtifactType, name="artifact_type", native_enum=False, length=20))
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    sanitised: Mapped[bool] = mapped_column(Boolean, default=False)
    sanitiser_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    message: Mapped["Message"] = relationship(back_populates="artifacts")  # noqa: F821
