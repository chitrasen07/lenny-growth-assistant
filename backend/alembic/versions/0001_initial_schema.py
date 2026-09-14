"""Initial schema: sessions, messages, citations, transcripts, chunks, artifacts.

Revision ID: 0001
Revises:
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.core.config import get_settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DIMENSIONS = get_settings().embedding_dimensions


def upgrade() -> None:
    # Requires the pgvector/pgvector image (or the extension installed) — see docker-compose.yml.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False, server_default="New chat"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sessions_updated_at", "sessions", ["updated_at"])

    op.create_table(
        "transcripts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_file", sa.String(length=500), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("episode", sa.String(length=300), nullable=True),
        sa.Column("guest", sa.String(length=300), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "transcript_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("transcript_id", sa.Uuid(), sa.ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("speaker", sa.String(length=200), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", Vector(_DIMENSIONS), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("transcript_id", "chunk_index", name="uq_chunk_position"),
    )
    op.create_index("ix_chunk_transcript", "transcript_chunks", ["transcript_id", "chunk_index"])
    # HNSW gives good recall for cosine search and, unlike ivfflat, needs no training
    # pass — so it works on an index that starts empty and grows as transcripts arrive.
    op.execute(
        "CREATE INDEX ix_chunk_embedding_hnsw ON transcript_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # Conversation order comes from this sequence, not from created_at: PostgreSQL's
    # now() is transaction-scoped, so messages written together share a timestamp.
    op.execute("CREATE SEQUENCE IF NOT EXISTS messages_seq")
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "seq",
            sa.BigInteger(),
            server_default=sa.text("nextval('messages_seq')"),
            nullable=False,
        ),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])
    op.create_index("ix_messages_session_seq", "messages", ["session_id", "seq"])

    op.create_table(
        "message_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "chunk_id", sa.Uuid(), sa.ForeignKey("transcript_chunks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("distance", sa.Float(), nullable=False),
        sa.Column("cited", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_message_sources_message_id", "message_sources", ["message_id"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sanitised", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sanitiser_report", sa.dialects.postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_artifacts_session_id", "artifacts", ["session_id"])
    op.create_index("ix_artifacts_message_id", "artifacts", ["message_id"])


def downgrade() -> None:
    op.drop_table("artifacts")
    op.drop_table("message_sources")
    op.drop_table("messages")
    op.execute("DROP SEQUENCE IF EXISTS messages_seq")
    op.execute("DROP INDEX IF EXISTS ix_chunk_embedding_hnsw")
    op.drop_table("transcript_chunks")
    op.drop_table("transcripts")
    op.drop_table("sessions")
