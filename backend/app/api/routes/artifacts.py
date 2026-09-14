"""Artifact endpoints.

Generation goes through the same agent skill the conversational path uses, so an artifact
requested from the UI control and one requested in chat are produced and sanitised
identically.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.agent.service import AgentService
from app.api.deps import AppSettings, DbSession
from app.agent.types import SkillContext
from app.core.errors import NotFoundError
from app.providers.factory import get_provider
from app.rag.retrieval import RetrievalService
from app.schemas.artifact import ArtifactGenerateRequest
from app.schemas.chat import ArtifactOut, ChatResponse
from app.services.chat import ChatService
from app.services.sessions import SessionService

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.post("", response_model=ChatResponse, summary="Generate a Markdown or HTML artifact")
async def generate_artifact(
    payload: ArtifactGenerateRequest, db: DbSession, settings: AppSettings
) -> ChatResponse:
    """Generate an artifact of an explicit type and record it as an assistant turn."""
    from app.core.config import LLMProviderName
    from app.models.chat import MessageRole

    sessions = SessionService(db, settings)
    await sessions.get(payload.session_id)

    history = await sessions.history_for_prompt(payload.session_id)
    provider = get_provider(payload.provider, settings)

    user_text = f"[{payload.artifact_type}] {payload.instruction}"
    await sessions.add_message(payload.session_id, MessageRole.USER, user_text)
    await sessions.touch(payload.session_id, title_from=payload.instruction)
    await db.commit()

    agent = AgentService(db, settings)
    skill = agent.registry.require("generate_artifact")
    context = SkillContext(provider=provider, retrieval=RetrievalService(db, settings), history=history)
    result = await skill.run(context, artifact_type=payload.artifact_type, instruction=payload.instruction)

    assistant = await ChatService(db, settings).record_assistant_turn(
        payload.session_id, result, route_intent="artifact", provider=provider, timings={}
    )
    await db.commit()

    return ChatResponse(
        session_id=payload.session_id,
        message=ChatService.to_message_out(assistant),
        provider=LLMProviderName(provider.name),
        model=provider.model,
        intent="artifact",
        grounded=not result.refused,
        timings_ms={"model_ms": int(result.meta.get("model_latency_ms", 0) or 0)},
    )


@router.get("/session/{session_id}/latest", response_model=ArtifactOut, summary="Latest artifact for a session")
async def latest_artifact(session_id: uuid.UUID, db: DbSession, settings: AppSettings) -> ArtifactOut:
    """Lets the viewer restore its content when the evaluator reloads or switches sessions."""
    service = SessionService(db, settings)
    await service.get(session_id)
    artifact = await service.latest_artifact(session_id)
    if artifact is None:
        raise NotFoundError(f"Session {session_id} has no artifacts yet.")
    return ArtifactOut.model_validate(artifact)
