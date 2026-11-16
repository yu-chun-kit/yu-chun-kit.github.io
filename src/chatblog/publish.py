"""Generate Hexo posts from catalogue entries.

Shared by the GUI and the CLI so both paths write identical files: the existing
:mod:`chatblog.cli` helpers fetch OpenWebUI chats, :mod:`chatblog.gemini_web`
fetches Gemini ones, and :func:`chatblog.render.write_hexo_post` renders both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .assets import download_conversation_images
from .catalog import ChatEntry
from .classify import conversation_transcript
from .ledger import PublishedRecord, content_hash, conversation_key
from .models import Conversation
from .render import parse_override_date, slugify_title, write_hexo_post
from .taxonomy import Taxonomy, Tag

PRIVATE_MARKER = "# chatblog private (auto-managed)"


@dataclass
class PublishOptions:
    download_assets: bool = True
    force_assets: bool = False
    private: bool = False
    date: str = ""
    source: str = "auto"


@dataclass
class PublishResult:
    key: str
    ok: bool
    title: str = ""
    post_path: str = ""
    images: int = 0
    message: str = ""
    error: str = ""
    updated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "ok": self.ok,
            "title": self.title,
            "post_path": self.post_path,
            "images": self.images,
            "message": self.message,
            "error": self.error,
            "updated": self.updated,
        }


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _existing_target(post_path: Path, conversation: Conversation, posts_dir: Path, post_date: datetime) -> Path:
    """Keep two chats with the same title and day from overwriting each other."""
    target = post_path
    if not target.exists():
        return target
    from .ledger import read_front_matter

    fields = read_front_matter(target)
    if (fields.get("source_chat_id") or "") == conversation.source_chat_id:
        return target
    suffix = slugify_title(conversation.source_chat_id, fallback="chat")[:8]
    return target.with_name(f"{target.stem}-{suffix}.md")


def coarse_post_tags(entry: ChatEntry, taxonomy: Taxonomy) -> list[str]:
    tags = [Tag(name=str(tag.get("name")), dim=str(tag.get("dim") or "")) for tag in entry.tags]
    return taxonomy.post_tags(tags, entry.provider)


def fetch_openwebui(entry: ChatEntry, options: PublishOptions) -> Conversation:
    from .cli import fetch_conversation
    from .config import load_settings

    settings = load_settings()
    return fetch_conversation(entry.chat_id, source=options.source, settings=settings)


def publish_entry(
    entry: ChatEntry,
    taxonomy: Taxonomy,
    options: PublishOptions | None = None,
    gemini_page: Any = None,
) -> tuple[PublishResult, PublishedRecord | None]:
    """Fetch one conversation and write its post. Returns the ledger record."""
    options = options or PublishOptions()
    from .config import load_settings

    settings = load_settings()
    repo_root = settings.repo_root
    result = PublishResult(key=entry.key, ok=False, title=entry.title)

    try:
        if entry.provider == "openwebui":
            conversation = fetch_openwebui(entry, options)
            if options.download_assets:
                from .cli import download_openwebui_assets

                download_openwebui_assets(conversation, settings, force=options.force_assets)
        elif entry.provider == "gemini":
            from . import gemini_web

            def _scrape(page):
                return gemini_web.fetch_conversation(
                    page,
                    entry.chat_id,
                    approx_date=entry.updated_at,
                    debug_dir=settings.data_dir / "debug",
                )

            if gemini_page is not None:
                conversation = _scrape(gemini_page)
                if options.download_assets:
                    gemini_web.download_images(gemini_page, conversation)
            else:
                profile = (
                    Path(settings.gemini_profile)
                    if settings.gemini_profile
                    else gemini_web.default_profile_dir()
                )
                with gemini_web.browser_page(
                    profile,
                    settings.gemini_port,
                    headless=settings.gemini_headless,
                    url=gemini_web.GEMINI_APP,
                ) as page:
                    conversation = _scrape(page)
                    if options.download_assets:
                        gemini_web.download_images(page, conversation)
            if options.download_assets:
                assets = download_conversation_images(conversation, repo_root / "source")
                for failed_url, message in assets.failed:
                    result.message += f"圖片略過：{message}；"
        else:
            raise ValueError(f"unknown provider: {entry.provider}")
    except Exception as exc:  # noqa: BLE001 - one failing chat must not stop a batch
        result.error = str(exc)
        return result, None

    conversation.tags = coarse_post_tags(entry, taxonomy) or conversation.tags
    post_date: datetime = (
        parse_override_date(options.date)
        or conversation.display_date
        or entry.updated_at
        or datetime.now()
    )
    from .render import default_output_path

    target = default_output_path(conversation, settings.posts_dir, post_date)
    target = _existing_target(target, conversation, settings.posts_dir, post_date)
    target = write_hexo_post(
        conversation,
        posts_dir=settings.posts_dir,
        override_date=options.date or None,
        output=target,
    )

    images_dir = repo_root / "source" / "images" / conversation.source_provider / conversation.source_chat_id
    record = PublishedRecord(
        key=conversation_key(conversation.source_provider, conversation.source_chat_id),
        provider=conversation.source_provider,
        chat_id=conversation.source_chat_id,
        title=conversation.title,
        post_path=_repo_relative(target, repo_root),
        images_dir=_repo_relative(images_dir, repo_root) if images_dir.is_dir() else "",
        published_at=datetime.now().isoformat(timespec="seconds"),
        source_updated_at=entry.updated_at.isoformat(timespec="seconds") if entry.updated_at else "",
        content_hash=content_hash(conversation.title, conversation_transcript(conversation)),
        tags=list(conversation.tags),
        private=bool(options.private),
    )

    if options.private:
        ensure_gitignored(repo_root, [record.post_path, record.images_dir])

    result.ok = True
    result.post_path = record.post_path
    result.message = (result.message + "已生成").strip("；")
    return result, record


def ensure_gitignored(repo_root: Path, paths: list[str]) -> None:
    """Append private post paths to .gitignore without disturbing line endings."""
    gitignore = repo_root / ".gitignore"
    # Read bytes: text-mode reads normalise CRLF and would rewrite the whole
    # file with LF (the repo keeps a CRLF working tree on purpose).
    raw = gitignore.read_bytes() if gitignore.is_file() else b""
    text = raw.decode("utf-8", errors="replace")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    existing = {line.strip() for line in text.splitlines()}
    missing = [item for item in paths if item and item not in existing]
    if not missing:
        return

    if PRIVATE_MARKER not in text:
        if text and not text.endswith(("\n", "\r\n")):
            text += newline
        text += newline + PRIVATE_MARKER + newline
    elif text and not text.endswith(("\n", "\r\n")):
        text += newline
    text += newline.join(missing) + newline
    gitignore.write_bytes(text.encode("utf-8"))
