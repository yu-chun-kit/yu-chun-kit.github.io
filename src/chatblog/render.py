from __future__ import annotations

import html
import re
from datetime import datetime, time
from pathlib import Path

from markdown_it import MarkdownIt

from .models import Conversation, DialogNode
from .normalize import parse_timestamp
from .sanitize import sanitize_html


def yaml_scalar(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def format_dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def slugify_title(title: str, fallback: str = "ai-dialog") -> str:
    safe = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE)
    safe = re.sub(r"\s+", "-", safe.strip())
    safe = safe[:60].strip("-")
    return safe or fallback


def clean_content(content: str) -> str:
    content = re.sub(
        r'<details\s+type="reasoning"[^>]*>.*?</details>',
        "",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return content.strip()


_MARKDOWN_RENDERER = MarkdownIt(
    "commonmark",
    {"breaks": True, "html": False, "linkify": False, "typographer": False},
).enable("table")


def process_markdown_content(content: str) -> str:
    """Render conversation markdown into the HTML embedded in the post.

    ``html=False`` keeps raw markup coming from the source conversation inert,
    so a chat export can never smuggle a ``<script>`` into the blog.  ``breaks``
    mirrors the previous behaviour where a single newline was a line break.
    """
    return _MARKDOWN_RENDERER.render(content).strip()


def render_node_content(node: DialogNode) -> str:
    """Turn one stored message into embeddable HTML for the dialog layout."""
    content = clean_content(node.content)
    if node.content_format == "html":
        return sanitize_html(content)
    return process_markdown_content(content)


def _format_message(node: DialogNode) -> list[str]:
    role_class = "user" if node.role == "user" else "ai"
    avatar = "我" if node.role == "user" else "AI"
    content = render_node_content(node)

    attachments = "".join(_format_attachment(attachment) for attachment in node.attachments)

    if role_class == "user":
        bubble = f'<div class="dialog-bubble">{content}{attachments}</div>'
    else:
        model_html = f'<div class="dialog-model">{html.escape(node.model_name)}</div>' if node.model_name else ""
        bubble = f'<div class="dialog-bubble">{model_html}<div class="dialog-content">{content}{attachments}</div></div>'

    return [
        f'<div class="dialog-message {role_class}">',
        f'  <div class="dialog-avatar">{avatar}</div>',
        f"  {bubble}",
        "</div>",
        "",
    ]


def _format_attachment(attachment) -> str:
    alt = html.escape(attachment.alt or attachment.caption or "Conversation image")
    caption = html.escape(attachment.caption or attachment.alt or "")
    source = html.escape(attachment.source_url or "")
    source_link = f' <a href="{source}" target="_blank" rel="noopener">source</a>' if source else ""
    caption_html = f"<figcaption>{caption}{source_link}</figcaption>" if caption or source_link else ""
    return (
        '<figure class="dialog-attachment">'
        f'<img src="{html.escape(attachment.url)}" alt="{alt}" loading="lazy">'
        f"{caption_html}</figure>"
    )


BRANCH_PREVIEW_LIMIT = 60
_TAG_RE = re.compile(r"<[^>]+>")
_MARKDOWN_MARK_RE = re.compile(r"[*_`~>#]+")


def preview_text(node: DialogNode | None, limit: int = BRANCH_PREVIEW_LIMIT) -> str:
    """Short, markup-free summary of a message, used as a branch label."""
    if node is None:
        return "（空訊息）"

    text = _TAG_RE.sub(" ", clean_content(node.content))
    text = _MARKDOWN_MARK_RE.sub("", text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit].rstrip() + "..."
    return text or "（空訊息）"


def render_branch_group(
    conversation: Conversation,
    children: list[str],
    visited: set[str],
    depth: int,
) -> list[str]:
    """Render every alternative continuation of one divergence point.

    The first child stays inline as the main line; the others become collapsed
    blocks.  Numbering is ``分支 N/總數`` so nested divergences cannot produce
    two different blocks that both claim to be "分支 2".
    """
    total = len(children)
    nested_class = " dialog-branch-nested" if depth > 0 else ""
    lines = [
        '<div class="dialog-branch-group">',
        f'<div class="dialog-branch-note">此處有 {total} 個分支：以下接續分支 1/{total}'
        f"（主線），其餘 {total - 1} 個分支已摺疊展開於此。</div>",
    ]

    for index, child_id in enumerate(children[1:], start=2):
        branch_lines = traverse_with_branches(conversation, child_id, set(visited), depth + 1)
        if not any(line.strip() for line in branch_lines):
            continue

        child = conversation.messages.get(child_id)
        label = f"分支 {index}/{total}"
        if depth > 0:
            label += f"（嵌套第 {depth + 1} 層）"

        lines.append(f'<details class="dialog-branch{nested_class}">')
        lines.append(f"<summary>{html.escape(label)}：{html.escape(preview_text(child))}</summary>")
        lines.append('<div class="dialog-branch-content">')
        lines.extend(branch_lines)
        lines.append("</div>")
        lines.append("</details>")
        lines.append("")

    lines.append("</div>")
    return lines


def traverse_with_branches(
    conversation: Conversation,
    message_id: str,
    visited: set[str] | None = None,
    depth: int = 0,
) -> list[str]:
    if visited is None:
        visited = set()

    if message_id in visited or message_id not in conversation.messages:
        return []

    visited.add(message_id)
    node = conversation.messages[message_id]
    lines: list[str] = []

    if clean_content(node.content):
        lines.extend(_format_message(node))

    children = list(node.children_ids)
    if not children:
        return lines

    # Divergence points are rendered where they happen: the collapsed branches
    # sit next to the message that spawned them instead of trailing the whole
    # conversation on the main line.
    if len(children) > 1:
        lines.extend(render_branch_group(conversation, children, visited, depth))

    lines.extend(traverse_with_branches(conversation, children[0], visited, depth))
    return lines


def tree_message_ids(conversation: Conversation, root_id: str) -> set[str]:
    """Every message id reachable from ``root_id`` (branches included)."""
    seen: set[str] = set()
    stack = [root_id]
    while stack:
        message_id = stack.pop()
        if message_id in seen or message_id not in conversation.messages:
            continue
        seen.add(message_id)
        stack.extend(conversation.messages[message_id].children_ids)
    return seen


def root_ids(conversation: Conversation) -> list[str]:
    """Message ids that start a tree (no parent, or a parent that is missing).

    OpenWebUI creates an extra root when a *user* message is edited (or a
    conversation is restarted): the edited prompt becomes a sibling tree of the
    original one.  Rendering only ``conversation.root_id`` used to drop those
    messages entirely.
    """
    return [
        message_id
        for message_id, node in conversation.messages.items()
        if node.parent_id is None or node.parent_id not in conversation.messages
    ]


def render_extra_roots(conversation: Conversation, reachable: set[str]) -> list[str]:
    """Render additional root trees (edited prompts) as collapsed blocks."""
    pending = [mid for mid in root_ids(conversation) if mid not in reachable]
    if not pending:
        return []

    lines = [
        '<div class="dialog-branch-group">',
        f'<div class="dialog-branch-note">此對話另有 {len(pending)} 段從頭開始的分支'
        "（訊息編輯或重新開始），已摺疊如下。</div>",
    ]

    handled = set(reachable)
    total = len(pending)
    for index, root_id in enumerate(pending, start=1):
        if root_id in handled:
            continue
        node = conversation.messages.get(root_id)
        branch_lines = traverse_with_branches(conversation, root_id, set(handled), depth=1)
        handled |= tree_message_ids(conversation, root_id)
        if not any(line.strip() for line in branch_lines):
            continue

        label = f"另一段對話 {index}/{total}"
        lines.append('<details class="dialog-branch dialog-branch-nested">')
        lines.append(f"<summary>{html.escape(label)}：{html.escape(preview_text(node))}</summary>")
        lines.append('<div class="dialog-branch-content">')
        lines.extend(branch_lines)
        lines.append("</div>")
        lines.append("</details>")
        lines.append("")

    lines.append("</div>")
    return lines


def render_conversation_body(conversation: Conversation) -> list[str]:
    """Walk every tree in the chat: the main line, its branches and extra roots."""
    visited: set[str] = set()
    lines = traverse_with_branches(conversation, conversation.root_id, visited)
    reachable = tree_message_ids(conversation, conversation.root_id)
    lines.extend(render_extra_roots(conversation, reachable))
    return lines


def parse_override_date(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = parse_timestamp(value)
    if parsed:
        return parsed
    try:
        return datetime.combine(datetime.strptime(value, "%Y-%m-%d").date(), time())
    except ValueError as exc:
        raise ValueError("Date must be YYYY-MM-DD or ISO datetime") from exc


def default_output_path(conversation: Conversation, posts_dir: Path, date: datetime) -> Path:
    filename = f"{date.strftime('%Y-%m-%d')}-{slugify_title(conversation.title)}.md"
    return posts_dir / filename


def render_front_matter(conversation: Conversation, post_date: datetime) -> list[str]:
    tags = conversation.tags or ["AI对话"]
    models = conversation.models

    lines = [
        "---",
        f"title: {yaml_scalar(conversation.title)}",
        f"date: {format_dt(post_date)}",
        "tags:",
    ]
    lines.extend(f"  - {tag}" for tag in tags)
    lines.extend(
        [
            "categories:",
            "  - AI对话",
            "layout: dialog",
            "css: /css/dialog.css",
            f"source_provider: {yaml_scalar(conversation.source_provider)}",
            f"source_chat_id: {yaml_scalar(conversation.source_chat_id)}",
            f"conversation_created_at: {yaml_scalar(format_dt(conversation.created_at))}",
            f"conversation_updated_at: {yaml_scalar(format_dt(conversation.updated_at))}",
            f"message_count: {conversation.message_count}",
            f"branch_count: {conversation.branch_count}",
            "models:",
        ]
    )
    if models:
        lines.extend(f"  - {yaml_scalar(model)}" for model in models)
    else:
        lines.append("  - unknown")

    lines.append("---")
    return lines


def render_metadata_header(conversation: Conversation) -> list[str]:
    models = ", ".join(conversation.models) if conversation.models else "unknown"
    source_date = conversation.display_date
    return [
        '<section class="dialog-meta">',
        '  <div class="dialog-meta-title">對話備份</div>',
        '  <dl class="dialog-meta-grid">',
        f"    <div><dt>來源</dt><dd>{html.escape(conversation.source_provider)}</dd></div>",
        f"    <div><dt>對話日期</dt><dd>{html.escape(format_dt(source_date))}</dd></div>",
        f"    <div><dt>模型</dt><dd>{html.escape(models)}</dd></div>",
        f"    <div><dt>消息數</dt><dd>{conversation.message_count}</dd></div>",
        f"    <div><dt>分支數</dt><dd>{conversation.branch_count}</dd></div>",
        "  </dl>",
        "</section>",
        "",
    ]


def render_hexo_post(conversation: Conversation, override_date: str | None = None) -> str:
    post_date = parse_override_date(override_date) or conversation.display_date or datetime.now()
    lines = render_front_matter(conversation, post_date)
    lines.extend(
        [
            "",
            '<link rel="stylesheet" href="/css/dialog.css">',
            "",
        ]
    )
    lines.extend(render_metadata_header(conversation))
    lines.extend(['<div class="dialog-container">', ""])
    lines.extend(render_conversation_body(conversation))
    lines.extend(["</div>", ""])
    return "\n".join(lines)


def write_hexo_post(
    conversation: Conversation,
    posts_dir: Path,
    override_date: str | None = None,
    output: Path | None = None,
) -> Path:
    post_date = parse_override_date(override_date) or conversation.display_date or datetime.now()
    target = output or default_output_path(conversation, posts_dir, post_date)
    target.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" keeps generated posts identical on Windows and Linux instead
    # of depending on the platform default line ending.
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_hexo_post(conversation, override_date=override_date))
    return target
