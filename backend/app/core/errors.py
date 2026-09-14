"""Typed application errors and their HTTP mapping.

Every failure the product can hit has a stable ``code`` so the frontend can react
(and so logs are greppable) without parsing prose. Messages are safe to show to a
user: they never embed credentials or raw provider payloads.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected, user-presentable failures."""

    code = "internal_error"
    status_code = 500
    #: Human-readable hint on how to fix it, shown in the UI when present.
    remedy: str | None = None

    def __init__(self, message: str, *, remedy: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        if remedy is not None:
            self.remedy = remedy
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.remedy:
            payload["remedy"] = self.remedy
        if self.details:
            payload["details"] = self.details
        return payload


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404


class ValidationFailedError(AppError):
    code = "validation_failed"
    status_code = 422


class PayloadTooLargeError(AppError):
    code = "payload_too_large"
    status_code = 413


class DatabaseUnavailableError(AppError):
    code = "database_unavailable"
    status_code = 503
    remedy = "Check that PostgreSQL is running and DATABASE_URL is correct."


class ProviderConfigurationError(AppError):
    """Provider selected but not usable, e.g. a missing API key."""

    code = "provider_not_configured"
    status_code = 503


class ProviderUnavailableError(AppError):
    """Provider is configured but unreachable, e.g. Ollama is not running."""

    code = "provider_unavailable"
    status_code = 503


class ProviderTimeoutError(AppError):
    code = "provider_timeout"
    status_code = 504
    remedy = "Try a shorter question, or a smaller/faster model."


class ProviderResponseError(AppError):
    """Provider replied, but with an error or unusable content."""

    code = "provider_error"
    status_code = 502


class EmbeddingError(AppError):
    code = "embedding_failed"
    status_code = 503


class KnowledgeBaseEmptyError(AppError):
    code = "knowledge_base_empty"
    status_code = 503
    remedy = "Add transcripts to data/transcripts/ and run: docker compose exec backend python -m scripts.ingest"


class IngestionError(AppError):
    code = "ingestion_failed"
    status_code = 500


class ArtifactGenerationError(AppError):
    code = "artifact_generation_failed"
    status_code = 502
