from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .models import Conversation
from .render import slugify_title


def _extension_from_response(url: str, content_type: str) -> str:
    content_type = content_type.split(";")[0].strip().lower()
    if content_type:
        ext = mimetypes.guess_extension(content_type)
        if ext:
            return ".jpg" if ext == ".jpe" else ext

    suffix = Path(urlparse(url).path).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{2,5}", suffix):
        return suffix

    return ".jpg"


def download_conversation_images(
    conversation: Conversation,
    source_dir: Path,
    public_prefix: str = "/images/gemini",
) -> list[Path]:
    """Download remote image attachments into Hexo's source directory.

    Attachment URLs are rewritten in-place to public site paths.
    """
    downloaded: list[Path] = []
    share_slug = slugify_title(conversation.source_chat_id, fallback="gemini-share")
    asset_dir = source_dir / "images" / "gemini" / share_slug
    asset_dir.mkdir(parents=True, exist_ok=True)

    image_index = 1
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for node in conversation.messages.values():
            for attachment in node.attachments:
                if not attachment.url.startswith(("http://", "https://")):
                    continue

                response = client.get(attachment.url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                ext = _extension_from_response(str(response.url), content_type)
                filename = f"image-{image_index:02d}{ext}"
                target = asset_dir / filename
                target.write_bytes(response.content)
                downloaded.append(target)

                attachment.source_url = attachment.source_url or attachment.url
                attachment.url = f"{public_prefix}/{share_slug}/{filename}"
                image_index += 1

    return downloaded
