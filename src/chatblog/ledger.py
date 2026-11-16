"""Local index of conversations that were already turned into blog posts.

The ledger answers one question for the GUI: *have I uploaded this chat
already, and has it changed since?*  It lives outside the git tree
(``.chatblog/index.json``) because conversation titles can be private.

Posts written before the ledger existed still carry ``source_provider`` and
``source_chat_id`` in their front matter, so :meth:`Ledger.seed_from_posts`
imports them on first use and the GUI shows them as published right away.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

LEDGER_VERSION = 1

_FRONT_MATTER = re.compile(r"\A---\s*\r?\n(?P<body>.*?)\r?\n---\s*(?:\r?\n|\Z)", re.DOTALL)
_FIELD_LINE = re.compile(r"^(?P<key>[A-Za-z_][\w-]*):\s*(?P<value>.*)$")

#: Front-matter values are written by :func:`chatblog.render.yaml_scalar`
#: (double quoted) but hand-written posts may leave them bare.
def _unquote(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return value


def conversation_key(provider: str, chat_id: str) -> str:
    return f"{provider}:{chat_id}"


def split_key(key: str) -> tuple[str, str]:
    provider, _, chat_id = (key or "").partition(":")
    return provider, chat_id


def content_hash(*parts: Any) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8", "replace"))
        digest.update(b"\x1f")
    return digest.hexdigest()


def read_front_matter(path: Path) -> dict[str, str]:
    """Read the scalar fields of a Hexo post without a YAML dependency."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(8192)
    except OSError:
        return {}

    match = _FRONT_MATTER.match(head)
    if not match:
        return {}

    fields: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if not line or line[0] in " \t-#":
            continue
        found = _FIELD_LINE.match(line)
        if found:
            fields[found.group("key")] = _unquote(found.group("value"))
    return fields


@dataclass
class PublishedRecord:
    """One conversation that already has a post on disk."""

    key: str
    provider: str
    chat_id: str
    title: str = ""
    post_path: str = ""
    images_dir: str = ""
    published_at: str = ""
    source_updated_at: str = ""
    content_hash: str = ""
    tags: list[str] = field(default_factory=list)
    private: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "provider": self.provider,
            "chat_id": self.chat_id,
            "title": self.title,
            "post_path": self.post_path,
            "images_dir": self.images_dir,
            "published_at": self.published_at,
            "source_updated_at": self.source_updated_at,
            "content_hash": self.content_hash,
            "tags": list(self.tags),
            "private": self.private,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PublishedRecord":
        provider = str(raw.get("provider") or "")
        chat_id = str(raw.get("chat_id") or "")
        key = str(raw.get("key") or conversation_key(provider, chat_id))
        return cls(
            key=key,
            provider=provider,
            chat_id=chat_id,
            title=str(raw.get("title") or ""),
            post_path=str(raw.get("post_path") or ""),
            images_dir=str(raw.get("images_dir") or ""),
            published_at=str(raw.get("published_at") or ""),
            source_updated_at=str(raw.get("source_updated_at") or ""),
            content_hash=str(raw.get("content_hash") or ""),
            tags=[str(tag) for tag in raw.get("tags") or []],
            private=bool(raw.get("private")),
        )

    def stale(self, title: str, source_updated_at: str | None) -> bool:
        """True when the conversation changed after it was published."""
        if self.title and title and self.title != title:
            return True
        if self.source_updated_at and source_updated_at:
            return _normalise_moment(self.source_updated_at) != _normalise_moment(source_updated_at)
        return False


def _normalise_moment(value: str | None) -> str:
    """Compare datetimes loosely: the sources disagree on seconds and zones."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return text[:16]


class Ledger:
    """Read/write ``.chatblog/index.json`` and seed it from existing posts."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.records: dict[str, PublishedRecord] = {}
        self._loaded = False

    # -- persistence -----------------------------------------------------
    def load(self, posts_dir: Path | None = None, repo_root: Path | None = None) -> "Ledger":
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = {}
            for item in (raw.get("items") or {}).values() if isinstance(raw, dict) else []:
                if isinstance(item, dict):
                    record = PublishedRecord.from_dict(item)
                    if record.key:
                        self.records[record.key] = record
        if posts_dir is not None and posts_dir.is_dir():
            self.seed_from_posts(posts_dir, repo_root=repo_root)
        self._loaded = True
        return self

    def save(self) -> None:
        payload = {
            "version": LEDGER_VERSION,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "items": {key: record.to_dict() for key, record in sorted(self.records.items())},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", delete=False, dir=str(self.path.parent), suffix=".tmp"
        )
        try:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.close()
            os.replace(handle.name, self.path)
        finally:
            if os.path.exists(handle.name):
                os.unlink(handle.name)

    # -- queries ---------------------------------------------------------
    def get(self, key: str) -> PublishedRecord | None:
        return self.records.get(key)

    def upsert(self, record: PublishedRecord) -> None:
        self.records[record.key] = record

    def remove(self, key: str) -> None:
        self.records.pop(key, None)

    def stale_keys(self) -> set[str]:
        return set(self.records)

    # -- seeding ---------------------------------------------------------
    def seed_from_posts(self, posts_dir: Path, repo_root: Path | None = None) -> int:
        """Import ``source_provider``/``source_chat_id`` front matter from posts."""
        repo_root = Path(repo_root) if repo_root else posts_dir.parent.parent
        added = 0
        for path in sorted(Path(posts_dir).glob("*.md")):
            fields = read_front_matter(path)
            provider = (fields.get("source_provider") or "").strip().lower()
            chat_id = (fields.get("source_chat_id") or "").strip()
            if not provider or not chat_id:
                continue
            if provider not in ("openwebui", "gemini"):
                continue
            key = conversation_key(provider, chat_id)
            if key in self.records:
                continue
            try:
                relative = str(path.resolve().relative_to(repo_root.resolve()))
            except ValueError:
                relative = str(path)
            self.records[key] = PublishedRecord(
                key=key,
                provider=provider,
                chat_id=chat_id,
                title=fields.get("title") or "",
                post_path=relative.replace("\\", "/"),
                published_at=fields.get("date") or "",
                source_updated_at=fields.get("conversation_updated_at") or "",
            )
            added += 1
        return added
