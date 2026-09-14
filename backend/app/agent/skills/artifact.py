"""`generate_artifact` — Markdown or HTML/CSS documents from the conversation.

Artifacts are built from the conversation *plus* transcript evidence when the topic is
covered. Unlike Q&A, missing evidence is not fatal here: "turn our discussion into a
landing page" is a formatting request about the user's own idea. So retrieval is
best-effort, and the prompt requires placeholders instead of invented specifics.
"""

from __future__ import annotations

from typing import Any

from app.agent.citations import apply_citations
from app.agent.prompts import ARTIFACT_SYSTEM_HTML, ARTIFACT_SYSTEM_MARKDOWN
from app.agent.types import GeneratedArtifact, Skill, SkillContext, SkillResult
from app.artifacts.builder import build_artifact
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.artifact import ArtifactType
from app.providers.base import ChatMessage

logger = get_logger(__name__)


class ArtifactSkill(Skill):
    name = "generate_artifact"
    description = (
        "Create a standalone Markdown document or a complete HTML page with CSS from the "
        "current conversation. Use when the user asks for a landing page, web page, strategy "
        "document, one-pager, brief or similar deliverable."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "artifact_type": {
                "type": "string",
                "enum": ["markdown", "html"],
                "description": "'html' for landing/web pages, 'markdown' for documents.",
            },
            "instruction": {
                "type": "string",
                "description": "What the artifact should contain, including relevant conversation context.",
            },
        },
        "required": ["artifact_type", "instruction"],
    }

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def run(self, context: SkillContext, **kwargs: Any) -> SkillResult:
        instruction = str(kwargs.get("instruction", "")).strip()
        if not instruction:
            return SkillResult(text="Tell me what the artifact should contain and I'll build it.", refused=True)

        requested = str(kwargs.get("artifact_type", "markdown")).lower()
        artifact_type = ArtifactType.HTML if requested == "html" else ArtifactType.MARKDOWN

        # Best-effort grounding: absent evidence we still build, but nothing is attributed.
        retrieval = await context.retrieval.retrieve(instruction, history=context.user_turns())
        evidence = retrieval.evidence_block() if retrieval.has_evidence else ""

        system = ARTIFACT_SYSTEM_HTML if artifact_type is ArtifactType.HTML else ARTIFACT_SYSTEM_MARKDOWN
        conversation = self._render_conversation(context)

        prompt_parts: list[str] = []
        if conversation:
            prompt_parts.append(f"CONVERSATION SO FAR:\n{conversation}")
        if evidence:
            prompt_parts.append(f"EVIDENCE (transcript excerpts you may cite):\n{evidence}")
        else:
            prompt_parts.append(
                "No relevant transcript excerpts were found, so do not cite or attribute "
                "anything to the podcast. Build the document from the conversation only."
            )
        prompt_parts.append(f"TASK: {instruction}")

        response = await context.provider.complete(
            [ChatMessage("system", system), ChatMessage("user", "\n\n".join(prompt_parts))],
            max_tokens=max(self._settings.llm_max_output_tokens, 4096),
            temperature=0.5,
        )

        built = build_artifact(response.text, artifact_type, fallback_title=instruction[:120] or "Generated artifact")

        # Citation markers are verified in the artifact body too, so a document cannot
        # display a reference that resolves to nothing.
        content, cited, dropped = (
            apply_citations(built.content, retrieval.chunks)
            if retrieval.has_evidence
            else (built.content, set(), set())
        )

        logger.info(
            "artifact_generated",
            artifact_type=artifact_type.value,
            title=built.title,
            chars=len(content),
            sanitised=built.sanitised,
            sanitiser_modified=bool(built.report and built.report.modified),
            grounded_chunks=len(retrieval.chunks),
        )

        summary = (
            f"I've created a {'HTML page' if artifact_type is ArtifactType.HTML else 'Markdown document'}, "
            f"**{built.title}**, in the Artifact Viewer."
        )
        if built.report and built.report.modified:
            summary += " Unsafe markup was removed before rendering — see the viewer's security note."
        if not retrieval.has_evidence:
            summary += " It is based on our conversation; no transcript sources were close enough to cite."

        return SkillResult(
            text=summary,
            retrieval=retrieval if retrieval.has_evidence else None,
            artifact=GeneratedArtifact(type=artifact_type, title=built.title, content=content),
            meta={
                "artifact_type": artifact_type.value,
                "artifact_chars": len(content),
                "sanitised": built.sanitised,
                "sanitiser_report": built.report.to_dict() if built.report else {},
                "cited_markers": sorted(cited),
                "dropped_markers": sorted(dropped),
                "model_latency_ms": response.latency_ms,
            },
        )

    def _render_conversation(self, context: SkillContext) -> str:
        """Recent turns, newest-biased and length-capped to keep the prompt lean."""
        if not context.history:
            return ""
        lines = [f"{'User' if role == 'user' else 'Assistant'}: {content}" for role, content in context.history[-6:]]
        rendered = "\n\n".join(lines)
        limit = self._settings.max_history_chars
        return rendered if len(rendered) <= limit else rendered[-limit:]
