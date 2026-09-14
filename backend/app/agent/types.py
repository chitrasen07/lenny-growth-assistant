"""Shared agent types.

A *skill* is a self-contained capability with a JSON schema, callable either directly by
the router or as a tool by an LLM. Both agent runtimes consume the same skill objects,
which is why swapping the runtime does not change product behaviour.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.models.artifact import ArtifactType
from app.providers.base import LLMProvider, ToolSpec
from app.rag.retrieval import RetrievalResult, RetrievalService


class Intent(StrEnum):
    QUESTION = "question"
    SHIP30_ESSAY = "ship30_essay"
    ARTIFACT = "artifact"


@dataclass(slots=True)
class GeneratedArtifact:
    type: ArtifactType
    title: str
    content: str


@dataclass(slots=True)
class SkillContext:
    """Everything a skill may use. Passed explicitly so skills stay unit-testable."""

    provider: LLMProvider
    retrieval: RetrievalService
    #: Prior turns of *this session only*, oldest first, already truncated.
    history: list[tuple[str, str]] = field(default_factory=list)

    def user_turns(self) -> list[str]:
        return [content for role, content in self.history if role == "user"]


@dataclass(slots=True)
class SkillResult:
    text: str
    retrieval: RetrievalResult | None = None
    artifact: GeneratedArtifact | None = None
    #: True when the skill declined for lack of transcript evidence.
    refused: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


class Skill(ABC):
    """One agent capability."""

    name: str
    description: str
    parameters: dict[str, Any]

    @abstractmethod
    async def run(self, context: SkillContext, **kwargs: Any) -> SkillResult: ...

    def to_tool_spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, parameters=self.parameters)
