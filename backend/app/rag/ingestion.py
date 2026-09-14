"""Transcript ingestion pipeline: load → clean → chunk → embed → index.

Idempotency is enforced with a content hash per source file. Re-running ingestion after
adding one new transcript embeds only that transcript; an edited file has its chunks
replaced in a single transaction, so the index never contains a half-updated episode.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import EmbeddingError, IngestionError
from app.core.logging import get_logger
from app.models.transcript import Transcript, TranscriptChunk
from app.rag.chunking import chunk_transcript
from app.rag.embeddings import Embedder, get_embedder
from app.rag.loader import LoadedTranscript, load_transcripts

logger = get_logger(__name__)


@dataclass(slots=True)
class IngestionReport:
    indexed: int = 0
    skipped: int = 0
    updated: int = 0
    chunks_written: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)
    duration_ms: int = 0

    @property
    def processed(self) -> int:
        return self.indexed + self.updated

    def summary(self) -> str:
        lines = [
            f"indexed {self.indexed} new, updated {self.updated}, skipped {self.skipped} unchanged",
            f"{self.chunks_written} chunks embedded in {self.duration_ms / 1000:.1f}s",
        ]
        if self.failures:
            lines.append(f"{len(self.failures)} failed:")
            lines.extend(f"  - {name}: {reason}" for name, reason in self.failures)
        return "\n".join(lines)


class IngestionService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None, embedder: Embedder | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._embedder = embedder or get_embedder(self._settings)

    async def ingest_directory(self, directory: str | None = None, *, force: bool = False) -> IngestionReport:
        started = time.perf_counter()
        root = directory or self._settings.transcripts_dir
        transcripts = load_transcripts(root)

        report = IngestionReport()
        if not transcripts:
            report.duration_ms = int((time.perf_counter() - started) * 1000)
            logger.warning("ingestion_no_transcripts", directory=str(root))
            return report

        logger.info("ingestion_started", directory=str(root), files=len(transcripts), force=force)
        for transcript in transcripts:
            try:
                await self._ingest_one(transcript, report, force=force)
            except (IngestionError, EmbeddingError) as exc:
                # One bad file must not abandon the rest of the corpus.
                await self._session.rollback()
                report.failures.append((transcript.source_file, exc.message))
                logger.error("ingestion_file_failed", source_file=transcript.source_file, error=exc.message)

        report.duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "ingestion_completed",
            indexed=report.indexed,
            updated=report.updated,
            skipped=report.skipped,
            chunks=report.chunks_written,
            failures=len(report.failures),
            duration_ms=report.duration_ms,
        )
        return report

    async def _ingest_one(self, loaded: LoadedTranscript, report: IngestionReport, *, force: bool) -> None:
        existing = await self._session.scalar(select(Transcript).where(Transcript.source_file == loaded.source_file))
        content_hash = loaded.content_hash

        if existing and existing.content_hash == content_hash and not force:
            report.skipped += 1
            logger.debug("ingestion_skipped_unchanged", source_file=loaded.source_file)
            return

        cleaned, chunks = chunk_transcript(
            loaded.raw_text,
            chunk_size=self._settings.chunk_size_chars,
            overlap=self._settings.chunk_overlap_chars,
        )
        if not chunks:
            raise IngestionError(
                f"'{loaded.source_file}' produced no usable text after cleaning.",
                remedy="Check the file is a transcript and not only timestamps or metadata.",
            )

        vectors = await self._embedder.embed_documents([chunk.content for chunk in chunks])
        if len(vectors) != len(chunks):
            raise IngestionError(
                f"Embedded {len(vectors)} vectors for {len(chunks)} chunks in '{loaded.source_file}'."
            )

        if existing:
            # Replace wholesale: chunk boundaries shift when the text changes, so stale
            # chunks cannot be matched up positionally.
            await self._session.execute(delete(TranscriptChunk).where(TranscriptChunk.transcript_id == existing.id))
            existing.content_hash = content_hash
            existing.title = loaded.title
            existing.episode = loaded.episode
            existing.guest = loaded.guest
            existing.source_url = loaded.source_url
            existing.chunk_count = len(chunks)
            transcript = existing
            report.updated += 1
        else:
            transcript = Transcript(
                source_file=loaded.source_file,
                content_hash=content_hash,
                title=loaded.title,
                episode=loaded.episode,
                guest=loaded.guest,
                source_url=loaded.source_url,
                chunk_count=len(chunks),
            )
            self._session.add(transcript)
            await self._session.flush()
            report.indexed += 1

        self._session.add_all(
            [
                TranscriptChunk(
                    transcript_id=transcript.id,
                    chunk_index=chunk.index,
                    content=chunk.content,
                    speaker=chunk.speaker,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    token_estimate=chunk.token_estimate,
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]
        )
        await self._session.commit()

        report.chunks_written += len(chunks)
        logger.info(
            "ingestion_file_indexed",
            source_file=loaded.source_file,
            title=loaded.title,
            chunks=len(chunks),
            cleaned_chars=len(cleaned),
            updated=bool(existing),
        )
