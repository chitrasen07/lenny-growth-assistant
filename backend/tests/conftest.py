"""Test fixtures.

Design decisions:

* **A real PostgreSQL is used**, because pgvector similarity search is the behaviour under
  test and SQLite cannot emulate it. Tests are skipped with an explanatory message when no
  database is reachable, rather than silently passing.
* **No network calls.** ``EMBEDDING_PROVIDER=hash`` selects the deterministic offline
  embedder and every LLM call goes through :class:`FakeProvider`, so the suite is fast and
  reproducible while still exercising the real retrieval, routing and persistence code.
* **Test content is synthetic and written inline.** Tests seed the corpus through
  :func:`seed_transcript` using short passages written for this suite with invented
  speakers and titles. No Lenny's Podcast content is bundled, and no test asserts against
  real episode text — the fixtures exist only so retrieval and citation behaviour can be
  checked deterministically.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator

# Environment must be set before app.core.config is first imported.
# Port 5433 matches POSTGRES_HOST_PORT in .env.example (5432 is often already in use).
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://lenny:lenny@localhost:5433/lenny_test"
)
os.environ.update(
    {
        "DATABASE_URL": TEST_DB_URL,
        "EMBEDDING_PROVIDER": "hash",
        "EMBEDDING_DIMENSIONS": "768",
        "LLM_PROVIDER": "ollama",
        "AGENT_RUNTIME": "router",
        "LOG_LEVEL": "WARNING",
        "LOG_FORMAT": "console",
        "ANTHROPIC_API_KEY": "",
        # Tuned for HashEmbedder, whose distances are not comparable to a real embedding
        # model's. Measured on the fixture corpus: topically related text lands at
        # 0.60-0.85, unrelated text at 1.0 (no shared content words). 0.90 sits inside
        # that gap. The production default (0.55) targets nomic-embed-text instead.
        "RETRIEVAL_MAX_DISTANCE": "0.90",
    }
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.core.runtime import configure_event_loop_policy  # noqa: E402

# psycopg async needs the selector loop on Windows; no-op elsewhere.
configure_event_loop_policy()
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import LLMProviderName, get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import set_session_factory  # noqa: E402
from app.models import Transcript, TranscriptChunk  # noqa: E402
from app.providers.base import ChatMessage, LLMProvider, LLMResponse, ProviderHealth, ToolCall, ToolSpec  # noqa: E402
from app.providers.factory import clear_providers, register_provider  # noqa: E402
from app.rag.embeddings import HashEmbedder, set_embedder  # noqa: E402


# --------------------------------------------------------------------- fake provider
class FakeProvider(LLMProvider):
    """Scriptable stand-in for a real LLM.

    Records the messages it receives so tests can assert *what the model was shown* —
    for example that retrieved evidence and prior turns reached the prompt.
    """

    name = "ollama"  # Impersonates the configured provider so routing is unchanged.
    supports_tools = True

    def __init__(self, responses: list[str] | None = None, model: str = "fake-model") -> None:
        self.model = model
        self._responses = list(responses or ["A grounded answer citing [S1]."])
        self.calls: list[list[ChatMessage]] = []
        self.raise_error: Exception | None = None

    def queue(self, *responses: str) -> None:
        self._responses = list(responses)

    @property
    def last_prompt(self) -> str:
        return "\n".join(message.content for message in self.calls[-1]) if self.calls else ""

    def _next(self) -> str:
        if self.raise_error is not None:
            raise self.raise_error
        if not self._responses:
            return "No further scripted response."
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]

    async def complete(self, messages, *, max_tokens=None, temperature=None) -> LLMResponse:  # noqa: ANN001
        self.calls.append(list(messages))
        return LLMResponse(text=self._next(), model=self.model, latency_ms=7)

    async def chat_with_tools(self, messages, tools: list[ToolSpec], *, max_tokens=None, temperature=None) -> LLMResponse:  # noqa: ANN001
        self.calls.append(list(messages))
        return LLMResponse(text=self._next(), tool_calls=list[ToolCall](), model=self.model, latency_ms=7)

    async def health(self) -> ProviderHealth:
        return ProviderHealth(True, "fake provider")


# --------------------------------------------------------------------- event loop
@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# --------------------------------------------------------------------- database
def _admin_url() -> str:
    return TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"


async def _ensure_database() -> str | None:
    """Create the test database and vector extension. Returns an error string on failure."""
    database = TEST_DB_URL.rsplit("/", 1)[-1]
    try:
        admin = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        async with admin.connect() as conn:
            exists = await conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database})
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{database}"'))
            else:
                # A previous run's connections can still be closing (notably when the suite
                # runs in a container that was just replaced), and they hold locks that make
                # the schema drop below fail. Only ever targets the test database.
                await conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :name AND pid <> pg_backend_pid()"
                    ),
                    {"name": database},
                )
        await admin.dispose()
    except Exception as exc:  # noqa: BLE001 - reported as a skip reason
        return f"{type(exc).__name__}: {exc}"

    try:
        engine = create_async_engine(TEST_DB_URL, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await engine.dispose()
    except Exception as exc:  # noqa: BLE001
        return f"pgvector extension unavailable — {type(exc).__name__}: {exc}"
    return None


@pytest_asyncio.fixture(scope="session")
async def engine():  # noqa: ANN201
    error = await _ensure_database()
    if error:
        pytest.skip(
            "PostgreSQL with pgvector is required for these tests. "
            f"Could not prepare {TEST_DB_URL}: {error}. "
            "Start it with: docker compose up -d db",
            allow_module_level=True,
        )

    engine = create_async_engine(TEST_DB_URL, poolclass=None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine) -> AsyncIterator[async_sessionmaker]:  # noqa: ANN001
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    set_session_factory(factory)
    yield factory
    # Truncate rather than drop so each test starts clean without rebuilding the schema.
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE artifacts, message_sources, messages, sessions, transcript_chunks, transcripts CASCADE")
        )
    set_session_factory(None)


@pytest_asyncio.fixture
async def db(session_factory) -> AsyncIterator:  # noqa: ANN001, ANN201
    async with session_factory() as session:
        yield session


# --------------------------------------------------------------------- app + provider
@pytest.fixture
def settings():  # noqa: ANN201
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def provider() -> FakeProvider:
    """Stand in for the *active* provider (Ollama) so no test reaches the network.

    Anthropic is deliberately left unregistered so it behaves like a genuinely
    unconfigured cloud provider: it reports its missing key and raises before making any
    request. Tests that need a working cloud provider register one explicitly.
    """
    clear_providers()
    fake = FakeProvider()
    register_provider(LLMProviderName.OLLAMA, fake)
    return fake


@pytest.fixture(autouse=True)
def reset_provider_cache():  # noqa: ANN201
    yield
    clear_providers()


@pytest.fixture(autouse=True)
def deterministic_embedder():  # noqa: ANN201
    set_embedder(HashEmbedder(768))
    yield
    set_embedder(None)


@pytest_asyncio.fixture
async def client(session_factory, provider) -> AsyncIterator[AsyncClient]:  # noqa: ANN001
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


# --------------------------------------------------------------------- corpus
async def seed_transcript(
    db,  # noqa: ANN001
    *,
    title: str,
    chunks: list[str],
    episode: str | None = None,
    guest: str | None = None,
    source_url: str | None = None,
    source_file: str | None = None,
    speakers: list[str | None] | None = None,
) -> Transcript:
    """Insert a transcript with embedded chunks using the deterministic test embedder."""
    embedder = HashEmbedder(768)
    vectors = await embedder.embed_documents(chunks)

    transcript = Transcript(
        source_file=source_file or f"{uuid.uuid4().hex[:8]}.txt",
        content_hash=uuid.uuid4().hex,
        title=title,
        episode=episode,
        guest=guest,
        source_url=source_url,
        chunk_count=len(chunks),
    )
    db.add(transcript)
    await db.flush()

    db.add_all(
        [
            TranscriptChunk(
                transcript_id=transcript.id,
                chunk_index=index,
                content=content,
                speaker=(speakers[index] if speakers else None),
                char_start=index * 100,
                char_end=index * 100 + len(content),
                token_estimate=len(content) // 4,
                embedding=vector,
            )
            for index, (content, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
    )
    await db.commit()
    return transcript


# Synthetic passages authored for this test suite. Invented speakers and companies —
# NOT real podcast content. Wording is chosen so the hash embedder can separate topics.
ACTIVATION_CHUNKS = [
    "Dana Okoye: Activation is the moment a new user reaches the outcome they signed up for. "
    "We measured activation as the percentage of signups completing a first meaningful action "
    "within seven days, and that single activation metric moved retention more than acquisition spend.",
    "Dana Okoye: The activation mistake teams make is optimising signup instead of the first "
    "meaningful action. We removed four onboarding steps, added a guided checklist, and activation "
    "rose because users reached value faster rather than because signup got shorter.",
]

PRICING_CHUNKS = [
    "Rafael Mendes: Pricing is a packaging problem before it is a number problem. We interviewed "
    "forty accounts, found willingness to pay clustered into three segments, and repackaged our "
    "pricing tiers around the value metric each segment cared about rather than raising the price.",
]
