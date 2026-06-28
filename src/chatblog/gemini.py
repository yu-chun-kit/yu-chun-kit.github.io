from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx

from .models import Conversation, DialogNode, ImageAttachment


@dataclass(frozen=True)
class GeminiTurn:
    user: str
    assistant: str
    images: list[ImageAttachment] | None = None


@dataclass(frozen=True)
class GeminiShareData:
    url: str
    title: str
    model: str
    created_at: datetime | None
    published_at: datetime | None
    turns: list[GeminiTurn]


def canonicalize_gemini_share_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc == "share.gemini.google":
        try:
            response = httpx.get(url, follow_redirects=True, timeout=30)
            response.raise_for_status()
        except httpx.HTTPError:
            return url

        canonical_match = re.search(r'<link\s+rel="canonical"\s+href="([^"]+)"', response.text)
        if canonical_match:
            return canonical_match.group(1)

        og_match = re.search(r'<meta\s+property="og:url"\s+content="([^"]+)"', response.text)
        if og_match:
            return og_match.group(1)

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


def parse_gemini_datetime(value: str) -> datetime | None:
    value = value.strip()
    for fmt in ("%B %d, %Y at %I:%M %p", "%b %d, %Y at %I:%M %p"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def parse_header_metadata(text: str) -> tuple[str, datetime | None, datetime | None]:
    model = "Gemini"
    created_at = None
    published_at = None

    created_match = re.search(r"Created with\s+(.+?)\s+([A-Z][a-z]+ \d{1,2}, \d{4} at \d{1,2}:\d{2} [AP]M)", text)
    if created_match:
        model = created_match.group(1).strip()
        created_at = parse_gemini_datetime(created_match.group(2))

    published_match = re.search(r"Published\s+([A-Z][a-z]+ \d{1,2}, \d{4} at \d{1,2}:\d{2} [AP]M)", text)
    if published_match:
        published_at = parse_gemini_datetime(published_match.group(1))

    return model, created_at, published_at


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
            content=turn.user,
            parent_id=previous_id,
            children_ids=[assistant_id],
            timestamp=data.created_at,
        )
        messages[assistant_id] = DialogNode(
            id=assistant_id,
            role="assistant",
            content=turn.assistant,
            parent_id=user_id,
            children_ids=[],
            timestamp=data.created_at,
            model_name=data.model,
            attachments=list(turn.images or []),
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
            page = browser.new_page(viewport={"width": 1280, "height": 1600})
            page.goto(canonical_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_selector("share-turn-viewer", timeout=timeout_ms)
            page.wait_for_timeout(1500)
            payload = page.evaluate(
                """
                () => {
                  const clean = (text) => (text || '').replace(/\\u00a0/g, ' ').trim();
                  const contentText = (element) => {
                    if (!element) return '';
                    let text = clean(element.innerText);
                    element.querySelectorAll('follow-up, .follow-up-container, .attachment-container').forEach((node) => {
                      const unwanted = clean(node.innerText);
                      if (unwanted) text = clean(text.replace(unwanted, ''));
                    });
                    return text;
                  };
                  const title = clean(document.querySelector('h1')?.innerText) || 'Gemini conversation';
                  const header = clean(document.querySelector('section[class*="share-viewer_header"]')?.innerText);
                  const turns = Array.from(document.querySelectorAll('share-turn-viewer')).map((turn) => {
                    const user = clean(turn.querySelector('user-query .query-text')?.innerText || turn.querySelector('user-query')?.innerText);
                    const response = turn.querySelector('response-container');
                    const assistant = contentText(
                      response?.querySelector('message-content .markdown') ||
                      response?.querySelector('message-content') ||
                      response
                    );
                    const images = Array.from(response?.querySelectorAll('img') || [])
                      .map((img) => ({
                        url: img.currentSrc || img.src || '',
                        alt: clean(img.alt || ''),
                        caption: clean(img.closest('a, span, div')?.innerText || img.alt || ''),
                        width: img.naturalWidth || img.width || 0,
                        height: img.naturalHeight || img.height || 0,
                      }))
                      .filter((image) => image.url && image.width >= 80 && image.height >= 80);
                    return { user: user.replace(/^You said\\s*/i, '').trim(), assistant, images };
                  }).filter((turn) => turn.user || turn.assistant);
                  return { title, header, turns };
                }
                """
            )
            browser.close()
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(f"Timed out loading Gemini share page: {canonical_url}") from exc
    except Exception as exc:
        if "Executable doesn't exist" in str(exc):
            raise RuntimeError(
                "Playwright browser is not installed. Run `uv run playwright install chromium`."
            ) from exc
        raise

    model, created_at, published_at = parse_header_metadata(str(payload.get("header") or ""))
    turns = [
        GeminiTurn(
            user=str(turn.get("user") or ""),
            assistant=str(turn.get("assistant") or ""),
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
