from datetime import datetime

import pytest

from chatblog.catalog import (
    ChatEntry,
    entries_from_gemini,
    entries_from_openwebui,
    gemini_url,
    openwebui_url,
)
from chatblog.gemini_web import GeminiListItem


def test_openwebui_entries_use_web_base_and_epoch_timestamps():
    rows = [
        {
            "id": "6bdd393c-fe73-4805-ba2d-8d588c290d0b",
            "title": " File Update ",
            "created_at": 1762000000,
            "updated_at": 1762100000,
        },
        {"id": "", "title": "no id"},
    ]
    entries = entries_from_openwebui(rows, "http://192.168.128.111:3000/")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.key == "openwebui:6bdd393c-fe73-4805-ba2d-8d588c290d0b"
    assert entry.title == "File Update"
    assert entry.url == "http://192.168.128.111:3000/c/6bdd393c-fe73-4805-ba2d-8d588c290d0b"
    assert entry.approximate_date is False
    assert entry.updated_at > entry.created_at


def test_gemini_entries_mark_approximate_dates():
    items = [
        GeminiListItem(chat_id="abcdef123456", title="Philo", group="昨天", approx_date=datetime(2026, 11, 3, 12)),
        GeminiListItem(chat_id="", title="skip"),
    ]
    entries = entries_from_gemini(items)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.key == "gemini:abcdef123456"
    assert entry.url == gemini_url("abcdef123456")
    assert entry.approximate_date is True
    assert entry.group == "昨天"


def test_entry_roundtrip_preserves_tags_and_dates():
    entry = ChatEntry(
        key="openwebui:x",
        provider="openwebui",
        chat_id="x",
        title="T",
        url="u",
        created_at=datetime(2026, 1, 2, 3, 4, 5),
        updated_at=datetime(2026, 1, 3, 3, 4, 5),
    )
    entry.set_tags(
        [
            {"name": "技術程式", "dim": "domain", "confidence": 0.91},
            {"name": "Jev", "dim": "concept", "confidence": 0.4},
        ],
        provider="openjev",
        model="openjev-latest",
    )
    payload = entry.to_dict(status="new")
    restored = ChatEntry.from_dict(payload)
    assert restored.created_at == datetime(2026, 1, 2, 3, 4, 5)
    assert [tag["name"] for tag in restored.tags] == ["技術程式", "Jev"]
    assert restored.classification["provider"] == "openjev"
    assert payload["status"] == "new"
    assert restored.sort_moment == datetime(2026, 1, 3, 3, 4, 5)


def test_urls_are_stable():
    assert openwebui_url("", "abc") == "http://192.168.128.111:3000/c/abc"
    assert openwebui_url("http://nas:3000", "abc") == "http://nas:3000/c/abc"
    assert gemini_url("abc") == "https://gemini.google.com/app/abc"


@pytest.mark.parametrize(
    ("classification", "pending"),
    [
        ({"provider": "rules", "error": "429"}, True),
        ({"provider": "rules"}, True),
        ({"provider": "gemini", "complete": False, "error": "429"}, True),
        ({"provider": "gemini", "complete": False}, True),
        ({"provider": "gemini", "complete": True}, False),
        ({"provider": "openjev", "model": "openjev-0.1", "error": ""}, False),
    ],
)
def test_pending_classification_survives_catalog_roundtrip(classification, pending):
    entry = ChatEntry(key="openwebui:x", provider="openwebui", chat_id="x")
    entry.tags = [{"name": "技術程式", "dim": "domain", "confidence": 0.9}]
    entry.classification = classification
    restored = ChatEntry.from_dict(entry.to_dict())
    assert restored.needs_classification is pending
    assert restored.to_dict()["needs_classification"] is pending
