"""Intent routing.

Routing is deliberately deterministic rather than an LLM classification call:

* it costs no tokens and adds no latency;
* it cannot fail because an 8B local model emitted malformed JSON, which matters because
  the demo runs on Ollama;
* an evaluator can read the whole routing table on one screen and predict the behaviour.

The trade-off is less flexibility on unusual phrasings; when Anthropic is selected,
``ClaudeAgentSDKRuntime`` can still choose a different skill.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.agent.types import Intent
from app.models.artifact import ArtifactType

_SHIP30_PATTERN = re.compile(
    r"\b(ship\s*30(?:\s*for\s*30)?|ship\s*thirty)\b|\b(?:write|draft|generate|create)\b[^.?!]{0,40}\bessay\b",
    re.IGNORECASE,
)
_HTML_PATTERN = re.compile(
    r"\b(landing\s*page|web\s*page|webpage|html|css|hero\s*section|micro\s*site|microsite|site\s*mock)\b",
    re.IGNORECASE,
)
_MARKDOWN_PATTERN = re.compile(
    r"\b(markdown|md\s+(?:doc|file)|one[\s-]?pager|strategy\s+doc\w*|brief|checklist|readme|memo|playbook)\b",
    re.IGNORECASE,
)
_ARTIFACT_VERB = re.compile(
    r"\b(create|generate|build|make|produce|draft|design|mock\s*up|turn\s+(?:this|that)\s+into|write\s+me)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class Route:
    intent: Intent
    artifact_type: ArtifactType | None = None
    #: Short explanation recorded in logs and message metadata for traceability.
    reason: str = ""


def route(message: str) -> Route:
    """Classify a user message into the skill that should handle it."""
    text = message.strip()

    if _SHIP30_PATTERN.search(text):
        return Route(Intent.SHIP30_ESSAY, reason="matched Ship 30 for 30 / essay request")

    wants_html = bool(_HTML_PATTERN.search(text))
    wants_markdown = bool(_MARKDOWN_PATTERN.search(text))
    if (wants_html or wants_markdown) and _ARTIFACT_VERB.search(text):
        # An explicit HTML/landing-page cue wins, since that is the more specific ask.
        artifact_type = ArtifactType.HTML if wants_html else ArtifactType.MARKDOWN
        return Route(
            Intent.ARTIFACT,
            artifact_type=artifact_type,
            reason=f"matched artifact request ({artifact_type.value})",
        )

    return Route(Intent.QUESTION, reason="default grounded question")
