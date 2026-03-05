#!/usr/bin/env python3
"""
Convert OpenWebUI chat export to Hexo blog post with dialog format.
Usage: python3 convert_chat.py <chat_id> [output_file]

Setup:
  1. Copy scripts/.env.example to scripts/.env
  2. Fill in your OpenWebUI API token
  3. Run the script
"""

import json
import sys
import re
import urllib.request
import os
from datetime import datetime
from pathlib import Path


# Load configuration from .env file
def load_env():
    """Load environment variables from .env file."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key, value)


load_env()

API_BASE = os.environ.get("OPENWEBUI_API_BASE", "http://192.168.128.111:3000/api/v1")
AUTH_TOKEN = os.environ.get("OPENWEBUI_API_TOKEN", "")

if not AUTH_TOKEN:
    print("Error: OPENWEBUI_API_TOKEN not set in scripts/.env")
    print("Please copy scripts/.env.example to scripts/.env and add your token")
    sys.exit(1)


def fetch_chat(chat_id):
    """Fetch chat data from API."""
    url = f"{API_BASE}/chats/{chat_id}"
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}", "Accept": "application/json"}

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def escape_yaml(text):
    """Escape special characters for YAML front-matter."""
    return text.replace('"', '\\"').replace("\n", " ")


def process_markdown_content(content):
    """Convert markdown content to HTML for dialog display."""
    import html

    # Escape HTML first
    content = html.escape(content)

    # Handle code blocks ```language\ncode\n```
    def replace_code_block(match):
        lang = match.group(1) or ""
        code = match.group(2)
        return f'<pre><code class="language-{lang}">{code}</code></pre>'

    content = re.sub(
        r"```(\w*)\n(.*?)```", replace_code_block, content, flags=re.DOTALL
    )

    # Handle inline code `code`
    content = re.sub(r"`([^`]+)`", r"<code>\1</code>", content)

    # Handle bold **text**
    content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", content)

    # Handle italic *text*
    content = re.sub(r"\*(.*?)\*", r"<em>\1</em>", content)

    # Convert newlines to <br> tags (no <p> wrappers to avoid spacing issues)
    # But don't add <br> inside pre blocks
    parts = []
    current = ""
    in_pre = False

    for line in content.split("\n"):
        if "<pre>" in line:
            in_pre = True
            if current:
                parts.append(current)
                current = ""
            parts.append(line)
        elif "</pre>" in line:
            in_pre = False
            parts.append(line)
        elif in_pre:
            parts.append(line)
        else:
            if current:
                current += "<br>" + line
            else:
                current = line

    if current:
        parts.append(current)

    return "".join(parts)


def clean_content(content):
    """Remove reasoning/thinking blocks and clean up content."""
    # Remove <details type="reasoning"> blocks
    content = re.sub(
        r'<details type="reasoning"[^>]*>.*?</details>', "", content, flags=re.DOTALL
    )
    # Remove HTML entities
    content = (
        content.replace("&quot;", '"')
        .replace("&#x27;", "'")
        .replace("&gt;", ">")
        .replace("&lt;", "<")
    )
    # Clean up extra whitespace
    content = content.strip()
    return content


def format_timestamp(ts):
    """Convert Unix timestamp to readable format."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def format_message(msg):
    """Format a single message as HTML."""
    role = msg["role"]
    content = msg["content"]
    model = msg.get("modelName", "")

    content = process_markdown_content(content)

    if role == "user":
        return [
            '<div class="dialog-message user">',
            '  <div class="dialog-avatar">我</div>',
            f'  <div class="dialog-bubble">{content}</div>',
            "</div>",
            "",
        ]
    else:
        model_html = f'<div class="dialog-model">{model}</div>' if model else ""
        return [
            '<div class="dialog-message ai">',
            '  <div class="dialog-avatar">AI</div>',
            f'  <div class="dialog-bubble">{model_html}<div class="dialog-content">{content}</div></div>',
            "</div>",
            "",
        ]


def traverse_with_branches(messages, msg_id, visited=None, is_main_branch=True):
    """Traverse conversation and return formatted HTML lines.

    Main branch (first child) is shown normally.
    Other branches are wrapped in <details> elements.
    Empty/error branches are skipped.
    """
    if visited is None:
        visited = set()

    if msg_id in visited or msg_id not in messages:
        return []

    visited.add(msg_id)
    msg = messages[msg_id]
    content = clean_content(msg.get("content", ""))

    lines = []

    # Add current message
    if content:
        msg_data = {
            "role": msg.get("role", "unknown"),
            "content": content,
            "timestamp": msg.get("timestamp", 0),
            "modelName": msg.get("modelName", ""),
        }
        lines.extend(format_message(msg_data))

    # Handle children
    children = msg.get("childrenIds", [])

    if len(children) == 0:
        pass
    elif len(children) == 1:
        # Only one child, continue normally
        lines.extend(
            traverse_with_branches(messages, children[0], visited, is_main_branch)
        )
    else:
        # Multiple children - first is main branch, others are folded
        # Main branch (first child)
        lines.extend(traverse_with_branches(messages, children[0], visited, True))

        # Other branches (folded) - only include if they have content
        branch_num = 2
        for child_id in children[1:]:
            # Check if this branch has any non-empty content
            branch_visited = set(visited)
            branch_lines = traverse_with_branches(
                messages, child_id, branch_visited, False
            )

            # Skip empty branches (no actual content)
            if not branch_lines or all(
                line.strip() in ["", "</div>"] for line in branch_lines
            ):
                continue

            # Get preview text from first message in branch
            child_msg = messages.get(child_id, {})
            preview = clean_content(child_msg.get("content", ""))[:50]
            if len(preview) == 50:
                preview += "..."

            lines.append(f'<details class="dialog-branch">')
            lines.append(f"<summary>分支 {branch_num}: {preview}</summary>")
            lines.append('<div class="dialog-branch-content">')
            lines.extend(branch_lines)
            lines.append("</div>")
            lines.append("</details>")
            lines.append("")
            branch_num += 1

    return lines


def generate_hexo_post(chat_data, output_file=None):
    """Generate Hexo blog post from chat data."""
    messages = chat_data["chat"]["history"]["messages"]
    title = chat_data.get("title", "AI对话记录")

    # Find root message
    root_id = None
    for msg_id, msg in messages.items():
        if msg.get("parentId") is None:
            root_id = msg_id
            break

    if not root_id:
        print("Error: Could not find root message")
        return

    # Get tags from API response
    tags = chat_data.get("meta", {}).get("tags", [])
    if not tags:
        tags = ["AI对话"]

    # Generate filename with full path to source/_posts/
    if not output_file:
        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_title = re.sub(r"[^\w\s-]", "", title)[:30].strip().replace(" ", "-")
        output_file = f"source/_posts/{date_str}-{safe_title}.md"

    # Generate post content
    post_lines = [
        "---",
        f'title: "{escape_yaml(title)}"',
        f"date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "tags:",
    ]

    for tag in tags:
        post_lines.append(f"  - {tag}")

    post_lines.extend(
        [
            "categories:",
            "  - AI对话",
            "layout: dialog",
            "css: /css/dialog.css",
            "---",
            "",
            '<link rel="stylesheet" href="/css/dialog.css">',
            "",
            '<div class="dialog-container">',
            "",
        ]
    )

    # Traverse with branch support
    conversation_lines = traverse_with_branches(messages, root_id)
    post_lines.extend(conversation_lines)

    post_lines.extend(["</div>", ""])

    post_content = "\n".join(post_lines)

    # Write to file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(post_content)

    print(f"Generated: {output_file}")
    return output_file


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 convert_chat.py <chat_id> [output_file]")
        print("Example: python3 convert_chat.py 1d75ee42-34a1-444f-be66-2866a80fdae1")
        print("\nSetup:")
        print("  1. Copy scripts/.env.example to scripts/.env")
        print("  2. Add your OpenWebUI API token to scripts/.env")
        sys.exit(1)

    chat_id = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        print(f"Fetching chat {chat_id}...")
        chat_data = fetch_chat(chat_id)
        generate_hexo_post(chat_data, output_file)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
