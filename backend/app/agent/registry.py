"""Skill registry — the single source of truth for what the agent can do.

Both runtimes read from this registry, so a skill added here is immediately available to
the deterministic router *and* as a Claude Agent SDK tool, with no duplicated wiring.
"""

from __future__ import annotations

from app.agent.skills.artifact import ArtifactSkill
from app.agent.skills.grounded_answer import GroundedAnswerSkill
from app.agent.skills.search import SearchTranscriptsSkill
from app.agent.skills.ship30 import Ship30EssaySkill
from app.agent.types import Skill
from app.core.config import Settings, get_settings
from app.providers.base import ToolSpec


class SkillRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self._skills: dict[str, Skill] = {
            skill.name: skill
            for skill in (
                SearchTranscriptsSkill(),
                GroundedAnswerSkill(settings),
                Ship30EssaySkill(settings),
                ArtifactSkill(settings),
            )
        }

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def require(self, name: str) -> Skill:
        skill = self._skills.get(name)
        if skill is None:  # pragma: no cover - guards against a typo in routing
            raise KeyError(f"Unknown skill '{name}'")
        return skill

    def names(self) -> list[str]:
        return list(self._skills)

    def tool_specs(self) -> list[ToolSpec]:
        return [skill.to_tool_spec() for skill in self._skills.values()]

    def describe(self) -> list[dict[str, str]]:
        """Skill inventory for the ``/api/config`` endpoint, so the UI can show it."""
        return [{"name": skill.name, "description": skill.description} for skill in self._skills.values()]
