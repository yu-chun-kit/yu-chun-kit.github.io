from datetime import datetime
from pathlib import Path

from chatblog.ledger import (
    Ledger,
    PublishedRecord,
    content_hash,
    conversation_key,
    read_front_matter,
)

POST = """---
title: "{title}"
date: 2026-10-02 09:00:00
tags:
  - AI对话
categories:
  - AI对话
source_provider: {provider}
source_chat_id: "{chat_id}"
---

body
"""


def write_post(posts: Path, name: str, title: str, provider: str, chat_id: str) -> Path:
    path = posts / name
    path.write_text(
        POST.format(title=title, provider=provider, chat_id=chat_id), encoding="utf-8"
    )
    return path


def test_read_front_matter_handles_crlf_and_quotes(tmp_path: Path):
    path = tmp_path / "post.md"
    path.write_bytes(
        b'---\r\ntitle: "A \\"quoted\\" title"\r\nsource_provider: gemini\r\n'
        b'source_chat_id: "abc123"\r\n---\r\nbody\r\n'
    )
    fields = read_front_matter(path)
    assert fields["title"] == 'A "quoted" title'
    assert fields["source_provider"] == "gemini"
    assert fields["source_chat_id"] == "abc123"
    assert read_front_matter(tmp_path / "missing.md") == {}


def test_seed_from_posts_imports_existing_posts(tmp_path: Path):
    posts = tmp_path / "source" / "_posts"
    posts.mkdir(parents=True)
    write_post(posts, "2026-10-02-a.md", "Chat A", "openwebui", "chat-a")
    write_post(posts, "2026-10-03-b.md", "Chat B", "gemini", "gem-b")
    (posts / "plain.md").write_text("---\ntitle: no source\n---\n", encoding="utf-8")

    ledger = Ledger(tmp_path / ".chatblog" / "index.json").load(posts, repo_root=tmp_path)

    assert set(ledger.records) == {"openwebui:chat-a", "gemini:gem-b"}
    record = ledger.records["gemini:gem-b"]
    assert record.title == "Chat B"
    assert record.post_path == "source/_posts/2026-10-03-b.md"
    assert record.published_at == "2026-10-02 09:00:00"


def test_save_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / "index.json"
    ledger = Ledger(path)
    ledger.upsert(
        PublishedRecord(
            key=conversation_key("openwebui", "abc"),
            provider="openwebui",
            chat_id="abc",
            title="標題",
            post_path="source/_posts/x.md",
            tags=["AI对话", "OpenWebUI"],
            private=True,
        )
    )
    ledger.save()

    reloaded = Ledger(path).load()
    record = reloaded.get("openwebui:abc")
    assert record is not None
    assert record.title == "標題"
    assert record.private is True
    assert record.tags == ["AI对话", "OpenWebUI"]


def test_stale_detects_title_and_time_changes():
    record = PublishedRecord(
        key="k",
        provider="openwebui",
        chat_id="k",
        title="Old",
        source_updated_at="2026-10-01T10:00:00",
    )
    assert record.stale("Old", "2026-10-01T10:00:30") is False
    assert record.stale("Old", "2026-10-02T10:00:00") is True
    assert record.stale("New", "2026-10-01T10:00:00") is True
    assert record.stale("Old", None) is False


def test_content_hash_is_stable():
    assert content_hash("a", "b") == content_hash("a", "b")
    assert content_hash("a", "b") != content_hash("a", "c")
