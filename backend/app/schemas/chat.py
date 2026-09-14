"""Request/response schemas for sessions, messages and chat."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import LLMProviderName
from app.models.chat import MessageRole


class SessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200, description="Optional title; derived from the first message when omitted.")


class SessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class SourceOut(BaseModel):
    """A transcript chunk offered as evidence for an answer.

    Optional fields are ``None`` when the source transcript did not state them; they are
    never guessed. ``excerpt`` is a short quote from the indexed chunk so a reviewer can
    check the claim against the evidence.
    """

    chunk_id: uuid.UUID
    transcript_id: uuid.UUID
    title: str
    episode: str | None = None
    guest: str | None = None
    source_url: str | None = None
    source_file: str
    chunk_index: int
    speaker: str | None = None
    excerpt: str
    #: Cosine distance from the query embedding: lower is more similar.
    distance: float
    #: 1-based marker the model was told to cite, e.g. 2 for "[S2]".
    marker: int
    #: True when the answer actually referenced this source.
    cited: bool = False


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: Literal["markdown", "html"]
    title: str
    content: str
    sanitised: bool
    sanitiser_report: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    sources: list[SourceOut] = Field(default_factory=list)
    artifact: ArtifactOut | None = None


class ChatRequest(BaseModel):
    session_id: uuid.UUID
    message: str = Field(min_length=1, max_length=8000)
    #: Per-request override of LLM_PROVIDER so the UI toggle works without a restart.
    provider: LLMProviderName | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("message must not be blank")
        return cleaned


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    message: MessageOut
    provider: LLMProviderName
    model: str
    #: "question" | "ship30_essay" | "artifact" — which skill handled the turn.
    intent: str
    #: True when the assistant declined for lack of transcript evidence.
    grounded: bool
    timings_ms: dict[str, int] = Field(default_factory=dict)
