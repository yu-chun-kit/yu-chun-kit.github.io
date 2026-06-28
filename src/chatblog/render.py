from __future__ import annotations

import html
import re
from datetime import datetime, time
from pathlib import Path

from .models import Conversation, DialogNode
from .normalize import parse_timestamp


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


def process_markdown_content(content: str) -> str:
    escaped = html.escape(content)
    code_blocks: list[str] = []

    def replace_code_block(match: re.Match[str]) -> str:
        lang = html.escape((match.group(1) or "").strip())
        code = match.group(2)
        code_blocks.append(f'<pre><code class="language-{lang}">{code}</code></pre>')
        return f"@@CHATBLOG_CODE_BLOCK_{len(code_blocks) - 1}@@"

    text = re.sub(r"```([^\n`]*)\n(.*?)```", replace_code_block, escaped, flags=re.DOTALL)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)

    chunks: list[str] = []
    for part in re.split(r"(@@CHATBLOG_CODE_BLOCK_\d+@@)", text):
        marker = re.fullmatch(r"@@CHATBLOG_CODE_BLOCK_(\d+)@@", part)
        if marker:
            chunks.append(code_blocks[int(marker.group(1))])
        else:
            chunks.append(part.replace("\n", "<br>"))

    return "".join(chunks)


def _format_message(node: DialogNode) -> list[str]:
    role_class = "user" if node.role == "user" else "ai"
    avatar = "我" if node.role == "user" else "AI"
    content = process_markdown_content(clean_content(node.content))

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


def traverse_with_branches(
    conversation: Conversation,
    message_id: str,
    visited: set[str] | None = None,
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

    children = node.children_ids
    if not children:
        return lines

    lines.extend(traverse_with_branches(conversation, children[0], visited))

    branch_number = 2
    for child_id in children[1:]:
        branch_lines = traverse_with_branches(conversation, child_id, set(visited))
        if not any(line.strip() for line in branch_lines):
            continue

        child = conversation.messages.get(child_id)
        preview = clean_content(child.content if child else "")[:50]
        if len(preview) == 50:
            preview += "..."

        lines.append('<details class="dialog-branch">')
        lines.append(f"<summary>分支 {branch_number}: {html.escape(preview)}</summary>")
        lines.append('<div class="dialog-branch-content">')
        lines.extend(branch_lines)
        lines.append("</div>")
        lines.append("</details>")
        lines.append("")
        branch_number += 1

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
    lines.extend(traverse_with_branches(conversation, conversation.root_id))
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
    target.write_text(render_hexo_post(conversation, override_date=override_date), encoding="utf-8")
    return target
