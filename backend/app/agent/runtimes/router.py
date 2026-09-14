"""Deterministic router runtime — the default, and the one the Ollama demo uses.

One turn selects exactly one skill via ``agent/routing.py`` and invokes it. The model is
called *inside* the skill, never to decide control flow.

Why not let the model choose the tool here: the demo must work on an 8B local model, where
tool-call JSON is unreliable and every extra round trip costs ~10-20s. Deterministic
dispatch makes the agent's behaviour predictable, cheap and testable, which the assignment
explicitly prefers ("keep routing explicit", "prefer explicit tool/skill boundaries").
Autonomous tool selection is available via the Claude Agent SDK runtime.
"""

from __future__ import annotations

from app.agent.registry import SkillRegistry
from app.agent.routing import Route, route
from app.agent.types import Intent, SkillContext, SkillResult
from app.core.logging import get_logger

logger = get_logger(__name__)


class RouterRuntime:
    name = "router"

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def plan(self, message: str) -> Route:
        return route(message)

    async def run(self, message: str, context: SkillContext, *, plan: Route | None = None) -> tuple[SkillResult, Route]:
        decision = plan or self.plan(message)
        logger.info("agent_routed", intent=decision.intent.value, reason=decision.reason, runtime=self.name)

        if decision.intent is Intent.SHIP30_ESSAY:
            skill = self._registry.require("generate_ship30_essay")
            result = await skill.run(context, topic=message)
        elif decision.intent is Intent.ARTIFACT:
            skill = self._registry.require("generate_artifact")
            artifact_type = (decision.artifact_type.value if decision.artifact_type else "markdown")
            result = await skill.run(context, artifact_type=artifact_type, instruction=message)
        else:
            skill = self._registry.require("answer_grounded_question")
            result = await skill.run(context, question=message)

        result.meta.setdefault("skill", skill.name)
        result.meta.setdefault("runtime", self.name)
        return result, decision
