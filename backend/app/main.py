"""FastAPI application factory and lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.service import runtime_name_for_provider
from app.api.errors import register_exception_handlers
from app.api.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from app.api.routes import artifacts, chat, health, sessions
from app.core.config import get_settings
from app.core.logging import configure_logging, describe_secret, get_logger
from app.db.session import check_database, dispose_engine
from app.providers.factory import close_providers

logger = get_logger(__name__)

DESCRIPTION = """\
Conversational assistant grounded in Lenny's Podcast transcripts.

Ask product and growth questions and get answers with citations traceable to indexed
transcript chunks, generate a Ship 30 for 30-style essay, or produce Markdown and
HTML/CSS artifacts rendered in the in-app Artifact Viewer.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    db_healthy, db_error = await check_database(settings)
    # Startup logs the configuration an operator needs, and only whether secrets exist.
    logger.info(
        "startup",
        environment=settings.environment,
        llm_provider=settings.llm_provider.value,
        llm_model=settings.active_model(),
        agent_runtime=runtime_name_for_provider(settings.llm_provider),
        embedding_model=settings.embedding_model,
        anthropic_api_key=describe_secret(settings.anthropic_api_key),
        database=("healthy" if db_healthy else f"unavailable ({db_error})"),
    )
    if not db_healthy:
        # Deliberately not fatal: the API still serves /health so an operator can see why.
        logger.error("startup_database_unavailable", detail=db_error)

    yield

    await close_providers()
    await dispose_engine()
    logger.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version=health.APP_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "x-request-id"],
    )
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(chat.router)
    app.include_router(artifacts.router)

    return app


app = create_app()
