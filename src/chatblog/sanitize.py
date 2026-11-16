"""Whitelist based HTML sanitizer for conversation content.

Gemini share pages are rendered by Angular, so the markdown panel we read from
the browser is *real* HTML (``<p>``, ``<ul>``, ``<h3>`` ...) with UI chrome
(citation chips, follow-up buttons) mixed in.  Flattening that to plain text -
which is what the first implementation did - silently destroyed headings and
lists, so the transcript read like one long paragraph.

This module keeps a small, explicit subset of the markup and drops everything
else, so the rendered post looks like the original conversation while staying
safe to embed in a static page:

* only :data:`ALLOWED_TAGS` survive, with only a handful of attributes,
* the content of :data:`DROP_TAGS` (scripts, styles, UI widgets, ...) is
  removed entirely,
* unknown tags are *unwrapped* so their text is preserved,
* URLs are restricted to http(s)/mailto/tel/relative targets.
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser
from typing import Iterable

__all__ = ["ALLOWED_TAGS", "DROP_TAGS", "sanitize_html"]


#: Tags that are kept together with their children.
ALLOWED_TAGS = frozenset(
    {
        "a",
        "b",
        "blockquote",
        "br",
        "code",
        "dd",
        "del",
        "div",
        "dl",
        "dt",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "ins",
        "kbd",
        "li",
        "mark",
        "ol",
        "p",
        "pre",
        "s",
        "samp",
        "small",
        "span",
        "strong",
        "sub",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
        "var",
    }
)

#: Tags that never have children in the emitted HTML.
VOID_TAGS = frozenset({"br", "hr"})

#: Tags whose whole subtree is discarded.
DROP_TAGS = frozenset(
    {
        # document level noise
        "base",
        "head",
        "link",
        "meta",
        "noscript",
        "script",
        "style",
        "template",
        "title",
        # embeds and interactivity
        "applet",
        "area",
        "audio",
        "button",
        "canvas",
        "dialog",
        "embed",
        "form",
        "frame",
        "frameset",
        "iframe",
        "img",
        "input",
        "label",
        "map",
        "math",
        "object",
        "option",
        "picture",
        "select",
        "source",
        "svg",
        "textarea",
        "track",
        "video",
        # Gemini share page widgets (citation chips / follow ups / icons)
        "follow-up",
        "gem-icon",
        "mat-icon",
        "message-actions",
        "response-container-header",
        "source-footnote",
        "source-inline-chip",
        "sources-carousel-inline",
        "tts",
    }
)

#: Attributes kept per tag; everything else (class, style, jslog, ...) is dropped.
ALLOWED_ATTRS: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "title"}),
    "ol": frozenset({"start"}),
    "td": frozenset({"colspan", "rowspan"}),
    "th": frozenset({"colspan", "rowspan"}),
}

_SAFE_URL_SCHEMES = frozenset({"http", "https", "mailto", "tel"})
_UNSAFE_URL_PREFIXES = ("javascript:", "vbscript:", "data:", "blob:")
_CONTROL_CHARS = re.compile(r"[\x00-\x20\u00a0\u202f]+")


def _is_safe_url(value: str) -> bool:
    """Return True for links we are willing to emit into the static site."""
    compact = _CONTROL_CHARS.sub("", value).lower()
    if not compact or compact.startswith("#"):
        return True
    if compact.startswith(_UNSAFE_URL_PREFIXES):
        return False

    scheme = compact.split(":", 1)[0] if ":" in compact.split("/", 1)[0] else ""
    return not scheme or scheme in _SAFE_URL_SCHEMES


def _clean_attrs(tag: str, attrs: Iterable[tuple[str, str | None]]) -> str:
    allowed = ALLOWED_ATTRS.get(tag)
    if not allowed:
        return ""

    rendered: list[str] = []
    for name, value in attrs:
        name = (name or "").lower()
        if name not in allowed or value is None:
            continue
        if name == "href" and not _is_safe_url(value):
            continue
        rendered.append(f' {name}="{escape(value, quote=True)}"')
    return "".join(rendered)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._open: list[str] = []
        self._drop_depth = 0

    # -- helpers ---------------------------------------------------------
    def _emit(self, text: str) -> None:
        if text:
            self.parts.append(text)

    def _emit_start(self, tag: str, attrs: Iterable[tuple[str, str | None]]) -> None:
        if tag in VOID_TAGS:
            self._emit(f"<{tag}>")
            return
        self._emit(f"<{tag}{_clean_attrs(tag, attrs)}>")
        self._open.append(tag)

    # -- HTMLParser hooks ------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if self._drop_depth:
            if tag in DROP_TAGS:
                self._drop_depth += 1
            return
        if tag in DROP_TAGS:
            self._drop_depth = 1
            return
        if tag in ALLOWED_TAGS:
            self._emit_start(tag, attrs)

    def handle_startendtag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if self._drop_depth or tag in DROP_TAGS:
            return
        if tag not in ALLOWED_TAGS:
            return
        if tag in VOID_TAGS:
            self._emit(f"<{tag}>")
        else:
            self._emit(f"<{tag}{_clean_attrs(tag, attrs)}></{tag}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._drop_depth:
            if tag in DROP_TAGS:
                self._drop_depth -= 1
            return
        if tag not in ALLOWED_TAGS or tag in VOID_TAGS or tag not in self._open:
            return
        while self._open:
            current = self._open.pop()
            self._emit(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._drop_depth or not data:
            return
        self._emit(escape(data, quote=False))

    def handle_comment(self, data: str) -> None:  # pragma: no cover - trivial
        return

    def handle_decl(self, decl: str) -> None:  # pragma: no cover - trivial
        return

    def handle_pi(self, data: str) -> None:  # pragma: no cover - trivial
        return

    def close(self) -> None:
        super().close()
        while self._open:
            self._emit(f"</{self._open.pop()}>")


def sanitize_html(raw: str) -> str:
    """Return ``raw`` reduced to the whitelisted conversation markup."""
    if not raw:
        return ""

    parser = _Sanitizer()
    parser.feed(raw)
    parser.close()
    return "".join(parser.parts).strip()
