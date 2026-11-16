"""The unified conversation catalogue shown in the studio GUI.

One :class:`ChatEntry` per conversation, regardless of whether it came from
OpenWebUI's SQLite database or from the Gemini web app.  The GUI only ever sees
this shape, so adding another provider later means adding one adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from .ledger import conversation_key
from .normalize import parse_timestamp
from .taxonomy import Tag

GEMINI_BASE = "https://gemini.google.com/app"


def openwebui_url(base: str, chat_id: str) -> str:
    base = (base or "").rstrip("/")
    if not base:
        base = "http://192.168.128.111:3000"
    return f"{base}/c/{chat_id}"


def gemini_url(chat_id: str) -> str:
    return f"{GEMINI_BASE}/{chat_id}"


def _iso(moment: datetime | None) -> str:
    return moment.isoformat(timespec="seconds") if moment else ""


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    return parse_timestamp(value)


@dataclass
class ChatEntry:
    key: str
    provider: str
    chat_id: str
    title: str = "未命名對話"
    url: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    approximate_date: bool = False
    message_count: int = 0
    models: list[str] = field(default_factory=list)
    tags: list[dict[str, Any]] = field(default_factory=list)
    group: str = ""
    snippet: str = ""
    classification: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, **extra: Any) -> dict[str, Any]:
        payload = {
            "key": self.key,
            "provider": self.provider,
            "chat_id": self.chat_id,
            "title": self.title,
            "url": self.url,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "approximate_date": self.approximate_date,
            "message_count": self.message_count,
            "models": list(self.models),
            "tags": list(self.tags),
            "group": self.group,
            "snippet": self.snippet,
            "classification": dict(self.classification),
            "needs_classification": self.needs_classification,
        }
        payload.update(extra)
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ChatEntry":
        return cls(
            key=str(raw.get("key") or ""),
            provider=str(raw.get("provider") or ""),
            chat_id=str(raw.get("chat_id") or ""),
            title=str(raw.get("title") or "未命名對話"),
            url=str(raw.get("url") or ""),
            created_at=_parse(raw.get("created_at")),
            updated_at=_parse(raw.get("updated_at")),
            approximate_date=bool(raw.get("approximate_date")),
            message_count=int(raw.get("message_count") or 0),
            models=[str(item) for item in raw.get("models") or []],
            tags=[
                {
                    "name": str(tag.get("name") or ""),
                    "dim": str(tag.get("dim") or ""),
                    "confidence": float(tag.get("confidence") or 0.0),
                }
                for tag in raw.get("tags") or []
                if isinstance(tag, dict) and tag.get("name")
            ],
            group=str(raw.get("group") or ""),
            snippet=str(raw.get("snippet") or ""),
            classification=dict(raw.get("classification") or {}),
        )

    @property
    def needs_classification(self) -> bool:
        info = self.classification
        return (
            not self.tags
            or info.get("provider") not in ("openjev", "gemini")
            or bool(info.get("error"))
            or info.get("complete") is False
        )

    def set_tags(
        self,
        tags: Iterable[Tag | dict[str, Any]],
        provider: str = "",
        model: str = "",
        error: str = "",
        *,
        complete: bool | None = None,
        input_tokens: int = 0,
    ) -> None:
        collected: list[dict[str, Any]] = []
        for tag in tags:
            if isinstance(tag, Tag):
                collected.append(tag.to_dict())
            elif isinstance(tag, dict) and tag.get("name"):
                collected.append(
                    {
                        "name": str(tag.get("name")),
                        "dim": str(tag.get("dim") or ""),
                        "confidence": float(tag.get("confidence") or 0.0),
                    }
                )
        self.tags = collected
        self.classification = {
            "provider": provider,
            "model": model,
            "error": error,
            "at": datetime.now().isoformat(timespec="seconds"),
            "complete": (
                bool(collected) and provider in ("openjev", "gemini") and not error
                if complete is None else complete
            ),
            "input_tokens": input_tokens,
        }

    @property
    def sort_moment(self) -> datetime:
        return self.updated_at or self.created_at or datetime.min


def entries_from_openwebui(rows: Iterable[dict[str, Any]], base_url: str) -> list[ChatEntry]:
    entries: list[ChatEntry] = []
    for row in rows:
        chat_id = str(row.get("id") or "")
        if not chat_id:
            continue
        entries.append(
            ChatEntry(
                key=conversation_key("openwebui", chat_id),
                provider="openwebui",
                chat_id=chat_id,
                title=str(row.get("title") or "未命名對話").strip() or "未命名對話",
                url=openwebui_url(base_url, chat_id),
                created_at=_parse(row.get("created_at")),
                updated_at=_parse(row.get("updated_at")),
                approximate_date=False,
            )
        )
    return entries


def entries_from_gemini(items: Iterable[Any]) -> list[ChatEntry]:
    entries: list[ChatEntry] = []
    for item in items:
        chat_id = str(getattr(item, "chat_id", "") or "")
        if not chat_id:
            continue
        approx = getattr(item, "approx_date", None)
        # The app's own RPC reports a real last-modified time; only the DOM
        # fallback has to guess from a "Today / Yesterday" heading.
        real = getattr(item, "updated_at", None)
        entries.append(
            ChatEntry(
                key=conversation_key("gemini", chat_id),
                provider="gemini",
                chat_id=chat_id,
                title=str(getattr(item, "title", "") or "未命名對話"),
                url=gemini_url(chat_id),
                updated_at=real or approx,
                created_at=getattr(item, "created_at", None),
                approximate_date=real is None and approx is not None,
                group=str(getattr(item, "group", "") or ""),
            )
        )
    return entries
