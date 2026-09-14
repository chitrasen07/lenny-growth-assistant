"""Session endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import AppSettings, DbSession
from app.schemas.chat import MessageOut, SessionCreateRequest, SessionSummary
from app.services.chat import ChatService
from app.services.sessions import SessionService

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionSummary, status_code=status.HTTP_201_CREATED, summary="Create a chat session")
async def create_session(payload: SessionCreateRequest, db: DbSession, settings: AppSettings) -> SessionSummary:
    record = await SessionService(db, settings).create(payload.title)
    return SessionSummary(
        id=record.id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
        message_count=0,
    )


@router.get("", response_model=list[SessionSummary], summary="List chat sessions, most recent first")
async def list_sessions(db: DbSession, settings: AppSettings) -> list[SessionSummary]:
    return [
        SessionSummary(
            id=record.id,
            title=record.title,
            created_at=record.created_at,
            updated_at=record.updated_at,
            message_count=count,
        )
        for record, count in await SessionService(db, settings).list_with_counts()
    ]


@router.get("/{session_id}", response_model=SessionSummary, summary="Get one session")
async def get_session(session_id: uuid.UUID, db: DbSession, settings: AppSettings) -> SessionSummary:
    service = SessionService(db, settings)
    record = await service.get(session_id)
    return SessionSummary(
        id=record.id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
        message_count=await service.message_count(session_id),
    )


@router.get("/{session_id}/messages", response_model=list[MessageOut], summary="Get a session's message history")
async def list_messages(session_id: uuid.UUID, db: DbSession, settings: AppSettings) -> list[MessageOut]:
    messages = await SessionService(db, settings).list_messages(session_id)
    return [ChatService.to_message_out(message) for message in messages]


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a session and its messages")
async def delete_session(session_id: uuid.UUID, db: DbSession, settings: AppSettings) -> None:
    await SessionService(db, settings).delete(session_id)
