"""Health, configuration and knowledge-base schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    healthy: bool
    detail: str | None = None


class KnowledgeBaseStatus(BaseModel):
    transcripts: int
    chunks: int
    embedding_model: str
    embedding_dimensions: int
    #: False when nothing has been ingested yet; the UI prompts the evaluator to ingest.
    ready: bool


class HealthResponse(BaseModel):
    """Overall service health.

    ``status`` is ``degraded`` rather than an HTTP error when an optional dependency is
    down, so a missing cloud key never makes the health check itself fail.
    """

    status: Literal["ok", "degraded"]
    version: str
    api: ComponentHealth
    database: ComponentHealth
    llm_provider: str
    llm_model: str
    #: Actual runtime for ``llm_provider`` / ``active_provider`` (not the AGENT_RUNTIME env).
    agent_runtime: str
    active_runtime: str
    ollama: ComponentHealth
    cloud_provider: ComponentHealth
    knowledge_base: KnowledgeBaseStatus | None = None


class ProviderInfo(BaseModel):
    name: str
    model: str
    available: bool
    #: Why it is unavailable, e.g. "ANTHROPIC_API_KEY missing". Never contains the key.
    detail: str | None = None
    #: Runtime ``AgentService`` constructs when this provider is selected.
    runtime: str


class ConfigResponse(BaseModel):
    """Non-secret runtime configuration, used to render the provider indicator."""

    active_provider: str
    active_model: str
    #: Actual runtime for ``active_provider``. Same value as ``agent_runtime``.
    agent_runtime: str
    active_runtime: str
    providers: list[ProviderInfo] = Field(default_factory=list)
    retrieval_top_k: int
    essay_target_words: int
    knowledge_base: KnowledgeBaseStatus
