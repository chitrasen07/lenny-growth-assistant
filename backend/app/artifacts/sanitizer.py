"""HTML sanitisation for generated artifacts.

Model output is untrusted input. This module is layer 2 of a three-layer defence:

  1. the prompt forbids scripting (helpful, but not a control);
  2. **this allowlist sanitiser**, which is what actually removes dangerous constructs;
  3. the frontend renders the result in ``<iframe sandbox srcdoc>`` *without*
     ``allow-scripts``, so even a sanitiser miss cannot execute JavaScript.

Why an allowlist parser rather than an off-the-shelf HTML cleaner: the assignment requires
generating full HTML **with CSS**, and general-purpose cleaners such as bleach escape the
contents of ``<style>``, which breaks every generated page. So the allowlist is explicit
here and ``<style>`` text is preserved after being filtered for CSS-borne script vectors.

What is allowed: document structure, text semantics, tables, lists, links, images, and
inline/embedded CSS.
What is blocked: ``script``/``iframe``/``object``/``embed``/``form``/``link``/``base``/
``svg``/``math``, every ``on*`` handler, ``javascript:``/``vbscript:``/``data:`` URLs
(except ``data:image``), CSS ``@import``, ``expression()`` and ``url(javascript:...)``.

Limitations (documented honestly): this is a syntactic filter, not a browser. It does not
attempt to defeat every mutation-XSS trick, which is precisely why the sandboxed,
script-disabled iframe — not this file — is the primary containment boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment
from bs4.element import Tag

ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "html", "head", "body", "title", "style", "meta",
        "header", "nav", "main", "section", "article", "aside", "footer", "div", "span",
        "h1", "h2", "h3", "h4", "h5", "h6", "p", "br", "hr",
        "ul", "ol", "li", "dl", "dt", "dd",
        "a", "strong", "em", "b", "i", "u", "s", "small", "mark", "sup", "sub", "abbr", "time",
        "code", "pre", "blockquote", "cite", "q",
        "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col",
        "figure", "figcaption", "img", "picture", "source",
        "button", "label",
    }
)

#: Tags whose entire subtree is discarded, since their text content is itself a payload.
DROP_WITH_CONTENT: frozenset[str] = frozenset(
    {"script", "iframe", "object", "embed", "applet", "form", "input", "textarea", "select",
     "option", "link", "base", "svg", "math", "template", "noscript", "frame", "frameset"}
)

GLOBAL_ATTRIBUTES: frozenset[str] = frozenset({"class", "id", "style", "title", "lang", "dir", "role"})
TAG_ATTRIBUTES: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "target", "rel"}),
    "img": frozenset({"src", "alt", "width", "height", "loading"}),
    "source": frozenset({"srcset", "media", "type"}),
    "th": frozenset({"colspan", "rowspan", "scope"}),
    "td": frozenset({"colspan", "rowspan"}),
    "col": frozenset({"span"}),
    "colgroup": frozenset({"span"}),
    "time": frozenset({"datetime"}),
    "meta": frozenset({"charset", "name", "content"}),
    "button": frozenset({"type", "disabled"}),
    "label": frozenset({"for"}),
    "abbr": frozenset({"title"}),
}

_DANGEROUS_URL = re.compile(r"^\s*(?:javascript|vbscript|file|about|blob)\s*:", re.IGNORECASE)
_DATA_URL = re.compile(r"^\s*data\s*:", re.IGNORECASE)
_SAFE_DATA_IMAGE = re.compile(r"^\s*data:image/(?:png|jpe?g|gif|webp|svg\+xml);base64,", re.IGNORECASE)
# Whole at-rules/declarations are removed rather than just the offending keyword, so no
# attacker-supplied URL survives as leftover text in the document.
_CSS_THREAT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # @import can load remote CSS (exfiltration + style injection).
    re.compile(r"@import[^;{}]*(?:;|(?=\})|$)", re.IGNORECASE),
    # Legacy IE script execution via CSS values.
    re.compile(r"[\w-]+\s*:[^;{}]*expression\s*\([^;{}]*(?:;|(?=\})|$)", re.IGNORECASE),
    # url(javascript:...) / url(vbscript:...) in any declaration.
    re.compile(
        r"[\w-]+\s*:[^;{}]*url\s*\(\s*['\"]?\s*(?:javascript|vbscript)\s*:[^;{}]*(?:;|(?=\})|$)",
        re.IGNORECASE,
    ),
    # Properties that bind behaviour/scripts to elements.
    re.compile(r"(?:-moz-binding|behaviou?r)\s*:[^;{}]*(?:;|(?=\})|$)", re.IGNORECASE),
)
_META_ALLOWED_NAMES = frozenset({"viewport", "description", "author", "color-scheme", "theme-color"})

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data: https:; "
    "font-src data:; base-uri 'none'; form-action 'none'; frame-src 'none'; "
    "object-src 'none'; script-src 'none'"
)


@dataclass(slots=True)
class SanitisationReport:
    """What the sanitiser changed. Surfaced in the Artifact Viewer, not just logged."""

    removed_tags: dict[str, int] = field(default_factory=dict)
    removed_attributes: dict[str, int] = field(default_factory=dict)
    removed_urls: int = 0
    css_rules_stripped: int = 0
    comments_removed: int = 0

    def record_tag(self, name: str) -> None:
        self.removed_tags[name] = self.removed_tags.get(name, 0) + 1

    def record_attribute(self, name: str) -> None:
        self.removed_attributes[name] = self.removed_attributes.get(name, 0) + 1

    @property
    def modified(self) -> bool:
        return bool(
            self.removed_tags or self.removed_attributes or self.removed_urls
            or self.css_rules_stripped or self.comments_removed
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "removed_tags": self.removed_tags,
            "removed_attributes": self.removed_attributes,
            "removed_urls": self.removed_urls,
            "css_rules_stripped": self.css_rules_stripped,
            "comments_removed": self.comments_removed,
            "modified": self.modified,
        }


def _is_unsafe_url(value: str, *, allow_data_image: bool = False) -> bool:
    if _DANGEROUS_URL.match(value):
        return True
    if _DATA_URL.match(value):
        return not (allow_data_image and _SAFE_DATA_IMAGE.match(value))
    return False


def _sanitise_css(css: str, report: SanitisationReport) -> str:
    cleaned = css
    for pattern in _CSS_THREAT_PATTERNS:
        cleaned, count = pattern.subn("", cleaned)
        if count:
            report.css_rules_stripped += count
    return cleaned


def _sanitise_attributes(tag: Tag, report: SanitisationReport) -> None:
    allowed = GLOBAL_ATTRIBUTES | TAG_ATTRIBUTES.get(tag.name, frozenset())
    for name in list(tag.attrs):
        lowered = name.lower()
        value = tag.attrs[name]
        raw = " ".join(value) if isinstance(value, list) else str(value)

        # Event handlers are the single most common injection vector.
        if lowered.startswith("on"):
            report.record_attribute(lowered)
            del tag.attrs[name]
            continue
        # aria-* and data-* are inert and useful for accessibility.
        if lowered.startswith(("aria-", "data-")):
            continue
        if lowered not in allowed:
            report.record_attribute(lowered)
            del tag.attrs[name]
            continue
        if lowered in {"href", "src", "srcset", "action", "formaction"}:
            if _is_unsafe_url(raw, allow_data_image=(lowered in {"src", "srcset"})):
                report.removed_urls += 1
                del tag.attrs[name]
                continue
        if lowered == "style":
            tag.attrs[name] = _sanitise_css(raw, report)
        if lowered == "target":
            # Prevent reverse tabnabbing on any link that opens a new context.
            tag.attrs["rel"] = "noopener noreferrer"

    if tag.name == "meta":
        name_attr = str(tag.attrs.get("name", "")).lower()
        if "charset" not in tag.attrs and name_attr not in _META_ALLOWED_NAMES:
            # http-equiv refreshes and unknown meta directives are dropped entirely.
            report.record_tag("meta")
            tag.decompose()


def sanitise_html(raw: str) -> tuple[str, SanitisationReport]:
    """Return a sanitised standalone HTML document and a report of what was removed."""
    report = SanitisationReport()
    soup = BeautifulSoup(raw or "", "html.parser")

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        report.comments_removed += 1
        comment.extract()

    for tag in soup.find_all(True):
        if not isinstance(tag, Tag) or tag.decomposed:
            continue
        name = tag.name.lower()
        if name in DROP_WITH_CONTENT:
            report.record_tag(name)
            tag.decompose()
            continue
        if name not in ALLOWED_TAGS:
            # Unknown but harmless wrapper: keep the text, drop the element.
            report.record_tag(name)
            tag.unwrap()

    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and not tag.decomposed:
            _sanitise_attributes(tag, report)

    for style in soup.find_all("style"):
        if isinstance(style, Tag) and style.string:
            style.string.replace_with(_sanitise_css(str(style.string), report))

    return _wrap_document(soup, raw), report


def _wrap_document(soup: BeautifulSoup, original: str) -> str:
    """Ensure a complete document with charset, viewport and the CSP meta present."""
    body_html = str(soup).strip()
    has_html_root = "<html" in original.lower()

    if not has_html_root:
        return (
            "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
            f'<meta charset="utf-8">\n'
            f'<meta http-equiv="Content-Security-Policy" content="{CONTENT_SECURITY_POLICY}">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            "</head>\n<body>\n"
            f"{body_html}\n</body>\n</html>"
        )

    # The CSP meta is injected here rather than trusted from model output.
    document = BeautifulSoup(body_html, "html.parser")
    head = document.find("head")
    if head is None:
        html_root = document.find("html")
        head = document.new_tag("head")
        if isinstance(html_root, Tag):
            html_root.insert(0, head)
        else:
            document.insert(0, head)
    if isinstance(head, Tag):
        if not head.find("meta", attrs={"charset": True}):
            head.insert(0, document.new_tag("meta", attrs={"charset": "utf-8"}))
        csp = document.new_tag("meta")
        csp.attrs["http-equiv"] = "Content-Security-Policy"
        csp.attrs["content"] = CONTENT_SECURITY_POLICY
        head.insert(0, csp)
        if not head.find("meta", attrs={"name": "viewport"}):
            head.append(document.new_tag("meta", attrs={"name": "viewport", "content": "width=device-width, initial-scale=1"}))

    rendered = str(document).strip()
    if not rendered.lower().startswith("<!doctype"):
        rendered = f"<!DOCTYPE html>\n{rendered}"
    return rendered
