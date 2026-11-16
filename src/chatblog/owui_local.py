"""Read OpenWebUI conversations **without an API token**.

OpenWebUI's own API needs a valid token (session JWTs expire after ~28 days).
When that is not available we can read the very same data straight from its
SQLite database - either

* ``SshContainerSource``: SSH into the NAS and query the live database inside
  the ``open-webui`` container (read-only, no files written on the NAS), or
* ``SqliteFileSource``: read a local / SMB-mounted copy of ``webui.db`` (or the
  cache produced by the ``openwebui-local-reader`` tool).

Both return a payload shaped like ``GET /api/v1/chats/{id}`` so the existing
:mod:`chatblog.normalize` code can consume it unchanged.  Images attached to a
conversation are read from the container's ``uploads`` directory and handed over
as ``data:`` URLs, which :mod:`chatblog.assets` already knows how to store.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .models import Conversation, ImageAttachment
from .normalize import normalize_openwebui_chat


#: Marker so stray output from docker/ssh cannot break JSON parsing.
RESULT_PREFIX = "CHATBLOG_JSON:"

DEFAULT_SSH_HOST = "johnsons_nas"
DEFAULT_CONTAINER = "open-webui"
DEFAULT_DB_PATH = "/app/backend/data/webui.db"
DEFAULT_DOCKER = "/usr/local/bin/docker"
DEFAULT_CONTAINER_PYTHON = "python"
DEFAULT_SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=8")

#: Images above this size are skipped instead of being streamed over SSH.
MAX_FILE_BYTES = 8 * 1024 * 1024


class LocalSourceError(RuntimeError):
    """Raised when the local OpenWebUI database cannot be read."""


_REMOTE_PROGRAM = r'''
import base64
import json
import os
import sqlite3
import sys

RESULT_PREFIX = "CHATBLOG_JSON:"
MAX_FILE_BYTES = __MAX_FILE_BYTES__


def ident(value):
    return '"' + str(value).replace('"', '""') + '"'


def open_db(path):
    uri = str(path)
    if not uri.startswith('file:'):
        uri = 'file:' + uri
    uri += '&mode=ro' if '?' in uri else '?mode=ro'
    db = sqlite3.connect(uri, uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA busy_timeout=5000')
    return db


def row_dict(row):
    return {key: row[key] for key in row.keys()}


def table_names(db):
    return {
        str(row[0])
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def columns(db, table):
    return {str(row[1]) for row in db.execute('PRAGMA table_info(' + ident(table) + ')')}


def decode_json(value):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        value = value.decode('utf-8', 'replace')
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            return None
    return value


def load_chat_blob(row):
    blob = decode_json(row.get('chat'))
    if isinstance(blob, dict):
        return blob
    return {}


def message_map(chat_blob):
    history = chat_blob.get('history') or {}
    messages = history.get('messages') or {}
    return messages if isinstance(messages, dict) else {}


def collect_file_ids(chat_blob):
    ids = []
    for message in message_map(chat_blob).values():
        if not isinstance(message, dict):
            continue
        for entry in message.get('files') or []:
            if not isinstance(entry, dict):
                continue
            nested = entry.get('file') if isinstance(entry.get('file'), dict) else {}
            file_id = entry.get('id') or nested.get('id')
            if file_id and str(file_id) not in ids:
                ids.append(str(file_id))
    return ids


def file_payload(row, meta, uploads_root=''):
    content_type = str(
        meta.get('content_type') or meta.get('type') or ''
    ).split(';')[0].strip().lower()
    if not content_type.startswith('image/'):
        return None

    raw = None
    candidates = []
    path = row.get('path')
    if path:
        candidates.append(str(path))
        if uploads_root:
            candidates.append(os.path.join(str(uploads_root), os.path.basename(str(path))))
    for candidate in candidates:
        if not os.path.isfile(candidate):
            continue
        size = os.path.getsize(candidate)
        if size > MAX_FILE_BYTES:
            return {'id': row.get('id'), 'filename': row.get('filename'),
                    'content_type': content_type, 'skipped': 'too large (%d bytes)' % size}
        with open(candidate, 'rb') as handle:
            raw = handle.read()
        break

    if raw is None:
        stored = decode_json(row.get('data'))
        if isinstance(stored, dict):
            content = stored.get('content')
            if isinstance(content, str) and content.startswith('data:') and ';base64,' in content:
                head, _, body = content.partition(';base64,')
                try:
                    raw = base64.b64decode(body)
                except Exception:
                    raw = None
                if head.startswith('data:image/') and raw is not None:
                    content_type = head[len('data:'):] or content_type

    if raw is None:
        return {'id': row.get('id'), 'filename': row.get('filename'),
                'content_type': content_type, 'skipped': 'payload not found'}

    return {
        'id': row.get('id'),
        'filename': row.get('filename') or '',
        'content_type': content_type,
        'size': len(raw),
        'data_url': 'data:' + content_type + ';base64,' + base64.b64encode(raw).decode('ascii'),
    }


def fetch_files(db, tables, request, chat_blob):
    if 'file' not in tables:
        return []
    ids = collect_file_ids(chat_blob)
    if not ids:
        return []
    available = columns(db, 'file')
    keep = [name for name in ('id', 'filename', 'path', 'meta', 'data', 'user_id') if name in available]
    if 'id' not in keep:
        return []
    files = []
    for file_id in ids:
        row = db.execute(
            'SELECT ' + ', '.join(ident(name) for name in keep) + ' FROM file WHERE id = ?',
            (file_id,),
        ).fetchone()
        if row is None:
            continue
        record = row_dict(row)
        meta = decode_json(record.get('meta')) or {}
        if not isinstance(meta, dict):
            meta = {}
        payload = file_payload(record, meta, str(request.get('uploads_root') or ''))
        if payload:
            files.append(payload)
    return files


def drop_blob_payloads(chat_blob):
    """Remove inline base64 from the message tree; it would bloat the transfer."""
    for message in message_map(chat_blob).values():
        if not isinstance(message, dict):
            continue
        for entry in message.get('files') or []:
            if isinstance(entry, dict) and isinstance(entry.get('file'), dict):
                inner = entry['file']
                if isinstance(inner.get('data'), dict):
                    inner['data'] = {}
    return chat_blob


def get_chat(db, request):
    tables = table_names(db)
    chat_id = str(request['chat_id'])
    available = columns(db, 'chat')
    keep = [name for name in (
        'id', 'user_id', 'title', 'share_id', 'archived', 'created_at', 'updated_at',
        'chat', 'meta', 'folder_id', 'summary', 'current_message_id',
    ) if name in available]
    row = db.execute(
        'SELECT ' + ', '.join(ident(name) for name in keep) + ' FROM chat WHERE id = ? LIMIT 1',
        (chat_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError('chat %s not found' % chat_id)

    record = row_dict(row)
    chat_blob = load_chat_blob(record)
    message_count = len(message_map(chat_blob))
    if message_count == 0 and 'chat_message' in tables:
        # Fall back to the normalised table when the blob has no history.
        cols = columns(db, 'chat_message')
        names = [name for name in (
            'id', 'role', 'parent_id', 'content', 'children_ids', 'childrenIds',
            'timestamp', 'model_id', 'model', 'files', 'sources', 'created_at', 'updated_at',
        ) if name in cols]
        rows = db.execute(
            'SELECT ' + ', '.join(ident(name) for name in names)
            + ' FROM chat_message WHERE chat_id = ? ORDER BY created_at, rowid',
            (chat_id,),
        ).fetchall()
        converted = {}
        for item in rows:
            data = row_dict(item)
            content = decode_json(data.get('content'))
            if isinstance(content, (dict, list)):
                content = json.dumps(content, ensure_ascii=False)
            converted[str(data.get('id'))] = {
                'id': data.get('id'),
                'role': data.get('role'),
                'content': content if isinstance(content, str) else '',
                'parentId': data.get('parent_id'),
                'childrenIds': decode_json(data.get('childrenIds') or data.get('children_ids')) or [],
                'timestamp': data.get('created_at') or data.get('timestamp'),
                'modelName': data.get('model') or data.get('model_id'),
            }
        chat_blob = {'history': {'messages': converted}}
        message_count = len(converted)

    files = fetch_files(db, tables, request, chat_blob)
    payload = {
        'id': record.get('id') or chat_id,
        'title': record.get('title'),
        'created_at': record.get('created_at'),
        'updated_at': record.get('updated_at'),
        'chat': drop_blob_payloads(chat_blob),
        'meta': decode_json(record.get('meta')) or {},
        'message_count': message_count,
        '_files': files,
        '_source': 'sqlite',
    }
    return payload


def list_chats(db, request):
    available = columns(db, 'chat')
    keep = [name for name in ('id', 'title', 'created_at', 'updated_at') if name in available]
    order = 'updated_at' if 'updated_at' in available else 'id'
    limit = max(1, min(int(request.get('limit') or 20), 500))
    rows = db.execute(
        'SELECT ' + ', '.join(ident(name) for name in keep) + ' FROM chat ORDER BY '
        + ident(order) + ' DESC LIMIT ?',
        (limit,),
    ).fetchall()
    return {'rows': [row_dict(row) for row in rows]}


def main(request):
    db = open_db(request.get('db_path') or '/app/backend/data/webui.db')
    operation = request.get('operation') or 'get'
    if operation == 'get':
        result = get_chat(db, request)
    elif operation == 'list':
        result = list_chats(db, request)
    else:
        raise RuntimeError('unsupported operation: %s' % operation)
    print(RESULT_PREFIX + json.dumps({'ok': True, **result}, ensure_ascii=False, default=str))


main(REQUEST)
'''.replace("__MAX_FILE_BYTES__", str(MAX_FILE_BYTES))


def build_program(request: dict[str, Any]) -> bytes:
    """Wrap :data:`_REMOTE_PROGRAM` with an embedded request literal."""
    request_json = json.dumps(request, ensure_ascii=True, separators=(",", ":"))
    script = f"{_REMOTE_PROGRAM}\n"
    script = script.replace(
        "\nmain(REQUEST)\n",
        f"\nREQUEST = json.loads({request_json!r})\nmain(REQUEST)\n",
    )
    return script.encode("utf-8")


def parse_result(stdout: str, stderr: str = "") -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith(RESULT_PREFIX):
            continue
        payload = json.loads(line[len(RESULT_PREFIX):])
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise LocalSourceError(str(payload.get("error") or "local OpenWebUI query failed"))
        return payload
    detail = (stderr or stdout or "").strip().splitlines()
    raise LocalSourceError(
        "local OpenWebUI query returned no result: " + (detail[-1] if detail else "no output")
    )


@dataclass
class LocalSourceConfig:
    """Where the OpenWebUI SQLite database lives."""

    kind: str = "ssh"  # "ssh" or "sqlite"
    host: str = DEFAULT_SSH_HOST
    container: str = DEFAULT_CONTAINER
    db_path: str = DEFAULT_DB_PATH
    docker: str = DEFAULT_DOCKER
    container_python: str = DEFAULT_CONTAINER_PYTHON
    port: int | None = None
    ssh_options: tuple[str, ...] = DEFAULT_SSH_OPTIONS
    timeout_seconds: int = 120
    local_db_path: str = ""
    #: Directory holding ``uploads`` on the machine that runs the query.  Only
    #: needed when the database is read from a file instead of the container.
    uploads_root: str = ""

    def describe(self) -> str:
        if self.kind == "sqlite":
            return f"sqlite:{self.local_db_path}"
        return f"ssh:{self.host}/{self.container}:{self.db_path}"


class LocalSource(Protocol):  # pragma: no cover - typing helper
    def fetch_chat(self, chat_id: str) -> dict[str, Any]: ...

    def list_chats(self, limit: int = 20) -> list[dict[str, Any]]: ...


class SshContainerSource:
    """Query the live database inside the OpenWebUI container over SSH."""

    def __init__(self, config: LocalSourceConfig | None = None) -> None:
        self.config = config or LocalSourceConfig()
        if not self.config.host:
            raise LocalSourceError("SSH host is not configured")
        self.source_label = self.config.describe()

    def _invoke(self, request: dict[str, Any]) -> dict[str, Any]:
        executable = shutil.which("ssh") or "ssh"
        command = [executable, *self.config.ssh_options]
        if self.config.port:
            command.extend(["-p", str(self.config.port)])
        command.extend(
            [
                self.config.host,
                self.config.docker,
                "exec",
                "-i",
                self.config.container,
                self.config.container_python,
                "-",
            ]
        )
        try:
            completed = subprocess.run(
                command,
                input=build_program(
                    {
                        "db_path": self.config.db_path,
                        "uploads_root": self.config.uploads_root,
                        **request,
                    }
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.config.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise LocalSourceError(
                "OpenSSH client not found; install it or use --source sqlite"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LocalSourceError(
                f"SSH query timed out after {self.config.timeout_seconds}s"
            ) from exc

        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")
        if completed.returncode != 0 and RESULT_PREFIX not in stdout:
            detail = stderr.strip().splitlines()
            raise LocalSourceError(
                f"SSH query failed (exit {completed.returncode}): "
                + (detail[-1] if detail else "no stderr")
            )
        return parse_result(stdout, stderr)

    def fetch_chat(self, chat_id: str) -> dict[str, Any]:
        return self._invoke({"operation": "get", "chat_id": chat_id})

    def list_chats(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self._invoke({"operation": "list", "limit": limit}).get("rows", []))


class SqliteFileSource:
    """Read a local or SMB-mounted OpenWebUI database (or local-reader cache)."""

    def __init__(self, config: LocalSourceConfig | None = None) -> None:
        self.config = config or LocalSourceConfig(kind="sqlite")
        if not self.config.local_db_path:
            raise LocalSourceError("sqlite source requires a database path")
        path = Path(self.config.local_db_path)
        if not path.is_file():
            raise LocalSourceError(f"database not found: {path}")
        self.source_label = self.config.describe()

    def _invoke(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                [sys.executable, "-"],
                input=build_program(
                    {
                        "db_path": self.config.local_db_path,
                        "uploads_root": self.config.uploads_root,
                        **request,
                    }
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.config.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - defensive
            raise LocalSourceError("local database query timed out") from exc

        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")
        if completed.returncode != 0 and RESULT_PREFIX not in stdout:
            detail = stderr.strip().splitlines()
            raise LocalSourceError(
                f"local database query failed: " + (detail[-1] if detail else "no stderr")
            )
        return parse_result(stdout, stderr)

    def fetch_chat(self, chat_id: str) -> dict[str, Any]:
        return self._invoke({"operation": "get", "chat_id": chat_id})

    def list_chats(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(self._invoke({"operation": "list", "limit": limit}).get("rows", []))


def build_local_source(config: LocalSourceConfig) -> LocalSource:
    if config.kind == "sqlite":
        return SqliteFileSource(config)
    return SshContainerSource(config)


def attach_local_images(conversation: Conversation, payload: dict[str, Any]) -> Conversation:
    """Attach the images that travelled with a local payload as ``data:`` URLs."""
    files = {str(item.get("id")): item for item in payload.get("_files", []) if item.get("data_url")}
    if not files:
        return conversation

    messages = ((payload.get("chat") or {}).get("history") or {}).get("messages") or {}
    for message_id, raw in messages.items():
        node = conversation.messages.get(str(message_id))
        if node is None or not isinstance(raw, dict):
            continue
        for entry in raw.get("files") or []:
            if not isinstance(entry, dict):
                continue
            nested = entry.get("file") if isinstance(entry.get("file"), dict) else {}
            file_id = str(entry.get("id") or nested.get("id") or "")
            item = files.get(file_id)
            if not item:
                continue
            name = str(item.get("filename") or nested.get("filename") or "")
            node.attachments.append(
                ImageAttachment(url=str(item["data_url"]), alt=name, caption=name)
            )
    return conversation


def normalize_local_chat(payload: dict[str, Any]) -> Conversation:
    """Turn a local-source payload into the shared :class:`Conversation` model."""
    conversation = normalize_openwebui_chat(payload)
    if not conversation.source_chat_id:
        conversation.source_chat_id = str(payload.get("id") or "")
    return attach_local_images(conversation, payload)


def fetch_local_chat(
    chat_id: str,
    config: LocalSourceConfig | None = None,
    source: LocalSource | None = None,
) -> Conversation:
    reader = source or build_local_source(config or LocalSourceConfig())
    return normalize_local_chat(reader.fetch_chat(chat_id))


__all__ = [
    "DEFAULT_CONTAINER",
    "DEFAULT_DB_PATH",
    "DEFAULT_SSH_HOST",
    "LocalSourceConfig",
    "LocalSourceError",
    "SshContainerSource",
    "SqliteFileSource",
    "attach_local_images",
    "build_local_source",
    "fetch_local_chat",
    "normalize_local_chat",
]
