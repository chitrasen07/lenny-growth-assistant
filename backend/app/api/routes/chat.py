"""Chat endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AppSettings, DbSession
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat import ChatService

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse, summary="Send a message and get a grounded reply")
async def chat(payload: ChatRequest, db: DbSession, settings: AppSettings) -> ChatResponse:
    """Route the message to a skill, answer from transcript evidence, and persist the turn.

    Depending on the message this returns a grounded answer with citations, a Ship 30 essay,
    or an artifact for the viewer. ``grounded=false`` means the assistant declined because
    the knowledge base had no relevant evidence.
    """
    return await ChatService(db, settings).send(payload.session_id, payload.message, payload.provider)
