from pathlib import Path

import pytest

from chatblog.catalog import ChatEntry
from chatblog.models import Conversation, DialogNode
from chatblog.publish import (
    PRIVATE_MARKER,
    PublishOptions,
    _existing_target,
    coarse_post_tags,
    ensure_gitignored,
)
from chatblog.taxonomy import Taxonomy, load_taxonomy


def make_entry(tags=None) -> ChatEntry:
    entry = ChatEntry(key="openwebui:x", provider="openwebui", chat_id="x", title="標題")
    entry.tags = tags or []
    return entry


def test_coarse_post_tags_only_use_domain():
    taxonomy = load_taxonomy()
    entry = make_entry(
        [
            {"name": "技術程式", "dim": "domain", "confidence": 0.9},
            {"name": "AI/LLM", "dim": "subdomain", "confidence": 0.8},
        ]
    )
    assert coarse_post_tags(entry, taxonomy) == ["AI对话", "OpenWebUI", "技術程式"]


def test_coarse_post_tags_without_classification():
    assert coarse_post_tags(make_entry(), load_taxonomy()) == ["AI对话", "OpenWebUI"]


def test_ensure_gitignored_appends_once_and_keeps_lf(tmp_path: Path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/\npublic/\n", encoding="utf-8")

    ensure_gitignored(tmp_path, ["source/_posts/a.md", "source/images/gemini/x/"])
    text = gitignore.read_text(encoding="utf-8")
    assert PRIVATE_MARKER in text
    assert "source/_posts/a.md" in text
    assert text.endswith("\n")
    assert "\r\n" not in text

    ensure_gitignored(tmp_path, ["source/_posts/a.md"])
    assert gitignore.read_text(encoding="utf-8").count("source/_posts/a.md") == 1


def test_ensure_gitignored_preserves_crlf(tmp_path: Path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_bytes(b"node_modules/\r\npublic/\r\n")
    ensure_gitignored(tmp_path, ["source/_posts/private.md"])
    raw = gitignore.read_bytes()
    assert b"node_modules/\r\n" in raw
    assert b"source/_posts/private.md\r\n" in raw


def test_existing_target_keeps_other_chats_apart(tmp_path: Path):
    posts = tmp_path / "posts"
    posts.mkdir()
    target = posts / "2026-10-02-title.md"
    target.write_text(
        '---\ntitle: "x"\nsource_provider: openwebui\nsource_chat_id: "other"\n---\n',
        encoding="utf-8",
    )
    conversation = Conversation(
        source_provider="openwebui",
        source_chat_id="new-chat-id",
        title="title",
        root_id="u",
        messages={"u": DialogNode(id="u", role="user", content="hi")},
    )
    from datetime import datetime

    resolved = _existing_target(target, conversation, posts, datetime(2026, 10, 2))
    assert resolved != target
    assert resolved.name.startswith("2026-10-02-title-")


def test_existing_target_overwrites_the_same_chat(tmp_path: Path):
    posts = tmp_path / "posts"
    posts.mkdir()
    target = posts / "2026-10-02-title.md"
    target.write_text(
        '---\nsource_provider: openwebui\nsource_chat_id: "same"\n---\n', encoding="utf-8"
    )
    conversation = Conversation(
        source_provider="openwebui",
        source_chat_id="same",
        title="title",
        root_id="u",
        messages={"u": DialogNode(id="u", role="user", content="hi")},
    )
    from datetime import datetime

    assert _existing_target(target, conversation, posts, datetime(2026, 10, 2)) == target


def test_publish_options_defaults():
    options = PublishOptions()
    assert options.download_assets is True
    assert options.private is False
    assert options.date == ""


def test_open_external_rejects_non_http():
    from chatblog.studio import open_external

    with pytest.raises(ValueError):
        open_external("file:///etc/passwd")


def test_publish_entry_writes_post_and_returns_record(tmp_path: Path, monkeypatch):
    from datetime import datetime

    from chatblog.config import Settings
    from chatblog.publish import publish_entry

    posts = tmp_path / "source" / "_posts"
    posts.mkdir(parents=True)
    settings = Settings(repo_root=tmp_path, posts_dir=posts, data_dir=tmp_path / ".chatblog")
    monkeypatch.setattr("chatblog.config.load_settings", lambda: settings)

    conversation = Conversation(
        source_provider="openwebui",
        source_chat_id="x",
        title="測試對話",
        root_id="u1",
        created_at=datetime(2026, 10, 1, 8, 0),
        messages={
            "u1": DialogNode(id="u1", role="user", content="你好", children_ids=["a1"]),
            "a1": DialogNode(
                id="a1",
                role="assistant",
                content="嗨",
                parent_id="u1",
                children_ids=[],
                model_name="test-model",
            ),
        },
    )
    monkeypatch.setattr(
        "chatblog.publish.fetch_openwebui", lambda entry, options: conversation.model_copy(deep=True)
    )

    entry = make_entry(
        [
            {"name": "技術程式", "dim": "domain", "confidence": 0.9},
            {"name": "AI/LLM", "dim": "subdomain", "confidence": 0.8},
        ]
    )
    result, record = publish_entry(entry, load_taxonomy(), PublishOptions(download_assets=False))

    assert result.ok is True
    assert record is not None
    assert record.key == "openwebui:x"
    post = tmp_path / record.post_path
    assert post.is_file()
    body = post.read_text(encoding="utf-8")
    assert "測試對話" in body
    assert "- 技術程式" in body
    assert "- AI/LLM" not in body  # fine-grained tags stay in the studio


def test_publish_entry_private_appends_gitignore(tmp_path: Path, monkeypatch):
    from datetime import datetime

    from chatblog.config import Settings
    from chatblog.publish import publish_entry

    posts = tmp_path / "source" / "_posts"
    posts.mkdir(parents=True)
    settings = Settings(repo_root=tmp_path, posts_dir=posts, data_dir=tmp_path / ".chatblog")
    monkeypatch.setattr("chatblog.config.load_settings", lambda: settings)
    conversation = Conversation(
        source_provider="openwebui",
        source_chat_id="private-chat",
        title="私人對話",
        root_id="u1",
        created_at=datetime(2026, 10, 1, 8, 0),
        messages={"u1": DialogNode(id="u1", role="user", content="secret")},
    )
    monkeypatch.setattr(
        "chatblog.publish.fetch_openwebui", lambda entry, options: conversation.model_copy(deep=True)
    )

    entry = ChatEntry(key="openwebui:private-chat", provider="openwebui", chat_id="private-chat", title="私人對話")
    result, record = publish_entry(
        entry, load_taxonomy(), PublishOptions(download_assets=False, private=True)
    )
    assert result.ok
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert record.post_path in text
    assert PRIVATE_MARKER in text

