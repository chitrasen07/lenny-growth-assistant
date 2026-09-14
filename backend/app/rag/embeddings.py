"""Embedding backends.

Ollama is the real backend. ``HashEmbedder`` exists so the automated tests can exercise
the full retrieval path offline and deterministically — it is selected only by
``EMBEDDING_PROVIDER=hash`` and is never used to produce answers shown to a user.
"""

from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod

from app.core.config import EmbeddingProviderName, Settings, get_settings
from app.core.errors import EmbeddingError
from app.core.logging import get_logger
from app.providers.ollama import OllamaProvider

logger = get_logger(__name__)


class Embedder(ABC):
    model: str
    dimensions: int

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_documents([text])
        if not vectors:
            raise EmbeddingError("Embedding the query returned no vector.")
        return vectors[0]

    def _validate(self, vectors: list[list[float]]) -> list[list[float]]:
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingError(
                    f"Embedding model '{self.model}' returned {len(vector)} dimensions "
                    f"but EMBEDDING_DIMENSIONS is {self.dimensions}.",
                    remedy="Align EMBEDDING_DIMENSIONS with the model, then re-run ingestion "
                    "(stored vectors must all share one dimension).",
                )
        return vectors


class OllamaEmbedder(Embedder):
    def __init__(self, provider: OllamaProvider, model: str, dimensions: int, batch_size: int = 16) -> None:
        self._provider = provider
        self.model = model
        self.dimensions = dimensions
        self._batch_size = batch_size

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors.extend(await self._provider.embed(batch))
        return self._validate(vectors)


#: Function words carry no topic signal but dominate a bag-of-words vector, making every
#: pair of sentences look similar. Removing them is what gives the test embedder usable
#: separation between topics.
_STOPWORDS = frozenset(
    """a about above after again against all also am an and any are aren as at be because been
    before being below between both but by can cannot could did do does doing don down during
    each few for from further had has have having he her here hers him his how i if in into is
    it its itself just me more most my no nor not of off on once only or other our out over own
    same she should so some such than that the their them then there these they this those
    through to too under until up very was we were what when where which while who whom why
    will with would you your yours""".split()
)


class HashEmbedder(Embedder):
    """Deterministic lexical hashing embedder for offline tests.

    Not semantic: it hashes content words into a fixed vector space, so shared vocabulary
    drives similarity. Synonyms will not match, which is exactly why it is confined to
    tests — but it is enough to verify ranking, thresholds, the refusal path and citation
    plumbing with no model server, and it makes the suite fast and reproducible.

    Because its distance distribution differs from a real embedding model's, tests set
    ``RETRIEVAL_MAX_DISTANCE`` to a value tuned for this embedder (see tests/conftest.py).
    """

    model = "hash-test-embedder"

    def __init__(self, dimensions: int = 768) -> None:
        self.dimensions = dimensions

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        normalised = "".join(char.lower() if char.isalnum() else " " for char in text)
        tokens = [token for token in normalised.split() if len(token) > 2 and token not in _STOPWORDS]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            # Sub-linear term frequency: a word repeated 10x should not swamp the vector.
            vector[index] += 1.0
        for index, value in enumerate(vector):
            if value:
                vector[index] = 1.0 + math.log(value)

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            # Keep a stable unit vector so cosine distance stays defined for empty text.
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]


_embedder: Embedder | None = None


def get_embedder(settings: Settings | None = None) -> Embedder:
    global _embedder
    if _embedder is not None:
        return _embedder

    settings = settings or get_settings()
    if settings.embedding_provider is EmbeddingProviderName.HASH:
        logger.warning("embedder_test_mode", model=HashEmbedder.model)
        _embedder = HashEmbedder(settings.embedding_dimensions)
    else:
        provider = OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.llm_timeout_seconds,
            embedding_model=settings.embedding_model,
        )
        _embedder = OllamaEmbedder(
            provider,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            batch_size=settings.embedding_batch_size,
        )
    return _embedder


def set_embedder(embedder: Embedder | None) -> None:
    """Test hook."""
    global _embedder
    _embedder = embedder
