#!/usr/bin/env python3
"""
Interactive chat publisher for OpenWebUI to Hexo blog.

Usage:
  python3 publish_chat.py              # Interactive mode - list and select
  python3 publish_chat.py <chat_id>    # Direct mode (like old script)
  python3 publish_chat.py --date YYYY-MM-DD <chat_id>  # Override date

Features:
  - List recent chats from API
  - Preview before publishing
  - Use chat timestamp (not today)
  - Confirm before git commit

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


def api_request(endpoint):
    """Make API request and return JSON."""
    url = f"{API_BASE}{endpoint}"
    headers = {"Authorization": f"Bearer {AUTH_TOKEN}", "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_chat(chat_id):
    """Fetch single chat data."""
    return api_request(f"/chats/{chat_id}")


def fetch_recent_chats(limit=20):
    """Fetch list of recent chats."""
    # Try different possible endpoints
    endpoints = [
        "/chats",
        "/chats/",
    ]

    for endpoint in endpoints:
        try:
            data = api_request(endpoint)
            if isinstance(data, dict) and "chats" in data:
                return data["chats"][:limit]
            elif isinstance(data, list):
                return data[:limit]
        except Exception as e:
            continue

    # Fallback: return empty list
    print("⚠️  无法获取对话列表，可能需要检查API端点")
    return []


def escape_yaml(text):
    """Escape special characters for YAML front-matter."""
    return text.replace('"', '\\"').replace("\n", " ")


def process_markdown_content(content):
    """Convert markdown content to HTML for dialog display."""
    import html

    # Escape HTML first
    content = html.escape(content)

    # Handle code blocks
    def replace_code_block(match):
        lang = match.group(1) or ""
        code = match.group(2)
        return f'<pre><code class="language-{lang}">{code}</code></pre>'

    content = re.sub(
        r"```(\w*)\n(.*?)```", replace_code_block, content, flags=re.DOTALL
    )

    # Handle inline code
    content = re.sub(r"`([^`]+)`", r"<code>\1</code>", content)

    # Handle bold and italic
    content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", content)
    content = re.sub(r"\*(.*?)\*", r"<em>\1</em>", content)

    # Convert newlines to <br> tags (no <p> wrappers)
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
    """Traverse conversation and return formatted HTML lines."""
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
        lines.extend(
            traverse_with_branches(messages, children[0], visited, is_main_branch)
        )
    else:
        # Multiple children - first is main branch, others are folded
        lines.extend(traverse_with_branches(messages, children[0], visited, True))

        branch_num = 2
        for child_id in children[1:]:
            branch_visited = set(visited)
            branch_lines = traverse_with_branches(
                messages, child_id, branch_visited, False
            )

            if not branch_lines or all(
                line.strip() in ["", "</div>"] for line in branch_lines
            ):
                continue

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


def get_chat_timestamp(chat_data):
    """Extract chat creation timestamp from data."""
    # Try different possible locations for timestamp
    messages = chat_data.get("chat", {}).get("history", {}).get("messages", {})

    # Find first message (root)
    for msg_id, msg in messages.items():
        if msg.get("parentId") is None:
            ts = msg.get("timestamp", 0)
            if ts:
                return ts

    # Fallback to chat metadata
    return chat_data.get("created_at", chat_data.get("updated_at", 0))


def count_messages(chat_data):
    """Count total messages in chat."""
    messages = chat_data.get("chat", {}).get("history", {}).get("messages", {})
    return len(messages)


def get_preview_messages(chat_data, count=2):
    """Get first few messages for preview."""
    messages = chat_data.get("chat", {}).get("history", {}).get("messages", {})

    # Find root and traverse main branch
    root_id = None
    for msg_id, msg in messages.items():
        if msg.get("parentId") is None:
            root_id = msg_id
            break

    if not root_id:
        return []

    previews = []
    current_id = root_id
    while current_id and len(previews) < count * 2:  # Get pairs of messages
        msg = messages.get(current_id, {})
        content = clean_content(msg.get("content", ""))[:100]
        if len(content) == 100:
            content += "..."

        role = "用户" if msg.get("role") == "user" else "AI"
        if content:
            previews.append(f"  {role}: {content}")

        # Follow main branch (first child)
        children = msg.get("childrenIds", [])
        current_id = children[0] if children else None

    return previews[: count * 2]


def generate_hexo_post(chat_data, override_date=None, output_file=None):
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
        return None

    # Get tags
    tags = chat_data.get("meta", {}).get("tags", [])
    if not tags:
        tags = ["AI对话"]

    # Get timestamp - use chat time, not today
    if override_date:
        # Parse override date and use it
        date_obj = datetime.strptime(override_date, "%Y-%m-%d")
        date_str = date_obj.strftime("%Y-%m-%d")
        time_str = date_obj.strftime("%H:%M:%S") if " " in override_date else "00:00:00"
    else:
        # Use chat timestamp
        timestamp = get_chat_timestamp(chat_data)
        if timestamp:
            date_obj = datetime.fromtimestamp(timestamp)
            date_str = date_obj.strftime("%Y-%m-%d")
            time_str = date_obj.strftime("%H:%M:%S")
        else:
            # Fallback to now
            date_obj = datetime.now()
            date_str = date_obj.strftime("%Y-%m-%d")
            time_str = date_obj.strftime("%H:%M:%S")

    # Generate filename
    if not output_file:
        safe_title = re.sub(r"[^\w\s-]", "", title)[:30].strip().replace(" ", "-")
        output_file = f"source/_posts/{date_str}-{safe_title}.md"

    # Generate post content
    post_lines = [
        "---",
        f'title: "{escape_yaml(title)}"',
        f"date: {date_str} {time_str}",
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

    conversation_lines = traverse_with_branches(messages, root_id)
    post_lines.extend(conversation_lines)
    post_lines.extend(["</div>", ""])

    post_content = "\n".join(post_lines)

    # Write to file
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(post_content)

    return output_file


def interactive_mode():
    """Run interactive mode."""
    print("🔍 获取最近对话...\n")

    chats = fetch_recent_chats(limit=15)

    if not chats:
        print("没有获取到对话列表。请直接使用对话ID:")
        print("  python3 publish_chat.py <chat_id>")
        print("\nSetup:")
        print("  1. Copy scripts/.env.example to scripts/.env")
        print("  2. Add your OpenWebUI API token to scripts/.env")
        sys.exit(1)

    # Display list
    print("📅 最近对话:")
    for i, chat in enumerate(chats, 1):
        title = chat.get("title", "无标题")
        chat_id = chat.get("id", "")

        # Format timestamp
        ts = chat.get("updated_at", chat.get("created_at", 0))
        if ts:
            date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        else:
            date_str = "未知日期"

        print(f"  {i:2}. {title[:40]:<40} ({date_str})")

    print()

    # Get selection
    while True:
        try:
            choice = input(f"选择编号 [1-{len(chats)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(chats):
                selected = chats[idx]
                break
            else:
                print(f"请输入1到{len(chats)}之间的数字")
        except ValueError:
            print("请输入有效数字")

    chat_id = selected.get("id")
    title = selected.get("title", "无标题")

    print(f"\n🔄 获取对话详情: {title}...")

    try:
        chat_data = fetch_chat(chat_id)
    except Exception as e:
        print(f"❌ 获取失败: {e}")
        sys.exit(1)

    # Show preview
    msg_count = count_messages(chat_data)
    previews = get_preview_messages(chat_data, count=2)

    print(f"\n📝 预览: {title}")
    print(f"   消息数: {msg_count}")
    print()
    for preview in previews:
        print(preview)

    # Date handling
    ts = get_chat_timestamp(chat_data)
    if ts:
        chat_date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    else:
        chat_date = datetime.now().strftime("%Y-%m-%d")

    print(f"\n📅 对话日期: {chat_date}")
    print("   (直接回车使用对话日期，输入日期如 2026-01-15 覆盖)")
    date_input = input("日期: ").strip()

    override_date = None
    if date_input:
        try:
            datetime.strptime(date_input, "%Y-%m-%d")
            override_date = date_input
            print(f"   使用自定义日期: {override_date}")
        except ValueError:
            print("   日期格式错误，使用对话日期")

    # Confirm
    print()
    confirm = input("确认发布? [Y/n]: ").strip().lower()
    if confirm and confirm not in ("y", "yes", "是"):
        print("❌ 已取消")
        sys.exit(0)

    # Generate
    print("\n📝 生成博客文章...")
    output_file = generate_hexo_post(chat_data, override_date=override_date)

    if output_file:
        print(f"✅ 已生成: {output_file}")
    else:
        print("❌ 生成失败")
        sys.exit(1)

    # Git commit option
    print()
    do_commit = input("提交到git? [Y/n]: ").strip().lower()
    if not do_commit or do_commit in ("y", "yes", "是"):
        import subprocess

        try:
            subprocess.run(["git", "add", output_file], check=True)
            safe_title = re.sub(r"[^\w\s-]", "", title)[:30]
            subprocess.run(
                ["git", "commit", "-m", f"post: add AI dialog - {safe_title}"],
                check=True,
            )
            print("✅ 已提交")
        except subprocess.CalledProcessError as e:
            print(f"⚠️  git提交失败: {e}")


def direct_mode(chat_id, override_date=None):
    """Run direct mode (like old script)."""
    print(f"🔄 获取对话 {chat_id}...")

    try:
        chat_data = fetch_chat(chat_id)
    except Exception as e:
        print(f"❌ 获取失败: {e}")
        sys.exit(1)

    title = chat_data.get("title", "AI对话记录")
    print(f"📝 生成博客文章: {title}...")

    output_file = generate_hexo_post(chat_data, override_date=override_date)

    if output_file:
        print(f"✅ 已生成: {output_file}")
    else:
        print("❌ 生成失败")
        sys.exit(1)


def main():
    # Check for date override flag
    override_date = None
    args = sys.argv[1:]

    if "--date" in args:
        idx = args.index("--date")
        if idx + 1 < len(args):
            override_date = args[idx + 1]
            args.pop(idx)
            args.pop(idx)
        else:
            print("错误: --date 需要参数 (YYYY-MM-DD)")
            sys.exit(1)

    if len(args) == 0:
        # Interactive mode
        interactive_mode()
    elif len(args) == 1:
        # Direct mode with chat_id
        direct_mode(args[0], override_date=override_date)
    else:
        print("用法:")
        print("  python3 publish_chat.py              # 交互模式")
        print("  python3 publish_chat.py <chat_id>    # 直接模式")
        print("  python3 publish_chat.py --date 2026-01-15 <chat_id>")
        print("\nSetup:")
        print("  1. Copy scripts/.env.example to scripts/.env")
        print("  2. Add your OpenWebUI API token to scripts/.env")
        sys.exit(1)


if __name__ == "__main__":
    main()
