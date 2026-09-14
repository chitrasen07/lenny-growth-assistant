"""Transcript file discovery and metadata extraction.

Metadata is only ever *read*, never inferred. If a file does not declare its guest or
source URL, those fields stay ``None`` and the UI simply omits them — an invented episode
name or URL would make a citation untrustworthy, which defeats the point of the product.

Supported inputs (see docs/transcripts.md):
  - ``.txt`` / ``.md``  optional YAML front matter
  - ``.vtt`` / ``.srt`` subtitle exports (cues stripped during cleaning)
  - ``.json``           ``{"title": ..., "transcript": ...}`` or a list of such objects
  - ``metadata.json``   sidecar mapping filename -> metadata, for plain text drops
"""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import IngestionError
from app.core.logging import get_logger

logger = get_logger(__name__)

SUPPORTED_SUFFIXES = {".txt", ".md", ".vtt", ".srt", ".json"}
SIDECAR_FILENAME = "metadata.json"
_METADATA_KEYS = {"title", "episode", "guest", "source_url", "url"}
#: Documentation that lives alongside the corpus. Indexing these would put our own
#: instructions into the knowledge base and let the assistant "cite" a README.
_IGNORED_STEMS = {"readme", "license", "licence", "contributing", "changelog", "notes"}


@dataclass(slots=True)
class LoadedTranscript:
    source_file: str
    raw_text: str
    title: str
    episode: str | None = None
    guest: str | None = None
    source_url: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest()


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Parse a leading ``---`` YAML block. Only flat ``key: value`` pairs are supported."""
    if not text.lstrip().startswith("---"):
        return {}, text
    stripped = text.lstrip()
    parts = stripped.split("---", 2)
    if len(parts) < 3:
        return {}, text
    metadata: dict[str, str] = {}
    for line in parts[1].strip().split("\n"):
        if ":" not in line or line.strip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key in _METADATA_KEYS:
            metadata[key] = value.strip().strip("\"'")
    return metadata, parts[2].lstrip("\n")


def _title_from_filename(path: Path) -> str:
    stem = re.sub(r"[_\-]+", " ", path.stem).strip()
    return re.sub(r"\s{2,}", " ", stem).title() or path.name


def _apply(record: dict[str, str], transcript: LoadedTranscript) -> None:
    if record.get("title"):
        transcript.title = record["title"]
    if record.get("episode"):
        transcript.episode = record["episode"]
    if record.get("guest"):
        transcript.guest = record["guest"]
    url = record.get("source_url") or record.get("url")
    if url:
        transcript.source_url = url


def _load_json(path: Path, relative: str) -> list[LoadedTranscript]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestionError(f"Could not parse JSON transcript '{relative}': {exc}") from exc

    records = payload if isinstance(payload, list) else [payload]
    loaded: list[LoadedTranscript] = []
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            raise IngestionError(f"'{relative}' entry {position} is not a JSON object.")
        body = record.get("transcript") or record.get("text") or record.get("content")
        if not isinstance(body, str) or not body.strip():
            raise IngestionError(
                f"'{relative}' entry {position} has no transcript text.",
                remedy="Provide a 'transcript', 'text' or 'content' string field.",
            )
        # Multiple episodes in one file need distinct source_file keys to stay idempotent.
        source_file = relative if len(records) == 1 else f"{relative}#{position}"
        transcript = LoadedTranscript(source_file=source_file, raw_text=body, title=_title_from_filename(path))
        _apply({str(k).lower(): str(v) for k, v in record.items() if v is not None}, transcript)
        loaded.append(transcript)
    return loaded


def load_transcripts(directory: str | Path) -> list[LoadedTranscript]:
    """Load every supported transcript under ``directory``.

    Raises :class:`IngestionError` when the directory is missing so the ingestion command
    fails loudly rather than reporting a successful run over zero files.
    """
    root = Path(directory)
    if not root.exists():
        raise IngestionError(
            f"Transcript directory '{root}' does not exist.",
            remedy="Create data/transcripts/ and add transcript files. See docs/transcripts.md.",
        )

    sidecar: dict[str, dict[str, str]] = {}
    sidecar_path = root / SIDECAR_FILENAME
    if sidecar_path.exists():
        try:
            raw = json.loads(sidecar_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                sidecar = {
                    str(name): {str(k).lower(): str(v) for k, v in record.items() if v is not None}
                    for name, record in raw.items()
                    if isinstance(record, dict)
                }
        except (OSError, json.JSONDecodeError) as exc:
            raise IngestionError(f"Could not parse {SIDECAR_FILENAME}: {exc}") from exc

    transcripts: list[LoadedTranscript] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if path.name == SIDECAR_FILENAME or path.stem.lower() in _IGNORED_STEMS:
            continue

        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() == ".json":
            transcripts.extend(_load_json(path, relative))
            continue

        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise IngestionError(f"Could not read '{relative}': {exc}") from exc

        front_matter, body = _parse_front_matter(raw)
        if not body.strip():
            logger.warning("transcript_empty", source_file=relative)
            continue

        transcript = LoadedTranscript(source_file=relative, raw_text=body, title=_title_from_filename(path))
        _apply(front_matter, transcript)
        # Sidecar entries win over the filename-derived title but not over front matter.
        for key in (relative, path.name):
            if key in sidecar:
                record = dict(sidecar[key])
                if front_matter:
                    record = {k: v for k, v in record.items() if k not in front_matter}
                _apply(record, transcript)
                break

        if not transcript.source_url:
            transcript.warnings.append("no source_url declared; citations will show the file name only")
        transcripts.append(transcript)

    for transcript in transcripts:
        for warning in transcript.warnings:
            logger.info("transcript_metadata_incomplete", source_file=transcript.source_file, warning=warning)

    return transcripts
