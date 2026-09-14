"""Async database engine and session management.

Database outages surface as :class:`DatabaseUnavailableError` (HTTP 503) rather than an
unhandled 500, so the UI can tell the user what is actually wrong.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.errors import DatabaseUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _async_url(settings: Settings) -> str:
    url = settings.database_url
    # Accept the plain libpq URL that most tooling emits and route it to psycopg3.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = settings or get_settings()
        _engine = create_async_engine(
            _async_url(settings),
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
            future=True,
        )
    return _engine


def get_session_factory(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(settings), expire_on_commit=False, autoflush=False, class_=AsyncSession
        )
    return _session_factory


def set_session_factory(factory: async_sessionmaker[AsyncSession] | None) -> None:
    """Test hook: point the app at a session factory bound to a test engine."""
    global _session_factory
    _session_factory = factory


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional session."""
    factory = get_session_factory()
    try:
        session = factory()
    except SQLAlchemyError as exc:  # pragma: no cover - connection construction rarely fails
        logger.error("database_session_failed", error=str(exc))
        raise DatabaseUnavailableError("Could not open a database connection.") from exc

    try:
        yield session
        await session.commit()
    except (OperationalError, DBAPIError) as exc:
        await session.rollback()
        logger.error("database_unavailable", error=type(exc).__name__)
        raise DatabaseUnavailableError("The database is unavailable or timed out.") from exc
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_database(settings: Settings | None = None) -> tuple[bool, str | None]:
    """Health probe. Returns ``(healthy, error_kind)`` and never raises."""
    from sqlalchemy import text

    try:
        engine = get_engine(settings)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # noqa: BLE001 - health must never propagate
        return False, type(exc).__name__
