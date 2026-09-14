"""Health and configuration endpoints.

``/health`` reports ``degraded`` instead of failing when an *optional* dependency is down,
so an unconfigured cloud provider never makes the service look broken. It returns 200 as
long as the API itself is serving; the component flags carry the detail.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from app.agent.service import runtime_name_for_provider
from app.api.deps import AppSettings, DbSession
from app.core.config import LLMProviderName
from app.db.session import check_database
from app.models.transcript import Transcript, TranscriptChunk
from app.providers.factory import get_provider
from app.schemas.system import (
    ComponentHealth,
    ConfigResponse,
    HealthResponse,
    KnowledgeBaseStatus,
    ProviderInfo,
)

router = APIRouter(tags=["system"])

APP_VERSION = "1.0.0"


async def _knowledge_base_status(db, settings) -> KnowledgeBaseStatus:  # noqa: ANN001
    transcripts = int(await db.scalar(select(func.count()).select_from(Transcript)) or 0)
    chunks = int(await db.scalar(select(func.count()).select_from(TranscriptChunk)) or 0)
    return KnowledgeBaseStatus(
        transcripts=transcripts,
        chunks=chunks,
        embedding_model=settings.embedding_model,
        embedding_dimensions=settings.embedding_dimensions,
        ready=chunks > 0,
    )


@router.get("/health", response_model=HealthResponse, summary="Service and dependency health")
async def health(response: Response, settings: AppSettings) -> HealthResponse:
    db_healthy, db_error = await check_database(settings)

    ollama = await get_provider(LLMProviderName.OLLAMA, settings).health()
    cloud = await get_provider(LLMProviderName.ANTHROPIC, settings).health()
    active_provider_ok = ollama.available if settings.llm_provider is LLMProviderName.OLLAMA else cloud.available

    knowledge_base = None
    if db_healthy:
        from app.db.session import get_session_factory

        async with get_session_factory(settings)() as db:
            knowledge_base = await _knowledge_base_status(db, settings)

    degraded = not db_healthy or not active_provider_ok or (knowledge_base is not None and not knowledge_base.ready)
    # 200 keeps container health checks passing while a model is still being pulled;
    # the payload is what tells an operator which component needs attention.
    response.headers["Cache-Control"] = "no-store"

    active_runtime = runtime_name_for_provider(settings.llm_provider)

    return HealthResponse(
        status="degraded" if degraded else "ok",
        version=APP_VERSION,
        api=ComponentHealth(healthy=True, detail="serving"),
        database=ComponentHealth(healthy=db_healthy, detail=None if db_healthy else f"unreachable ({db_error})"),
        llm_provider=settings.llm_provider.value,
        llm_model=settings.active_model(),
        agent_runtime=active_runtime,
        active_runtime=active_runtime,
        ollama=ComponentHealth(healthy=ollama.available, detail=ollama.detail),
        cloud_provider=ComponentHealth(healthy=cloud.available, detail=cloud.detail),
        knowledge_base=knowledge_base,
    )


@router.get("/api/config", response_model=ConfigResponse, summary="Non-secret runtime configuration")
async def config(db: DbSession, settings: AppSettings) -> ConfigResponse:
    """Drives the provider indicator and the model toggle in the UI."""
    ollama = await get_provider(LLMProviderName.OLLAMA, settings).health()
    cloud = await get_provider(LLMProviderName.ANTHROPIC, settings).health()
    active_runtime = runtime_name_for_provider(settings.llm_provider)

    return ConfigResponse(
        active_provider=settings.llm_provider.value,
        active_model=settings.active_model(),
        agent_runtime=active_runtime,
        active_runtime=active_runtime,
        providers=[
            ProviderInfo(
                name=LLMProviderName.OLLAMA.value,
                model=settings.ollama_model,
                available=ollama.available,
                detail=ollama.detail,
                runtime=runtime_name_for_provider(LLMProviderName.OLLAMA),
            ),
            ProviderInfo(
                name=LLMProviderName.ANTHROPIC.value,
                model=settings.anthropic_model,
                available=cloud.available,
                detail=cloud.detail,
                runtime=runtime_name_for_provider(LLMProviderName.ANTHROPIC),
            ),
        ],
        retrieval_top_k=settings.retrieval_top_k,
        essay_target_words=settings.essay_target_words,
        knowledge_base=await _knowledge_base_status(db, settings),
    )
