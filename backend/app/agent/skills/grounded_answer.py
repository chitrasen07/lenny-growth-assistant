"""`answer_grounded_question` — transcript-grounded Q&A with honest refusal."""

from __future__ import annotations

from typing import Any

from app.agent.citations import apply_citations
from app.agent.prompts import GROUNDED_ANSWER_SYSTEM, REFUSAL_MESSAGE
from app.agent.types import Skill, SkillContext, SkillResult
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.providers.base import ChatMessage

logger = get_logger(__name__)


class GroundedAnswerSkill(Skill):
    name = "answer_grounded_question"
    description = (
        "Answer a product management or growth question using Lenny's Podcast transcripts, "
        "citing the excerpts that support each claim. Declines when the transcripts do not "
        "cover the question."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The user's question, made self-contained."}
        },
        "required": ["question"],
    }

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def run(self, context: SkillContext, **kwargs: Any) -> SkillResult:
        question = str(kwargs.get("question", "")).strip()
        if not question:
            return SkillResult(text=REFUSAL_MESSAGE, refused=True)

        retrieval = await context.retrieval.retrieve(question, history=context.user_turns())

        # No evidence clears the relevance threshold: refuse deterministically, without
        # calling the model. This is what stops general model knowledge being presented
        # as if it came from the transcripts.
        if not retrieval.has_evidence:
            logger.info(
                "grounded_answer_refused",
                reason="knowledge_base_empty" if retrieval.knowledge_base_empty else "no_relevant_evidence",
            )
            return SkillResult(
                text=REFUSAL_MESSAGE,
                retrieval=retrieval,
                refused=True,
                meta={"refusal_reason": "knowledge_base_empty" if retrieval.knowledge_base_empty else "below_threshold"},
            )

        messages: list[ChatMessage] = [ChatMessage("system", GROUNDED_ANSWER_SYSTEM)]
        for role, content in context.history:
            messages.append(ChatMessage("assistant" if role == "assistant" else "user", content))
        messages.append(
            ChatMessage(
                "user",
                f"EVIDENCE:\n{retrieval.evidence_block()}\n\n"
                f"QUESTION: {question}\n\n"
                "Answer using only the EVIDENCE above, citing markers inline.",
            )
        )

        response = await context.provider.complete(
            messages,
            max_tokens=self._settings.llm_max_output_tokens,
            temperature=self._settings.llm_temperature,
        )

        text = response.text.strip()
        if not text:
            return SkillResult(
                text=REFUSAL_MESSAGE,
                retrieval=retrieval,
                refused=True,
                meta={"refusal_reason": "empty_model_response"},
            )

        cleaned, cited, dropped = apply_citations(text, retrieval.chunks)
        if not cleaned:
            logger.info("grounded_answer_refused", reason="attribution_unverified")
            return SkillResult(
                text=REFUSAL_MESSAGE,
                retrieval=retrieval,
                refused=True,
                meta={"refusal_reason": "attribution_unverified", "dropped_markers": sorted(dropped)},
            )

        refused = REFUSAL_MESSAGE.lower() in cleaned.lower()

        if dropped:
            logger.warning("citation_markers_dropped", markers=sorted(dropped))
        if not cited and not refused:
            # The answer may still be sound, but it is unverifiable claim by claim, so the
            # UI labels it and the sources panel shows what was retrieved.
            logger.warning("answer_without_citations", retrieved=len(retrieval.chunks))

        return SkillResult(
            text=cleaned,
            retrieval=retrieval,
            refused=refused,
            meta={
                "cited_markers": sorted(cited),
                "dropped_markers": sorted(dropped),
                "uncited_answer": not cited and not refused,
                "model_latency_ms": response.latency_ms,
                "usage": response.usage,
            },
        )
