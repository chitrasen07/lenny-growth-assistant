"""Artifact request schemas."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import LLMProviderName


class ArtifactGenerateRequest(BaseModel):
    """Explicit artifact generation, used by the 'Generate artifact' controls.

    The conversational path (asking the assistant for a landing page) is routed by the
    agent instead; this endpoint exists so the UI can request a specific format directly.
    """

    session_id: uuid.UUID
    artifact_type: Literal["markdown", "html"]
    instruction: str = Field(min_length=1, max_length=2000)
    provider: LLMProviderName | None = None

    @field_validator("instruction")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("instruction must not be blank")
        return cleaned
