from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Role = Literal["user", "assistant", "system", "unknown"]


class ChatSummary(BaseModel):
    id: str
    title: str = "Untitled"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ImageAttachment(BaseModel):
    url: str
    alt: str = ""
    caption: str = ""
    source_url: str = ""


class DialogNode(BaseModel):
    id: str
    role: Role = "unknown"
    content: str = ""
    parent_id: str | None = None
    children_ids: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None
    model_name: str = ""
    attachments: list[ImageAttachment] = Field(default_factory=list)


class Conversation(BaseModel):
    source_provider: str = "openwebui"
    source_chat_id: str
    title: str = "AI conversation"
    root_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    messages: dict[str, DialogNode] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def models(self) -> list[str]:
        names = {node.model_name for node in self.messages.values() if node.model_name}
        return sorted(names)

    @property
    def branch_count(self) -> int:
        return sum(max(len(node.children_ids) - 1, 0) for node in self.messages.values())

    @property
    def display_date(self) -> datetime | None:
        root = self.messages.get(self.root_id)
        return root.timestamp if root and root.timestamp else self.created_at or self.updated_at
