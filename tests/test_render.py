import json
from pathlib import Path

from chatblog.normalize import normalize_openwebui_chat
from chatblog.render import (
    clean_content,
    process_markdown_content,
    render_hexo_post,
    slugify_title,
    traverse_with_branches,
)


FIXTURE = Path(__file__).parent / "fixtures" / "openwebui_chat.json"


def load_conversation():
    return normalize_openwebui_chat(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_clean_content_removes_reasoning_blocks():
    assert clean_content('Before <details type="reasoning">secret</details> After') == "Before  After"


def test_markdown_processing_escapes_html_and_formats_code():
    html = process_markdown_content("Hello <x> `code`\n```python\nprint('x')\n```")

    assert "&lt;x&gt;" in html
    assert "<code>code</code>" in html
    assert '<pre><code class="language-python">' in html
    assert "print(&#x27;x&#x27;)" in html


def test_traverse_with_branches_outputs_details():
    conversation = load_conversation()
    lines = "\n".join(traverse_with_branches(conversation, conversation.root_id))

    assert '<details class="dialog-branch">' in lines
    assert "Alternative branch" in lines
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in lines
    assert "secret" not in lines


def test_render_hexo_post_includes_metadata_front_matter():
    conversation = load_conversation()
    post = render_hexo_post(conversation, override_date="2026-03-01")

    assert 'source_provider: "openwebui"' in post
    assert 'source_chat_id: "chat-123"' in post
    assert "message_count: 4" in post
    assert "branch_count: 1" in post
    assert '<section class="dialog-meta">' in post
    assert "對話備份" in post
    assert "Test Model" in post


def test_slugify_title_keeps_readable_title():
    assert slugify_title("Test **Chat** / Export?") == "Test-Chat-Export"
    assert slugify_title("   ") == "ai-dialog"
