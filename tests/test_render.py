import json
import re
from pathlib import Path

from chatblog.models import Conversation, DialogNode
from chatblog.normalize import normalize_openwebui_chat
from chatblog.render import (
    clean_content,
    preview_text,
    process_markdown_content,
    render_hexo_post,
    render_node_content,
    slugify_title,
    traverse_with_branches,
)


FIXTURE = Path(__file__).parent / "fixtures" / "openwebui_chat.json"


def load_conversation():
    return normalize_openwebui_chat(json.loads(FIXTURE.read_text(encoding="utf-8")))


def build_wide_branch_conversation() -> Conversation:
    """One node with four continuations, and one nested divergence."""

    def user(mid, text, children, parent=None):
        return DialogNode(id=mid, role="user", content=text, children_ids=children, parent_id=parent)

    def ai(mid, text, children, parent=None):
        return DialogNode(
            id=mid,
            role="assistant",
            content=text,
            children_ids=children,
            parent_id=parent,
            model_name="test-model",
        )

    messages = {
        "m1": user("m1", "第一個問題", ["m2"]),
        "m2": ai("m2", "主線回答開頭。", ["b1", "b2", "b3", "b4"], parent="m1"),
        "b1": ai("b1", "**分支一**：最早的答案。", ["m3"], parent="m2"),
        "m3": user("m3", "主線追問", ["m4"], parent="b1"),
        "m4": ai("m4", "主線追問的回答。", [], parent="m3"),
        "b2": ai("b2", "**分支二**：換個說法。", [], parent="m2"),
        "b3": ai("b3", "**分支三**：先講結論。", ["b3x", "b3y"], parent="m2"),
        "b3x": ai("b3x", "分支三的補充。", [], parent="b3"),
        "b3y": ai("b3y", "分支三的另一個補充。", [], parent="b3"),
        "b4": ai("b4", "**分支四**：完全不同的角度。", [], parent="m2"),
    }

    return Conversation(
        source_provider="openwebui",
        source_chat_id="synthetic",
        title="多分支測試",
        root_id="m1",
        messages=messages,
    )


def test_clean_content_removes_reasoning_blocks():
    assert clean_content('Before <details type="reasoning">secret</details> After') == "Before  After"


def test_markdown_processing_escapes_html_and_formats_code():
    html = process_markdown_content("Hello <x> `code`\n```python\nprint('x')\n```")

    assert "&lt;x&gt;" in html
    assert "<code>code</code>" in html
    assert '<pre><code class="language-python">' in html
    assert "print('x')" in html


def test_markdown_processing_keeps_structure():
    html = process_markdown_content(
        "# 標題\n\n- 項目一\n- 項目二\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n> 引言"
    )

    assert "<h1>標題</h1>" in html
    assert "<ul>" in html and "<li>項目一</li>" in html
    assert "<table>" in html and "<td>1</td>" in html
    assert "<blockquote>" in html


def test_markdown_single_newline_becomes_line_break():
    assert "<br" in process_markdown_content("第一行\n第二行")


def test_render_node_content_keeps_html_messages_intact():
    node = DialogNode(
        id="assistant",
        role="assistant",
        content="<h3>標題</h3><p>答案</p><script>alert(1)</script>",
        content_format="html",
    )

    rendered = render_node_content(node)

    assert "<h3>標題</h3>" in rendered
    assert "<p>答案</p>" in rendered
    assert "script" not in rendered


def test_traverse_with_branches_outputs_details():
    conversation = load_conversation()
    lines = "\n".join(traverse_with_branches(conversation, conversation.root_id))

    assert '<details class="dialog-branch">' in lines
    assert "Alternative branch" in lines
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in lines
    assert "secret" not in lines


def test_preview_text_strips_markup_and_truncates():
    node = DialogNode(
        id="a",
        role="assistant",
        content="<p><b>粗體</b> 與 **星號** 還有  多餘空白</p>",
        content_format="html",
    )

    assert preview_text(node) == "粗體 與 星號 還有 多餘空白"
    assert preview_text(None) == "（空訊息）"
    assert preview_text(node, limit=5).endswith("...")
    assert len(preview_text(node, limit=5)) <= 8


def test_wide_branching_uses_unique_labels_at_the_divergence_point():
    conversation = build_wide_branch_conversation()

    post = render_hexo_post(conversation, override_date="2026-01-01")
    summaries = re.findall(r"<summary>(.*?)</summary>", post)

    assert len(summaries) == 4
    assert ["分支 2/4", "分支 3/4", "分支 4/4"] == [s.split("：")[0] for s in summaries if "嵌套" not in s]
    nested = [s for s in summaries if "嵌套" in s]
    assert nested == ["分支 2/2（嵌套第 2 層）：分支三的另一個補充。"]
    # duplicated "分支 2" labels were the old bug; every label is now unique
    labels = [s.split("：")[0] for s in summaries]
    assert len(set(labels)) == len(labels)

    assert post.count('<details class="dialog-branch">') == 3
    assert post.count('<details class="dialog-branch dialog-branch-nested">') == 1

    # the fork is announced where it happens, before the main line continues
    assert post.index("此處有 4 個分支") < post.index("主線追問")
    assert "此處有 2 個分支" in post

    for summary in summaries:
        assert "<" not in summary
        assert "**" not in summary


def test_chat_with_two_roots_renders_every_tree():
    """OpenWebUI adds a second root when a user message is edited."""
    conversation = Conversation(
        source_provider="openwebui",
        source_chat_id="two-roots",
        title="兩段對話",
        root_id="r1",
        messages={
            "r1": DialogNode(id="r1", role="user", content="原本的問題", children_ids=["a1"]),
            "a1": DialogNode(
                id="a1", role="assistant", content="原本的回答", parent_id="r1", children_ids=[]
            ),
            "r2": DialogNode(id="r2", role="user", content="編輯後的問題", children_ids=["a2", "a3"]),
            "a2": DialogNode(
                id="a2", role="assistant", content="編輯後的第一個回答", parent_id="r2", children_ids=[]
            ),
            "a3": DialogNode(
                id="a3", role="assistant", content="編輯後的第二個回答", parent_id="r2", children_ids=[]
            ),
        },
    )

    post = render_hexo_post(conversation, override_date="2026-01-01")

    assert post.count('<div class="dialog-message') == 5
    assert "message_count: 5" in post
    for text in ("原本的問題", "原本的回答", "編輯後的問題", "編輯後的第一個回答", "編輯後的第二個回答"):
        assert text in post, text
    assert "另一段對話 1/1" in post
    # the extra root itself plus the two-way fork inside it
    assert post.count('<details class="dialog-branch') == 2
    assert "此處有 2 個分支" in post


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
