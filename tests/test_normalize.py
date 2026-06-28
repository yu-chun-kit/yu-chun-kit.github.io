import json
from pathlib import Path

from chatblog.normalize import normalize_chat_list, normalize_openwebui_chat


FIXTURE = Path(__file__).parent / "fixtures" / "openwebui_chat.json"


def test_normalize_openwebui_chat():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    conversation = normalize_openwebui_chat(raw)

    assert conversation.source_provider == "openwebui"
    assert conversation.source_chat_id == "chat-123"
    assert conversation.title == "Test **Chat** / Export?"
    assert conversation.root_id == "root"
    assert conversation.message_count == 4
    assert conversation.branch_count == 1
    assert conversation.models == ["Other Model", "Test Model"]
    assert conversation.tags == ["general", "backup"]


def test_normalize_chat_list_shapes():
    raw = {"chats": [{"id": "one", "title": "First"}, {"id": "two", "title": "Second"}]}
    chats = normalize_chat_list(raw)

    assert [chat.id for chat in chats] == ["one", "two"]
    assert chats[0].title == "First"
