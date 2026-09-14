"""`search_transcripts` — the only path to knowledge.

Exists as its own skill so that retrieval is (a) reusable by every other skill,
(b) individually testable, and (c) visible in logs as a discrete step. It returns evidence
rather than prose: an LLM never sees the knowledge base except through this skill.
"""

from __future__ import annotations

from typing import Any

from app.agent.types import Skill, SkillContext, SkillResult


class SearchTranscriptsSkill(Skill):
    name = "search_transcripts"
    description = (
        "Search the Lenny's Podcast transcript knowledge base for excerpts relevant to a "
        "topic or question. Returns numbered excerpts with their episode metadata. Use this "
        "before answering any question about product, growth or strategy."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A self-contained search query. Resolve pronouns and follow-up references first.",
            },
            "top_k": {
                "type": "integer",
                "description": "How many excerpts to return (1-12).",
                "minimum": 1,
                "maximum": 12,
            },
        },
        "required": ["query"],
    }

    async def run(self, context: SkillContext, **kwargs: Any) -> SkillResult:
        query = str(kwargs.get("query", "")).strip()
        if not query:
            return SkillResult(text="No query supplied, so no transcripts were searched.", refused=True)

        top_k = kwargs.get("top_k")
        result = await context.retrieval.retrieve(
            query,
            history=context.user_turns(),
            top_k=int(top_k) if isinstance(top_k, int) else None,
        )

        if not result.has_evidence:
            reason = (
                "The knowledge base is empty — no transcripts have been ingested."
                if result.knowledge_base_empty
                else "No excerpt in the knowledge base was relevant enough to this query."
            )
            return SkillResult(text=reason, retrieval=result, refused=True)

        return SkillResult(
            text=result.evidence_block(),
            retrieval=result,
            meta={"chunks": len(result.chunks), "best_distance": result.chunks[0].distance},
        )
