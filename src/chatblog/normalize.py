from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import ChatSummary, Conversation, DialogNode, Role


def parse_timestamp(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp)

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return parse_timestamp(int(text))
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    return None


def normalize_chat_summary(raw: dict[str, Any]) -> ChatSummary:
    chat_id = str(raw.get("id") or raw.get("chat_id") or raw.get("uuid") or "")
    return ChatSummary(
        id=chat_id,
        title=str(raw.get("title") or "Untitled"),
        created_at=parse_timestamp(raw.get("created_at")),
        updated_at=parse_timestamp(raw.get("updated_at")),
    )


def normalize_chat_list(raw: Any) -> list[ChatSummary]:
    if isinstance(raw, dict):
        for key in ("chats", "data", "items"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break

    if not isinstance(raw, list):
        return []

    return [summary for item in raw if isinstance(item, dict) if (summary := normalize_chat_summary(item)).id]


def _normalize_role(value: Any) -> Role:
    role = str(value or "unknown").lower()
    if role == "assistant":
        return "assistant"
    if role == "user":
        return "user"
    if role == "system":
        return "system"
    return "unknown"


def normalize_openwebui_chat(raw: dict[str, Any]) -> Conversation:
    chat = raw.get("chat") or {}
    history = chat.get("history") or {}
    raw_messages = history.get("messages") or {}

    if not isinstance(raw_messages, dict) or not raw_messages:
        raise ValueError("OpenWebUI chat has no messages")

    messages: dict[str, DialogNode] = {}
    root_id: str | None = None

    for fallback_id, item in raw_messages.items():
        if not isinstance(item, dict):
            continue

        message_id = str(item.get("id") or fallback_id)
        parent_id = item.get("parentId")
        if parent_id is not None:
            parent_id = str(parent_id)

        children = item.get("childrenIds") or []
        if not isinstance(children, list):
            children = []

        node = DialogNode(
            id=message_id,
            role=_normalize_role(item.get("role")),
            content=str(item.get("content") or ""),
            parent_id=parent_id,
            children_ids=[str(child) for child in children],
            timestamp=parse_timestamp(item.get("timestamp")),
            model_name=str(item.get("modelName") or item.get("model") or ""),
        )
        messages[message_id] = node

        if parent_id is None and root_id is None:
            root_id = message_id

    if not messages:
        raise ValueError("OpenWebUI chat has no valid messages")

    if root_id is None:
        root_id = next(iter(messages))

    meta = raw.get("meta") or {}
    tags = meta.get("tags") if isinstance(meta, dict) else []
    if not isinstance(tags, list):
        tags = []

    created_at = parse_timestamp(raw.get("created_at"))
    updated_at = parse_timestamp(raw.get("updated_at"))
    if created_at is None:
        created_at = messages[root_id].timestamp

    return Conversation(
        source_chat_id=str(raw.get("id") or raw.get("chat_id") or ""),
        title=str(raw.get("title") or "AI conversation"),
        root_id=root_id,
        created_at=created_at,
        updated_at=updated_at,
        messages=messages,
        tags=[str(tag) for tag in tags if str(tag).strip()],
    )
