from __future__ import annotations

import base64
import binascii
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote_to_bytes, urljoin, urlparse

import httpx

from .models import Conversation, ImageAttachment
from .render import slugify_title


@dataclass
class AssetDownloadResult:
    """Outcome of :func:`download_conversation_images`."""

    downloaded: list[Path] = field(default_factory=list)
    reused: list[Path] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.downloaded) + len(self.reused)


_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;,]*)(?P<params>;[^,]*)?,(?P<payload>.*)$", re.DOTALL)


def _extension_from_mime(mime: str) -> str | None:
    mime = (mime or "").split(";")[0].strip().lower()
    if not mime:
        return None
    ext = mimetypes.guess_extension(mime)
    if not ext:
        return None
    return ".jpg" if ext == ".jpe" else ext


def _extension_from_response(url: str, content_type: str) -> str:
    ext = _extension_from_mime(content_type)
    if ext:
        return ext

    suffix = Path(urlparse(url).path).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{2,5}", suffix):
        return suffix

    return ".jpg"


def _decode_data_url(url: str) -> tuple[bytes, str]:
    """Return ``(payload, extension)`` for an inline ``data:`` image."""
    match = _DATA_URL_RE.match(url)
    if not match:
        raise ValueError("unsupported data URL")

    params = (match.group("params") or "").lower()
    payload = match.group("payload")
    if "base64" in params:
        data = base64.b64decode(payload, validate=False)
    else:
        data = unquote_to_bytes(payload)
    if not data:
        raise ValueError("empty data URL payload")
    return data, _extension_from_mime(match.group("mime") or "") or ".jpg"


def _localizable_attachments(
    conversation: Conversation,
    base_url: str | None = None,
) -> list[ImageAttachment]:
    """Attachments we can turn into local files (http(s), data:, or relative)."""
    found: list[ImageAttachment] = []
    for node in conversation.messages.values():
        for attachment in node.attachments:
            url = attachment.url or ""
            if url.startswith(("http://", "https://", "data:")):
                found.append(attachment)
            elif url.startswith("/") and base_url:
                found.append(attachment)
    return found


def _resolve_url(url: str, base_url: str | None) -> str:
    """Resolve OpenWebUI-style URLs (``/api/v1/files/<id>/content``) to absolute ones."""
    if url.startswith(("http://", "https://", "data:")) or not base_url:
        return url

    parsed = urlparse(base_url)
    if url.startswith("/") and parsed.scheme and parsed.netloc:
        # root relative: keep the host, drop the API prefix
        return f"{parsed.scheme}://{parsed.netloc}{url}"
    return urljoin(base_url.rstrip("/") + "/", url)


def _existing_asset(asset_dir: Path, image_index: int) -> Path | None:
    matches = sorted(asset_dir.glob(f"image-{image_index:02d}.*"))
    return matches[0] if matches else None


def download_conversation_images(
    conversation: Conversation,
    source_dir: Path,
    public_prefix: str = "/images",
    *,
    force: bool = False,
    client: httpx.Client | None = None,
    base_url: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> AssetDownloadResult:
    """Download conversation images into Hexo's source directory.

    Attachment URLs are rewritten in-place to public site paths.  Re-running an
    import reuses files that are already on disk unless ``force`` is set, and a
    failing image never aborts the whole post: the original URL is kept and the
    error is reported in :attr:`AssetDownloadResult.failed`.

    * ``client`` can be injected (e.g. an ``httpx.MockTransport`` in tests).
    * ``base_url`` resolves relative URLs such as OpenWebUI's
      ``/api/v1/files/<id>/content``.
    * ``headers`` carries the OpenWebUI bearer token for those protected files.
    * ``data:`` URLs (inline base64 images) are decoded straight to disk.
    """
    result = AssetDownloadResult()
    attachments = _localizable_attachments(conversation, base_url)
    if not attachments:
        return result

    provider_slug = slugify_title(conversation.source_provider, fallback="chat")
    share_slug = slugify_title(conversation.source_chat_id, fallback=f"{provider_slug}-share")
    asset_dir = source_dir / "images" / provider_slug / share_slug
    asset_dir.mkdir(parents=True, exist_ok=True)

    owned_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=60)
    try:
        for image_index, attachment in enumerate(attachments, 1):
            existing = None if force else _existing_asset(asset_dir, image_index)
            original_url = attachment.url
            is_data = original_url.startswith("data:")
            if existing is not None:
                # Reuse: never copy an inline payload into source_url, it would
                # be embedded in the post as a multi-hundred-KB href.
                if not attachment.source_url or attachment.source_url.startswith("data:"):
                    attachment.source_url = "" if is_data else original_url
                attachment.url = f"{public_prefix}/{provider_slug}/{share_slug}/{existing.name}"
                result.reused.append(existing)
                continue

            try:
                if is_data:
                    payload, ext = _decode_data_url(original_url)
                else:
                    request_url = _resolve_url(original_url, base_url)
                    response = http.get(request_url, headers=dict(headers or {}))
                    response.raise_for_status()
                    payload = response.content
                    ext = _extension_from_response(
                        str(response.url), response.headers.get("content-type", "")
                    )
                filename = f"image-{image_index:02d}{ext}"
                target = asset_dir / filename
                target.write_bytes(payload)
            except (httpx.HTTPError, OSError, ValueError, binascii.Error) as exc:
                label = "inline data URL" if is_data else original_url
                result.failed.append((label, str(exc)))
                continue

            result.downloaded.append(target)
            if is_data:
                if attachment.source_url.startswith("data:"):
                    attachment.source_url = ""
            else:
                attachment.source_url = attachment.source_url or original_url
            attachment.url = f"{public_prefix}/{provider_slug}/{share_slug}/{filename}"
    finally:
        if owned_client:
            http.close()

    return result
