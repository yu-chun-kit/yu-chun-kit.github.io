import base64
import json
import sqlite3
from pathlib import Path

import pytest

from chatblog.owui_local import (
    LocalSourceConfig,
    LocalSourceError,
    SqliteFileSource,
    attach_local_images,
    build_program,
    normalize_local_chat,
    parse_result,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 24

CHAT_ID = "chat-1"
ROOT = "m1"


def build_database(path: Path, uploads_dir: Path | None = None) -> Path:
    """Create a miniature webui.db with one chat, one image and one branch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE chat (
            id TEXT PRIMARY KEY, user_id TEXT, title TEXT, created_at INTEGER,
            updated_at INTEGER, chat TEXT, meta TEXT
        );
        CREATE TABLE chat_message (
            id TEXT, chat_id TEXT, user_id TEXT, role TEXT, parent_id TEXT,
            content TEXT, files TEXT, created_at INTEGER
        );
        CREATE TABLE file (
            id TEXT, user_id TEXT, filename TEXT, path TEXT, meta TEXT, data TEXT
        );
        """
    )

    file_id = "file-1"
    stored_path = f"/app/backend/data/uploads/{file_id}_IMG_1.png"
    if uploads_dir is not None:
        uploads_dir.mkdir(parents=True, exist_ok=True)
        (uploads_dir / f"{file_id}_IMG_1.png").write_bytes(PNG_BYTES)
    db.execute(
        "INSERT INTO file VALUES (?,?,?,?,?,?)",
        (
            file_id,
            "user-1",
            "IMG_1.png",
            stored_path,
            json.dumps({"name": "IMG_1.png", "content_type": "image/png", "size": len(PNG_BYTES)}),
            "{}",
        ),
    )

    messages = {
        ROOT: {
            "id": ROOT,
            "role": "user",
            "content": "附圖的木棍塔要怎麼蓋？",
            "parentId": None,
            "childrenIds": ["a1"],
            "timestamp": 1790000000,
            "files": [
                {
                    "type": "file",
                    "id": file_id,
                    "url": file_id,
                    "name": "IMG_1.png",
                    "content_type": "image/png",
                    "file": {"id": file_id, "filename": "IMG_1.png", "data": {"content": "x" * 20}},
                }
            ],
        },
        "a1": {
            "id": "a1",
            "role": "assistant",
            "content": "**主線**答案",
            "parentId": ROOT,
            "childrenIds": ["u2", "b1"],
            "modelName": "deepseek-test",
        },
        "u2": {"id": "u2", "role": "user", "content": "追問", "parentId": "a1", "childrenIds": []},
        "b1": {"id": "b1", "role": "assistant", "content": "**分支**答案", "parentId": "a1", "childrenIds": []},
    }
    db.execute(
        "INSERT INTO chat VALUES (?,?,?,?,?,?,?)",
        (
            CHAT_ID,
            "user-1",
            "木棍塔測試",
            1790000000,
            1790000500,
            json.dumps({"history": {"messages": messages}}, ensure_ascii=False),
            "{}",
        ),
    )
    for message_id, message in messages.items():
        db.execute(
            "INSERT INTO chat_message VALUES (?,?,?,?,?,?,?,?)",
            (
                message_id,
                CHAT_ID,
                "user-1",
                message["role"],
                message["parentId"],
                message["content"],
                json.dumps(message.get("files") or []),
                1790000000,
            ),
        )
    db.commit()
    db.close()
    return path


def test_sqlite_source_reads_chat_and_inline_image(tmp_path: Path):
    db_path = build_database(tmp_path / "webui.db", uploads_dir=tmp_path / "uploads")
    source = SqliteFileSource(
        LocalSourceConfig(kind="sqlite", local_db_path=str(db_path), uploads_root=str(tmp_path / "uploads"))
    )

    payload = source.fetch_chat(CHAT_ID)

    assert payload["title"] == "木棍塔測試"
    assert payload["message_count"] == 4
    assert len(payload["_files"]) == 1
    assert payload["_files"][0]["data_url"].startswith("data:image/png;base64,")
    decoded = base64.b64decode(payload["_files"][0]["data_url"].split(",", 1)[1])
    assert decoded == PNG_BYTES
    # inline payloads are stripped from the message tree before transfer
    root = payload["chat"]["history"]["messages"][ROOT]
    assert root["files"][0]["file"]["data"] == {}


def test_sqlite_source_missing_image_payload_is_reported(tmp_path: Path):
    db_path = build_database(tmp_path / "webui.db", uploads_dir=None)
    source = SqliteFileSource(LocalSourceConfig(kind="sqlite", local_db_path=str(db_path)))

    payload = source.fetch_chat(CHAT_ID)

    assert payload["_files"][0]["skipped"] == "payload not found"


def test_normalize_local_chat_attaches_images_and_branches(tmp_path: Path):
    db_path = build_database(tmp_path / "webui.db", uploads_dir=tmp_path / "uploads")
    source = SqliteFileSource(
        LocalSourceConfig(kind="sqlite", local_db_path=str(db_path), uploads_root=str(tmp_path / "uploads"))
    )

    conversation = normalize_local_chat(source.fetch_chat(CHAT_ID))

    assert conversation.source_provider == "openwebui"
    assert conversation.source_chat_id == CHAT_ID
    assert conversation.message_count == 4
    assert conversation.branch_count == 1
    assert conversation.models == ["deepseek-test"]
    attachments = conversation.messages[ROOT].attachments
    assert len(attachments) == 1
    assert attachments[0].caption == "IMG_1.png"
    assert attachments[0].url.startswith("data:image/png;base64,")


def test_list_chats_returns_summaries(tmp_path: Path):
    db_path = build_database(tmp_path / "webui.db")
    source = SqliteFileSource(LocalSourceConfig(kind="sqlite", local_db_path=str(db_path)))

    rows = source.list_chats(limit=5)

    assert [row["id"] for row in rows] == [CHAT_ID]
    assert rows[0]["title"] == "木棍塔測試"


def test_missing_database_is_a_clear_error(tmp_path: Path):
    with pytest.raises(LocalSourceError):
        SqliteFileSource(LocalSourceConfig(kind="sqlite", local_db_path=str(tmp_path / "nope.db")))


def test_unknown_chat_raises(tmp_path: Path):
    db_path = build_database(tmp_path / "webui.db")
    source = SqliteFileSource(LocalSourceConfig(kind="sqlite", local_db_path=str(db_path)))

    with pytest.raises(LocalSourceError):
        source.fetch_chat("does-not-exist")


def test_parse_result_reads_marker_line_and_reports_errors():
    ok = parse_result('warning: something\nCHATBLOG_JSON:{"ok": true, "title": "x"}')
    assert ok["title"] == "x"

    with pytest.raises(LocalSourceError):
        parse_result('CHATBLOG_JSON:{"ok": false, "error": "boom"}')

    with pytest.raises(LocalSourceError):
        parse_result("no marker here")


def test_build_program_embeds_request_without_quoting_issues():
    program = build_program({"operation": "get", "chat_id": "id-'quoted'-x"}).decode()

    assert "REQUEST = json.loads(" in program
    assert program.rstrip().endswith("main(REQUEST)")


def test_attach_local_images_ignores_unrelated_files(tmp_path: Path):
    payload = {
        "chat": {"history": {"messages": {ROOT: {"files": [{"id": "missing-file"}]}}}},
        "_files": [{"id": "other-file", "filename": "x.png", "data_url": "data:image/png;base64,AAAA"}],
    }
    conversation = normalize_local_chat(
        {
            "id": CHAT_ID,
            "title": "t",
            "chat": {"history": {"messages": {ROOT: {"id": ROOT, "role": "user", "content": "hi", "childrenIds": []}}}},
            "created_at": 1790000000,
            "updated_at": 1790000000,
        }
    )

    attach_local_images(conversation, payload)

    assert conversation.messages[ROOT].attachments == []
