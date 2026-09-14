"""Transcript ingestion command.

Usage (from the ``backend`` directory, or via docker compose exec backend):

    python -m scripts.ingest                    # index new/changed transcripts
    python -m scripts.ingest --force            # re-embed everything
    python -m scripts.ingest --dir ../data/transcripts
    python -m scripts.ingest --status           # show what is currently indexed

Safe to re-run: unchanged files are skipped by content hash, so adding one transcript only
embeds that transcript.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.core.runtime import configure_event_loop_policy
from app.db.session import dispose_engine, get_session_factory
from app.models.transcript import Transcript, TranscriptChunk
from app.rag.ingestion import IngestionService

logger = get_logger("scripts.ingest")


async def show_status() -> int:
    settings = get_settings()
    async with get_session_factory(settings)() as db:
        transcripts = int(await db.scalar(select(func.count()).select_from(Transcript)) or 0)
        chunks = int(await db.scalar(select(func.count()).select_from(TranscriptChunk)) or 0)
        rows = (
            await db.execute(select(Transcript).order_by(Transcript.ingested_at.desc()).limit(50))
        ).scalars().all()

    print(f"\nKnowledge base: {transcripts} transcript(s), {chunks} chunk(s)")
    print(f"Embedding model: {settings.embedding_model} ({settings.embedding_dimensions} dims)\n")
    if not rows:
        print("Nothing indexed yet. Add files to data/transcripts/ and run: python -m scripts.ingest")
        return 0
    for record in rows:
        details = [f"{record.chunk_count} chunks"]
        if record.guest:
            details.append(f"guest: {record.guest}")
        details.append("url: yes" if record.source_url else "url: none")
        print(f"  - {record.title}  [{record.source_file}]  ({', '.join(details)})")
    print()
    return 0


async def run_ingestion(directory: str | None, force: bool) -> int:
    settings = get_settings()
    async with get_session_factory(settings)() as db:
        report = await IngestionService(db, settings).ingest_directory(directory, force=force)

    print("\n" + report.summary() + "\n")
    if report.failures:
        # Non-zero exit so a scripted or CI run notices partial failure.
        return 1
    if report.processed == 0 and report.skipped == 0:
        print(
            f"No transcript files found in '{directory or settings.transcripts_dir}'.\n"
            "Add .txt/.md/.vtt/.srt/.json transcripts there — see docs/transcripts.md."
        )
        return 1
    return 0


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Ingest Lenny's Podcast transcripts into the vector index.")
    parser.add_argument("--dir", dest="directory", default=None, help="Transcript directory (default: TRANSCRIPTS_DIR)")
    parser.add_argument("--force", action="store_true", help="Re-chunk and re-embed even if unchanged")
    parser.add_argument("--status", action="store_true", help="Show what is currently indexed and exit")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, "console")

    try:
        return await show_status() if args.status else await run_ingestion(args.directory, args.force)
    except AppError as exc:
        print(f"\nIngestion failed: {exc.message}", file=sys.stderr)
        if exc.remedy:
            print(f"  → {exc.remedy}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - top-level CLI guard
        logger.exception("ingestion_crashed", error_type=type(exc).__name__)
        print(f"\nUnexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        await dispose_engine()


def main() -> None:
    configure_event_loop_policy()
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
