from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

import httpx

from .models import Conversation, DialogNode, ImageAttachment
from .sanitize import sanitize_html


DEFAULT_MODEL = "Gemini"

#: English month names as used by the (en-US) share header.
_DATE_PATTERN = r"[A-Z][a-z]{2,8}\.? \d{1,2}, \d{4}(?: at \d{1,2}:\d{2} ?[AP]M)?"
_CREATED_PATTERN = re.compile(r"Created with\s+(?P<model>.+?)\s+(?P<date>" + _DATE_PATTERN + r")")
_PUBLISHED_PATTERN = re.compile(r"Published\s+(?P<date>" + _DATE_PATTERN + r")")
_DATETIME_FORMATS = (
    "%B %d, %Y at %I:%M %p",
    "%b %d, %Y at %I:%M %p",
    "%B %d, %Y, %I:%M %p",
    "%B %d, %Y at %H:%M",
    "%B %d, %Y",
    "%b %d, %Y",
)
_WHITESPACE = re.compile(r"[\s\u00a0\u202f]+")


@dataclass(frozen=True)
class GeminiTurn:
    """One user prompt plus the rendered answer Gemini served for it."""

    user: str
    assistant_html: str
    images: list[ImageAttachment] = field(default_factory=list)


@dataclass(frozen=True)
class GeminiShareData:
    url: str
    title: str
    model: str
    created_at: datetime | None
    published_at: datetime | None
    turns: list[GeminiTurn]


def canonicalize_gemini_share_url(url: str) -> str:
    """Resolve short ``share.gemini.google`` links to their canonical URL."""
    parsed = urlparse(url)
    if parsed.netloc == "share.gemini.google":
        try:
            response = httpx.get(url, follow_redirects=True, timeout=30)
            response.raise_for_status()
        except httpx.HTTPError:
            return url

        canonical = re.search(
            r'<link\b[^>]*\brel="canonical"[^>]*\bhref="([^"]+)"',
            response.text,
        )
        if canonical:
            return canonical.group(1)

        og_url = re.search(r'<meta\b[^>]*\bproperty="og:url"[^>]*\bcontent="([^"]+)"', response.text)
        if og_url:
            return og_url.group(1)

        return str(response.url)
    if parsed.netloc.endswith("gemini.google.com") and parsed.path.startswith("/share/"):
        share_id = parsed.path.removeprefix("/share/").strip("/")
        return f"https://gemini.google.com/share/{share_id}"
    return url


def extract_share_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc == "share.gemini.google":
        return parsed.path.strip("/") or url
    if parsed.path.startswith("/share/"):
        return parsed.path.removeprefix("/share/").strip("/") or url
    return url


def _normalize_whitespace(value: str) -> str:
    """Collapse the exotic spaces Google uses in share headers."""
    return _WHITESPACE.sub(" ", value or "").strip()


def parse_gemini_datetime(value: str) -> datetime | None:
    value = _normalize_whitespace(value)
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def parse_model_name(text: str) -> str:
    """Read the model label out of a ``Created with <model> <date>`` string."""
    match = _CREATED_PATTERN.search(_normalize_whitespace(text))
    if not match:
        return DEFAULT_MODEL

    # "Created with Pro" and the creation date live in two adjacent spans; when
    # they are flattened together the label can swallow the next "Published ..."
    # sentence, so cut it off explicitly.
    model = re.split(r"\s+\bPublished\b", match.group("model"))[0].strip()
    return model or DEFAULT_MODEL


def parse_created_at(text: str) -> datetime | None:
    """Extract the creation timestamp from a ``Created with ...`` string."""
    match = _CREATED_PATTERN.search(_normalize_whitespace(text))
    return parse_gemini_datetime(match.group("date")) if match else None


def parse_published_at(text: str) -> datetime | None:
    """Extract the publishing timestamp from a ``Published ...`` string."""
    match = _PUBLISHED_PATTERN.search(_normalize_whitespace(text))
    return parse_gemini_datetime(match.group("date")) if match else None


def parse_header_metadata(text: str) -> tuple[str, datetime | None, datetime | None]:
    """Split a share header into ``(model, created_at, published_at)``."""
    return parse_model_name(text), parse_created_at(text), parse_published_at(text)


def dedupe_query_text(text: str) -> str:
    """Undo the duplicated prompt the share DOM exposes to screen readers.

    ``user-query`` contains a visually hidden ``<h5>You said ...</h5>`` before
    the real prompt, so ``innerText`` yields the prompt twice.  The scraper now
    reads the visible lines directly; this stays as a safety net for fallbacks.
    """
    text = re.sub(r"^\s*You said\s+", "", (text or "").strip(), flags=re.IGNORECASE).strip()
    if not text:
        return ""

    for separator, joiner in (("\n\n", "\n\n"), ("\n", "\n")):
        parts = [part.strip() for part in text.split(separator)]
        half = len(parts) // 2
        if len(parts) >= 2 and len(parts) % 2 == 0 and parts[:half] == parts[half:]:
            return joiner.join(parts[:half])
    return text


def build_conversation_from_share(data: GeminiShareData) -> Conversation:
    messages: dict[str, DialogNode] = {}
    previous_id: str | None = None
    root_id = "turn-1-user"

    for index, turn in enumerate(data.turns, 1):
        user_id = f"turn-{index}-user"
        assistant_id = f"turn-{index}-assistant"

        messages[user_id] = DialogNode(
            id=user_id,
            role="user",
            content=dedupe_query_text(turn.user),
            parent_id=previous_id,
            children_ids=[assistant_id],
            timestamp=data.created_at,
        )
        messages[assistant_id] = DialogNode(
            id=assistant_id,
            role="assistant",
            content=sanitize_html(turn.assistant_html),
            content_format="html",
            parent_id=user_id,
            children_ids=[],
            timestamp=data.created_at,
            model_name=data.model,
            attachments=list(turn.images),
        )

        if previous_id and previous_id in messages:
            messages[previous_id].children_ids = [user_id]
        previous_id = assistant_id

    if not messages:
        raise ValueError("Gemini share page did not contain any conversation turns")

    return Conversation(
        source_provider="gemini",
        source_chat_id=extract_share_id(data.url),
        title=data.title or "Gemini conversation",
        root_id=root_id,
        created_at=data.created_at,
        updated_at=data.published_at,
        messages=messages,
        tags=["AI对话", "Gemini"],
    )


#: DOM scraping script; kept as a constant so it is easy to review in isolation.
_SHARE_SCRAPE_SCRIPT = r"""
() => {
  const strip = (text) => (text || '')
    .replace(/\u00a0/g, ' ')
    .replace(/\u202f/g, ' ')
    .trim();
  const textOf = (node) => strip(node ? node.innerText : '');

  // Angular chrome that must never end up in the transcript: citation chips
  // ("huangguo.com", "AI成人短剧"), follow-up buttons, icon ligature text.
  const REMOVE_SELECTORS = [
    'source-footnote',
    'sources-carousel-inline',
    'source-inline-chip',
    'follow-up',
    '.follow-up-container',
    '.response-container-header',
    '.message-actions',
    'tts',
    'button',
    'mat-icon',
    'gem-icon',
    'script',
    'style',
  ].join(',');

  const readQuery = (turn) => {
    // Visible prompt lines only; skips the screen-reader "You said" heading.
    const lines = Array.from(turn.querySelectorAll('user-query p.query-text-line'))
      .map((node) => textOf(node))
      .filter(Boolean);
    if (lines.length) return lines.join('\n\n');

    const query = turn.querySelector('user-query .query-text') || turn.querySelector('user-query');
    return textOf(query).replace(/^You said\s*/i, '').trim();
  };

  const readResponseHtml = (turn) => {
    const response = turn.querySelector('response-container');
    if (!response) return '';
    const panel = response.querySelector('message-content .markdown')
      || response.querySelector('message-content')
      || response.querySelector('.markdown');
    if (!panel) return '';
    const clone = panel.cloneNode(true);
    clone.querySelectorAll(REMOVE_SELECTORS).forEach((node) => node.remove());
    return clone.innerHTML;
  };

  const readImages = (turn) => {
    const response = turn.querySelector('response-container');
    if (!response) return [];
    return Array.from(response.querySelectorAll('img')).map((img) => {
      const figure = img.closest('figure');
      const caption = figure && figure.querySelector('figcaption');
      return {
        url: img.currentSrc || img.src || '',
        alt: strip(img.alt || ''),
        caption: strip(textOf(caption) || img.alt || ''),
        width: img.naturalWidth || img.width || 0,
        height: img.naturalHeight || img.height || 0,
      };
    }).filter((image) => image.url && image.width >= 80 && image.height >= 80);
  };

  const header = document.querySelector('section[class*="share-viewer_header"]');
  const createdWith = header && header.querySelector('.publish-time-mode');
  const createdWithFallback = header && header.querySelector('[data-test-id="created-with-bard-mode-from-config"]');
  const turns = Array.from(document.querySelectorAll('share-turn-viewer')).map((turn) => ({
    user: readQuery(turn),
    assistantHtml: readResponseHtml(turn),
    images: readImages(turn),
  })).filter((turn) => turn.user || turn.assistantHtml);

  return {
    title: textOf(document.querySelector('h1')) || 'Gemini conversation',
    // ".publish-time-mode" wraps both the model label and the creation date.
    createdWith: textOf(createdWith) || textOf(createdWithFallback),
    published: textOf(header && header.querySelector('.publish-time-text')),
    header: textOf(header),
    turns,
  };
}
"""


def fetch_gemini_share(url: str, timeout_ms: int = 60_000) -> GeminiShareData:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency packaging guard
        raise RuntimeError("Gemini import requires Playwright. Run `uv sync` first.") from exc

    canonical_url = canonicalize_gemini_share_url(url)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 1600})
                page.goto(canonical_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_selector("share-turn-viewer", timeout=timeout_ms)
                # Answers stream in after the shell renders; wait for the first
                # one but keep going when a share has no rendered answer.
                try:
                    page.wait_for_function(
                        "() => !!document.querySelector('share-turn-viewer message-content')",
                        timeout=min(timeout_ms, 20_000),
                    )
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(1000)
                payload = page.evaluate(_SHARE_SCRAPE_SCRIPT)
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(f"Timed out loading Gemini share page: {canonical_url}") from exc
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            raise RuntimeError(
                "Playwright browser is not installed. Run `uv run playwright install chromium`."
            ) from exc
        raise

    created_with = str(payload.get("createdWith") or "")
    published_text = str(payload.get("published") or "")
    header_text = str(payload.get("header") or "")

    # Each header field is parsed on its own: flattening them together lets the
    # model label absorb the "Published ..." sentence.
    model = parse_model_name(created_with) if created_with else DEFAULT_MODEL
    created_at = parse_created_at(created_with)
    published_at = parse_published_at(published_text)
    if created_at is None or published_at is None or model == DEFAULT_MODEL:
        fallback_model, fallback_created, fallback_published = parse_header_metadata(header_text)
        model = model if model != DEFAULT_MODEL else fallback_model
        created_at = created_at or fallback_created
        published_at = published_at or fallback_published

    turns = [
        GeminiTurn(
            user=str(turn.get("user") or ""),
            assistant_html=str(turn.get("assistantHtml") or ""),
            images=[
                ImageAttachment(
                    url=str(image.get("url") or ""),
                    alt=str(image.get("alt") or ""),
                    caption=str(image.get("caption") or image.get("alt") or ""),
                    source_url=str(image.get("url") or ""),
                )
                for image in turn.get("images", [])
                if image.get("url")
            ],
        )
        for turn in payload.get("turns", [])
    ]
    if not turns:
        raise ValueError(f"Gemini share page {canonical_url} exposed no conversation turns")

    return GeminiShareData(
        url=canonical_url,
        title=str(payload.get("title") or "Gemini conversation"),
        model=model,
        created_at=created_at,
        published_at=published_at,
        turns=turns,
    )


def fetch_gemini_share_conversation(url: str, timeout_ms: int = 60_000) -> Conversation:
    return build_conversation_from_share(fetch_gemini_share(url, timeout_ms=timeout_ms))
