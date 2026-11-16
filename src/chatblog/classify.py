"""Turn a conversation into fine-grained tags with a System One model.

The pipeline is deliberately small:

1. flatten the conversation into plain text (HTML stripped, branches included),
2. build a *state* string: title + metadata + an excerpt that fits the model,
3. ask the taxonomy's typed questions in two narrow batches (domain first, then
   subdomain / concept / flags restricted to that domain),
4. compose display tags from the probability answers.

When no API key is configured (or the request fails) the rule-based classifier
in :meth:`chatblog.taxonomy.Taxonomy.rules` produces a smaller tag set instead,
so the GUI always has something to show.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from .models import Conversation, DialogNode
from .taxonomy import Tag, Taxonomy
from .systemone import SystemOneClient, SystemOneError

MAX_STATE_CHARS = 9000

#: Asked together in the first request: they describe the shape of the chat and
#: only have a handful of options each.
STRUCTURAL_DIMENSIONS = ("domain", "genre", "depth", "language", "sensitivity")
#: Cheap yes/no questions that ride along with the narrowed follow-up.
FLAG_DIMENSIONS = ("has_code", "is_series", "publishable", "has_private_info")

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t\u00a0\u202f]+")


@dataclass
class Classification:
    tags: list[Tag] = field(default_factory=list)
    provider: str = "rules"  # "openjev" | "rules"
    model: str = ""
    error: str = ""
    input_tokens: int = 0

    @property
    def complete(self) -> bool:
        return bool(self.tags) and self.provider != "rules" and not self.error

    @property
    def ok(self) -> bool:
        return self.complete

    def to_dict(self) -> dict:
        return {
            "tags": [tag.to_dict() for tag in self.tags],
            "provider": self.provider,
            "model": self.model,
            "error": self.error,
            "input_tokens": self.input_tokens,
            "complete": self.complete,
        }


def node_text(node: DialogNode) -> str:
    text = _TAG_RE.sub(" ", node.content or "")
    text = _SPACE_RE.sub(" ", text)
    return " ".join(text.split())


def _ordered_ids(conversation: Conversation) -> list[str]:
    """Walk the main line first, then any extra roots (edited prompts)."""
    ordered: list[str] = []
    seen: set[str] = set()

    def walk(start: str) -> None:
        current = start
        while current and current not in seen and current in conversation.messages:
            seen.add(current)
            ordered.append(current)
            children = conversation.messages[current].children_ids
            current = children[0] if children else ""

    walk(conversation.root_id)
    for message_id, node in conversation.messages.items():
        if message_id in seen:
            continue
        if node.parent_id is None or node.parent_id not in conversation.messages:
            walk(message_id)
    for message_id in conversation.messages:
        if message_id not in seen:
            ordered.append(message_id)
    return ordered


def conversation_transcript(conversation: Conversation, max_chars: int | None = None) -> str:
    lines: list[str] = []
    for message_id in _ordered_ids(conversation):
        node = conversation.messages.get(message_id)
        if node is None:
            continue
        text = node_text(node)
        if not text:
            continue
        role = "我" if node.role == "user" else "AI"
        lines.append(f"{role}：{text}")
    transcript = "\n\n".join(lines)
    if max_chars and len(transcript) > max_chars:
        transcript = transcript[:max_chars]
    return transcript


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    head = int(limit * 0.62)
    tail = limit - head
    return f"{text[:head].rstrip()}\n…（中略）…\n{text[-tail:].lstrip()}"


def build_state(
    title: str,
    provider: str,
    transcript: str,
    *,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    models: Iterable[str] = (),
    message_count: int = 0,
    limit: int = MAX_STATE_CHARS,
) -> str:
    """Title + metadata + a two-ended excerpt, so long chats still fit."""
    meta = [f"標題：{title or '（無標題）'}", f"來源：{provider}"]
    if created_at:
        meta.append(f"建立：{created_at:%Y-%m-%d}")
    if updated_at:
        meta.append(f"更新：{updated_at:%Y-%m-%d}")
    model_names = [name for name in models if name]
    if model_names:
        meta.append("模型：" + "、".join(model_names))
    if message_count:
        meta.append(f"訊息數：{message_count}")
    header = "\n".join(meta)
    room = max(500, limit - len(header) - 80)
    return f"{header}\n\n--- 對話節錄 ---\n{_clip(transcript, room)}\n--- 節錄完 ---"


def _fallback(title: str, transcript: str, taxonomy: Taxonomy, error: str = "") -> Classification:
    return Classification(tags=taxonomy.rules(transcript, title), provider="rules", error=error)


def classify_text(
    title: str,
    transcript: str,
    taxonomy: Taxonomy,
    client: SystemOneClient | None = None,
    *,
    provider: str = "openwebui",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    models: Iterable[str] = (),
    message_count: int = 0,
) -> Classification:
    """Classify one conversation, falling back to rules on any model error.

    The questions are asked in two small batches rather than one big one.
    Measured on a real chat: all eleven questions at once, with 80 subdomains
    and 47 concepts in the same payload, answered "nietzsche / anxiety" for a
    programming conversation; the domain alone answered ``technology`` with
    0.999 confidence. Narrowing the option lists after the domain is chosen
    fixes that, at the cost of repeating the state (≈7k tokens per call).
    """
    if client is None or not client.configured:
        return _fallback(title, transcript, taxonomy, error="未設定分類模型 API key，已用關鍵詞規則分類")

    state = build_state(
        title,
        provider,
        transcript,
        created_at=created_at,
        updated_at=updated_at,
        models=models,
        message_count=message_count,
    )

    questions = taxonomy.questions()
    answers: dict[str, Any] = {}
    tokens = 0
    error = ""
    model = getattr(client, "model", "")

    try:
        first = client.ask(
            state, {key: questions[key] for key in STRUCTURAL_DIMENSIONS if key in questions}
        )
        answers.update(first["answers"])
        tokens += first["usage"].input_tokens
        model = first["model"] or model
    except SystemOneError as exc:
        return _fallback(title, transcript, taxonomy, error=str(exc))

    domain_id = str((answers.get("domain") or {}).get("choice") or "")

    # Subdomain / concept are narrow follow-ups: only the options that belong
    # to the domain that just won. A failure here just means a coarser tag set.
    second: dict[str, dict[str, Any]] = {}
    subdomain_question = taxonomy.subdomain_question(domain_id)
    if subdomain_question:
        second["subdomain"] = subdomain_question
    concept_question = taxonomy.concept_question(domain_id)
    if concept_question:
        second["concept"] = concept_question
    second.update({key: questions[key] for key in FLAG_DIMENSIONS if key in questions})

    if second:
        try:
            follow = client.ask(state, second)
            answers.update(follow["answers"])
            tokens += follow["usage"].input_tokens
        except SystemOneError as exc:
            error = str(exc)

    tags = taxonomy.compose(answers)
    if not tags:
        result = _fallback(title, transcript, taxonomy, error=error or "模型沒有回傳可用的標籤")
        result.input_tokens = tokens
        return result
    return Classification(
        tags=tags, provider=getattr(client, "provider", "openjev"),
        model=model, input_tokens=tokens, error=error,
    )


def classify_conversation(
    conversation: Conversation,
    taxonomy: Taxonomy,
    client: SystemOneClient | None = None,
) -> Classification:
    transcript = conversation_transcript(conversation)
    return classify_text(
        conversation.title,
        transcript,
        taxonomy,
        client,
        provider=conversation.source_provider,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        models=conversation.models,
        message_count=conversation.message_count,
    )
