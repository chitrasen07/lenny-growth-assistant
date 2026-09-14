"""Agent routing and skill registry."""

from __future__ import annotations

import pytest

from app.agent.registry import SkillRegistry
from app.agent.routing import route
from app.agent.types import Intent
from app.models.artifact import ArtifactType


@pytest.mark.parametrize(
    "message",
    [
        "How do I improve activation?",
        "What did the guest say about retention?",
        "Should we hire a growth PM before product-market fit?",
        "Tell me about pricing strategy",  # 'pricing' alone is a question, not an artifact
    ],
)
def test_questions_route_to_grounded_answer(message):  # noqa: ANN001
    assert route(message).intent is Intent.QUESTION


@pytest.mark.parametrize(
    "message",
    [
        "Write a Ship 30 for 30 essay about activation",
        "ship30 essay on retention",
        "Can you draft an essay about onboarding?",
        "Generate an essay on growth loops",
    ],
)
def test_essay_requests_route_to_the_ship30_skill(message):  # noqa: ANN001
    assert route(message).intent is Intent.SHIP30_ESSAY


@pytest.mark.parametrize(
    ("message", "expected_type"),
    [
        ("Create a landing page for this idea", ArtifactType.HTML),
        ("Build me an HTML page with CSS for this", ArtifactType.HTML),
        ("Make a web page showing our positioning", ArtifactType.HTML),
        ("Create a Markdown strategy document", ArtifactType.MARKDOWN),
        ("Generate a one-pager for this", ArtifactType.MARKDOWN),
        ("Draft a playbook from our conversation", ArtifactType.MARKDOWN),
    ],
)
def test_artifact_requests_route_with_the_right_format(message, expected_type):  # noqa: ANN001
    decision = route(message)

    assert decision.intent is Intent.ARTIFACT
    assert decision.artifact_type is expected_type


def test_html_cue_wins_over_markdown_when_both_appear():
    """"Landing page" is the more specific ask than "doc"."""
    decision = route("Create a landing page and a strategy doc")

    assert decision.artifact_type is ArtifactType.HTML


def test_artifact_keyword_without_a_verb_stays_a_question():
    """Asking *about* landing pages is a question, not a request to build one."""
    assert route("What makes a good landing page?").intent is Intent.QUESTION


def test_routing_records_a_reason_for_traceability():
    assert route("Create a landing page").reason
    assert route("How do I improve activation?").reason


def test_registry_exposes_the_four_documented_skills():
    registry = SkillRegistry()

    assert set(registry.names()) == {
        "search_transcripts",
        "answer_grounded_question",
        "generate_ship30_essay",
        "generate_artifact",
    }


def test_registry_produces_valid_tool_schemas():
    """Both runtimes advertise skills as tools, so the schemas must be well formed."""
    for spec in SkillRegistry().tool_specs():
        assert spec.name and spec.description
        assert spec.parameters["type"] == "object"
        assert isinstance(spec.parameters.get("properties"), dict)
        for required in spec.parameters.get("required", []):
            assert required in spec.parameters["properties"]
