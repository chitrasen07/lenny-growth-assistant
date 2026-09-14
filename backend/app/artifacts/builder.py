"""Artifact post-processing: unwrap, validate, title, sanitise.

Models frequently wrap a document in ``` fences or add a sentence of commentary; the
artifact contract promises a renderable document, so that packaging is stripped here
rather than being left for the frontend to guess at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.artifacts.sanitizer import SanitisationReport, sanitise_html
from app.core.errors import ArtifactGenerationError
from app.core.logging import get_logger
from app.models.artifact import ArtifactType

logger = get_logger(__name__)

#: Guards the database and the browser against a runaway generation.
MAX_ARTIFACT_CHARS = 200_000

_FENCE_PATTERN = re.compile(r"^\s*```[a-zA-Z]*\s*\n(?P<body>.*?)\n?\s*```\s*$", re.DOTALL)
_HTML_START = re.compile(r"<!DOCTYPE\s+html|<html[\s>]", re.IGNORECASE)


def strip_code_fence(text: str) -> str:
    match = _FENCE_PATTERN.match(text.strip())
    return match.group("body").strip() if match else text.strip()


def _extract_html_document(text: str) -> str:
    """Discard prose surrounding an HTML document."""
    match = _HTML_START.search(text)
    if match:
        text = text[match.start() :]
    closing = text.lower().rfind("</html>")
    if closing != -1:
        text = text[: closing + len("</html>")]
    return text.strip()


def derive_title(content: str, artifact_type: ArtifactType, fallback: str) -> str:
    if artifact_type is ArtifactType.MARKDOWN:
        for line in content.split("\n"):
            if line.strip().startswith("# "):
                return line.strip()[2:].strip()[:200] or fallback
    else:
        match = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
        if match and match.group(1).strip():
            return re.sub(r"\s+", " ", match.group(1)).strip()[:200]
        match = re.search(r"<h1[^>]*>(.*?)</h1>", content, re.IGNORECASE | re.DOTALL)
        if match:
            text = re.sub(r"<[^>]+>", "", match.group(1))
            if text.strip():
                return re.sub(r"\s+", " ", text).strip()[:200]
    return fallback[:200]


@dataclass(slots=True)
class BuiltArtifact:
    type: ArtifactType
    title: str
    content: str
    sanitised: bool
    report: SanitisationReport | None = None


def build_artifact(raw: str, artifact_type: ArtifactType, *, fallback_title: str) -> BuiltArtifact:
    """Validate and normalise raw model output into a renderable artifact."""
    content = strip_code_fence(raw or "")
    if not content.strip():
        raise ArtifactGenerationError(
            "The model returned an empty artifact.",
            remedy="Retry, or describe the artifact you want in more detail.",
        )
    if len(content) > MAX_ARTIFACT_CHARS:
        raise ArtifactGenerationError(
            f"The generated artifact exceeded the {MAX_ARTIFACT_CHARS:,} character limit.",
            remedy="Ask for a smaller or more focused document.",
        )

    if artifact_type is ArtifactType.HTML:
        content = _extract_html_document(content)
        if not _HTML_START.search(content):
            raise ArtifactGenerationError(
                "The model did not return an HTML document.",
                remedy="Retry, or ask explicitly for 'a complete HTML page with CSS'.",
            )
        sanitised, report = sanitise_html(content)
        title = derive_title(sanitised, artifact_type, fallback_title)
        if report.modified:
            logger.warning("artifact_sanitised", **{k: v for k, v in report.to_dict().items() if k != "modified"})
        return BuiltArtifact(artifact_type, title, sanitised, sanitised=True, report=report)

    return BuiltArtifact(
        artifact_type,
        derive_title(content, artifact_type, fallback_title),
        content,
        sanitised=False,
    )
