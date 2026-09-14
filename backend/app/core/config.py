"""Application configuration, loaded from environment variables."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class LLMProviderName(StrEnum):
    OLLAMA = "ollama"
    ANTHROPIC = "anthropic"


class AgentRuntimeName(StrEnum):
    #: Deterministic intent router that invokes one skill per turn. Provider-agnostic,
    #: so it is the only runtime that can drive a local Ollama model. Default.
    ROUTER = "router"
    #: Anthropic Claude Agent SDK: the model autonomously selects skills exposed as
    #: in-process MCP tools. Cloud-only — the SDK cannot drive a local Ollama model.
    CLAUDE_AGENT_SDK = "claude_agent_sdk"


class EmbeddingProviderName(StrEnum):
    OLLAMA = "ollama"
    #: Deterministic offline embedder. Test/CI use only — never for real answers.
    HASH = "hash"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- app
    app_name: str = "The Lenny Growth Assistant"
    environment: str = "development"
    log_level: str = "INFO"
    log_format: str = Field(default="json", description="'json' or 'console'")
    #: NoDecode opts out of pydantic-settings' default JSON decoding for complex types, so
    #: CORS_ORIGINS can be the comma-separated list an operator would naturally write
    #: rather than a JSON array. The validator below does the splitting.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )

    # ----------------------------------------------------------- database
    database_url: str = "postgresql+psycopg://lenny:lenny@localhost:5432/lenny"
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_connect_timeout_seconds: int = 5

    # ------------------------------------------------------- llm provider
    llm_provider: LLMProviderName = LLMProviderName.OLLAMA
    #: Loaded from AGENT_RUNTIME for compatibility. Dispatch is by LLM provider
    #: (see ``AgentService.runtime``); this setting is not the runtime selector.
    agent_runtime: AgentRuntimeName = AgentRuntimeName.ROUTER
    llm_timeout_seconds: float = 180.0
    llm_max_output_tokens: int = 4096
    llm_temperature: float = 0.3

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"

    # -------------------------------------------------------- embeddings
    embedding_provider: EmbeddingProviderName = EmbeddingProviderName.OLLAMA
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = 768
    embedding_batch_size: int = 16

    # ------------------------------------------------------------ ingest
    transcripts_dir: str = "data/transcripts"
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 200

    # --------------------------------------------------------- retrieval
    retrieval_top_k: int = 6
    #: Cosine distance ceiling (0 = identical, 2 = opposite). Chunks above this are
    #: treated as irrelevant, which is what triggers the honest refusal.
    retrieval_max_distance: float = 0.55
    retrieval_max_chunks_per_episode: int = 2
    retrieval_context_char_budget: int = 9000
    #: Ship 30 essays need broader evidence than a single Q&A turn.
    essay_top_k: int = 12
    essay_context_char_budget: int = 16000
    #: Higher than the Q&A cap: an essay may legitimately lean on one deep-dive episode.
    essay_max_chunks_per_episode: int = 6
    essay_target_words: int = 1250
    essay_word_tolerance: float = 0.15

    # ----------------------------------------------------------- limits
    max_message_chars: int = 8000
    max_history_messages: int = 12
    max_history_chars: int = 6000

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("log_format")
    @classmethod
    def _validate_log_format(cls, value: str) -> str:
        if value not in {"json", "console"}:
            raise ValueError("LOG_FORMAT must be 'json' or 'console'")
        return value

    @property
    def sync_database_url(self) -> str:
        """Alembic and the ingestion CLI use a synchronous connection."""
        return self.database_url.replace("+asyncpg", "+psycopg")

    def active_model(self, provider: LLMProviderName | None = None) -> str:
        """Model name for the given (or configured) provider, for display and logging."""
        resolved = provider or self.llm_provider
        return self.ollama_model if resolved is LLMProviderName.OLLAMA else self.anthropic_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
