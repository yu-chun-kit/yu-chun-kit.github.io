"""The local studio: a small HTTP server + single-page GUI.

``chatblog gui`` starts this on 127.0.0.1 and opens a browser.  The server owns
three things:

* a merged catalogue of OpenWebUI and Gemini conversations (``.chatblog/catalog.json``),
* the published-post ledger (``.chatblog/index.json``),
* background jobs (refresh / classify / publish) with progress polling.

Everything binds to localhost and every ``/api`` call needs the per-session
token that :func:`bootstrap` hands to the page, so another tab (or a random web
page) cannot drive the tool.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

from .catalog import ChatEntry, entries_from_gemini, entries_from_openwebui
from .config import Settings, load_settings, save_studio_settings
from .ledger import Ledger
from .publish import PublishOptions, publish_entry
from .systemone import GeminiDecisionClient, SystemOneClient, SystemOneError
from .taxonomy import Taxonomy, load_taxonomy

STATIC_DIR = Path(__file__).with_name("static")
DEFAULT_PORT = 8765


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _firefox_executable() -> str | None:
    override = os.environ.get("CHATBLOG_FIREFOX")
    if override and Path(override).is_file():
        return override
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Mozilla Firefox/firefox.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Mozilla Firefox/firefox.exe",
        Path("/usr/bin/firefox"),
    ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def _spawn(executable: str, url: str) -> None:
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [executable, url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )


def open_external(url: str, preference: str = "auto") -> str:
    """Open ``url`` in the browser that can actually reach it.

    Chrome is in TunnlTo's tunnel, so it cannot reach the LAN OpenWebUI; Firefox
    is not tunnelled.  Gemini needs the tunnel.  ``auto`` therefore routes by
    host, which is exactly the split the user hit by hand.
    """
    if not re.match(r"^https?://", url or ""):
        raise ValueError("只允許 http/https 連結")
    host = urlsplit(url).hostname or ""
    lan = host.startswith("192.168.") or host.endswith(".lan") or host in ("localhost", "127.0.0.1")

    choice = (preference or "auto").lower()
    if choice == "auto":
        choice = "firefox" if lan else "chrome"

    if choice == "firefox":
        executable = _firefox_executable()
        if executable:
            _spawn(executable, url)
            return "firefox"
    elif choice == "chrome":
        try:
            from .gemini_web import chrome_executable

            _spawn(chrome_executable(), url)
            return "chrome"
        except Exception:  # noqa: BLE001 - fall back to the default browser
            pass

    webbrowser.open(url)
    return "system"


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@dataclass
class Job:
    kind: str
    keys: list[str]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "running"  # running | done | error | cancelled
    total: int = 0
    done: int = 0
    message: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = field(default_factory=_now)
    finished_at: str = ""
    cancelled: bool = False
    token_usage: int = 0

    def __post_init__(self) -> None:
        self.total = len(self.keys)

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "message": self.message,
            "items": list(self.items),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "token_usage": self.token_usage,
        }


class JobManager:
    """Runs one job at a time (browser work must not interleave)."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.order: list[str] = []
        self._lock = threading.Lock()

    def start(
        self,
        kind: str,
        keys: list[str],
        worker: Callable[[str, Job], dict[str, Any]],
        **attrs: Any,
    ) -> Job:
        job = Job(kind=kind, keys=list(keys))
        for name, value in attrs.items():
            setattr(job, name, value)
        with self._lock:
            self.jobs[job.id] = job
            self.order.append(job.id)
            while len(self.order) > 25:
                dropped = self.order.pop(0)
                self.jobs.pop(dropped, None)

        thread = threading.Thread(target=self._run, args=(job, worker), daemon=True, name=f"job-{job.id}")
        thread.start()
        return job

    def _run(self, job: Job, worker: Callable[[str, Job], dict[str, Any]]) -> None:
        try:
            for key in job.keys:
                if job.cancelled:
                    job.status = "cancelled"
                    break
                try:
                    result = worker(key, job)
                except Exception as exc:  # noqa: BLE001 - keep the batch alive
                    result = {"key": key, "ok": False, "error": str(exc)}
                job.items.append(result)
                job.done += 1
            else:
                job.status = "done"
        except Exception as exc:  # noqa: BLE001
            job.status = "error"
            job.message = str(exc)
        finally:
            job.finished_at = _now()
            callback = getattr(job, "on_finish", None)
            if callable(callback):
                try:
                    callback()
                except Exception:  # noqa: BLE001 - cleanup must not mask the result
                    pass

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self) -> list[Job]:
        return [self.jobs[job_id] for job_id in reversed(self.order) if job_id in self.jobs]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class StudioService:
    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.port = port
        self.token = secrets.token_urlsafe(18)
        self.jobs = JobManager()
        self.lock = threading.RLock()
        self._settings = load_settings()
        self._taxonomy = load_taxonomy(self._settings.taxonomy_path or None)
        self.data_dir = self._settings.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_data_ignored()

        self.ledger = Ledger(self.data_dir / "index.json").load(
            self._settings.posts_dir, repo_root=self._settings.repo_root
        )
        self.entries: dict[str, ChatEntry] = {}
        self.catalog_updated_at = ""
        self.source_state: dict[str, dict[str, Any]] = {
            "openwebui": {"ok": True, "detail": "未載入", "count": 0, "at": ""},
            "gemini": {"ok": True, "detail": "未載入", "count": 0, "at": ""},
        }
        self._load_catalog()

    # -- state -----------------------------------------------------------
    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def taxonomy(self) -> Taxonomy:
        return self._taxonomy

    def reload_settings(self) -> None:
        with self.lock:
            self._settings = load_settings()
            self._taxonomy = load_taxonomy(self._settings.taxonomy_path or None)

    def _ensure_data_ignored(self) -> None:
        try:
            from .publish import ensure_gitignored

            ensure_gitignored(self._settings.repo_root, [".chatblog/"])
        except Exception:  # noqa: BLE001 - never block startup on .gitignore
            pass

    def _catalog_path(self) -> Path:
        return self.data_dir / "catalog.json"

    def _load_catalog(self) -> None:
        path = self._catalog_path()
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for item in (raw.get("entries") or {}).values():
            if isinstance(item, dict):
                entry = ChatEntry.from_dict(item)
                if entry.key:
                    self.entries[entry.key] = entry
        self.catalog_updated_at = str(raw.get("updated_at") or "")
        sources = raw.get("sources") or {}
        for name, state in sources.items():
            if name in self.source_state and isinstance(state, dict):
                self.source_state[name].update(state)

    def _save_catalog(self) -> None:
        updated_at = _now()
        payload = {
            "version": 1,
            "updated_at": updated_at,
            "sources": self.source_state,
            "entries": {key: entry.to_dict() for key, entry in self.entries.items()},
        }
        tmp = self._catalog_path().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self._catalog_path())
        self.catalog_updated_at = updated_at

    def systemone_client(self) -> SystemOneClient:
        settings = self._settings
        if settings.classifier_provider == "gemini":
            return GeminiDecisionClient(
                base_url=settings.decision_base_url,
                api_key=settings.gemini_api_key,
                model=settings.decision_model,
            )
        if settings.classifier_provider != "openjev":
            raise SystemOneError(f"未知的分類來源：{settings.classifier_provider}")
        return SystemOneClient(
            base_url=settings.openjev_base_url,
            api_key=settings.openjev_api_key,
            model=settings.openjev_model,
        )

    # -- catalogue -------------------------------------------------------
    def decorated(self) -> list[dict[str, Any]]:
        with self.lock:
            records = {key: record for key, record in self.ledger.records.items()}
            rows = []
            for entry in self.entries.values():
                record = records.get(entry.key)
                if record:
                    status = "stale" if record.stale(entry.title, _iso(entry.updated_at)) else "published"
                else:
                    status = "new"
                extra = {
                    "status": status,
                    "post_path": record.post_path if record else "",
                    "published_at": record.published_at if record else "",
                    "private": record.private if record else False,
                }
                rows.append(entry.to_dict(**extra))
            rows.sort(key=lambda row: (row["updated_at"] or row["created_at"] or "", row["title"]), reverse=True)
            return rows

    def refresh(self, providers: list[str]) -> dict[str, Any]:
        errors: dict[str, str] = {}
        with self.lock:
            previous = dict(self.entries)

        if "openwebui" in providers:
            try:
                rows, via = self._list_openwebui()
                fresh = entries_from_openwebui(rows, self._settings.owui_web_base)
                with self.lock:
                    for entry in fresh:
                        old = previous.get(entry.key)
                        if old is None:
                            continue
                        entry.tags = old.tags
                        entry.classification = old.classification
                        entry.models = entry.models or old.models
                        entry.message_count = entry.message_count or old.message_count
                    self.entries = {
                        key: value for key, value in self.entries.items() if value.provider != "openwebui"
                    }
                    self.entries.update({entry.key: entry for entry in fresh})
                    self.source_state["openwebui"] = {
                        "ok": True,
                        "detail": via,
                        "count": len(fresh),
                        "at": _now(),
                    }
            except Exception as exc:  # noqa: BLE001
                errors["openwebui"] = str(exc)
                with self.lock:
                    self.source_state["openwebui"] = {
                        "ok": False,
                        "detail": str(exc)[:300],
                        "count": self.source_state["openwebui"].get("count", 0),
                        "at": _now(),
                    }

        if "gemini" in providers:
            try:
                items = self._list_gemini()
                fresh = entries_from_gemini(items)
                with self.lock:
                    for entry in fresh:
                        old = previous.get(entry.key)
                        if old is None:
                            continue
                        entry.tags = old.tags
                        entry.classification = old.classification
                        entry.models = entry.models or old.models
                        entry.message_count = entry.message_count or old.message_count
                    self.entries = {
                        key: value for key, value in self.entries.items() if value.provider != "gemini"
                    }
                    self.entries.update({entry.key: entry for entry in fresh})
                    self.source_state["gemini"] = {
                        "ok": True,
                        "detail": "browser",
                        "count": len(fresh),
                        "at": _now(),
                    }
            except Exception as exc:  # noqa: BLE001
                errors["gemini"] = str(exc)
                with self.lock:
                    self.source_state["gemini"] = {
                        "ok": False,
                        "detail": str(exc)[:300],
                        "count": self.source_state["gemini"].get("count", 0),
                        "at": _now(),
                    }

        with self.lock:
            self.catalog_updated_at = _now()
            self._save_catalog()
        return errors

    def _list_openwebui(self) -> tuple[list[dict[str, Any]], str]:
        from .cli import build_client, local_source_config
        from .owui_local import build_local_source

        settings = self._settings
        try:
            client = build_client(settings)
            chats = client.list_chats(limit=500)
            rows = [
                {
                    "id": chat.id,
                    "title": chat.title,
                    "created_at": chat.created_at,
                    "updated_at": chat.updated_at,
                }
                for chat in chats
            ]
            return rows, "api"
        except Exception:  # noqa: BLE001 - fall back to the NAS database
            reader = build_local_source(local_source_config(settings, "ssh"))
            return list(reader.list_chats(limit=500)), "ssh"

    def _list_gemini(self) -> list[Any]:
        from . import gemini_web

        profile = self._gemini_profile()
        with gemini_web.browser_page(
            profile,
            self._settings.gemini_port,
            headless=self._settings.gemini_headless,
            url=gemini_web.GEMINI_APP,
        ) as page:
            gemini_web._goto_app(page)
            return gemini_web.list_conversations(page)

    def _gemini_profile(self) -> Path:
        from . import gemini_web

        return Path(self._settings.gemini_profile) if self._settings.gemini_profile else gemini_web.default_profile_dir()

    #: One CDP connection reused across the items of a single job; opening a
    #: new Playwright driver per chat costs ~1s and a full page load anyway.
    _gemini_cm: Any = None
    _gemini_page: Any = None

    def gemini_page(self):
        from . import gemini_web

        if self._gemini_page is None:
            self._gemini_cm = gemini_web.browser_page(
                self._gemini_profile(),
                self._settings.gemini_port,
                headless=self._settings.gemini_headless,
                url=gemini_web.GEMINI_APP,
            )
            self._gemini_page = self._gemini_cm.__enter__()
        return self._gemini_page

    def close_gemini_page(self) -> None:
        if self._gemini_cm is not None:
            try:
                self._gemini_cm.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        self._gemini_cm = None
        self._gemini_page = None

    # -- per-item workers ------------------------------------------------
    def classify_key(self, key: str, job: Job) -> dict[str, Any]:
        from .classify import classify_conversation
        from . import gemini_web

        entry = self.entries.get(key)
        if entry is None:
            return {"key": key, "ok": False, "error": "找不到這個對話"}

        client = self.systemone_client()
        if entry.provider == "openwebui":
            from .cli import fetch_conversation

            conversation = fetch_conversation(entry.chat_id, source="auto", settings=self._settings)
        else:
            conversation = gemini_web.fetch_conversation(
                self.gemini_page(),
                entry.chat_id,
                approx_date=entry.updated_at,
                debug_dir=self.data_dir / "debug",
            )

        classification = classify_conversation(conversation, self._taxonomy, client)
        job.token_usage += classification.input_tokens
        with self.lock:
            entry.set_tags(
                classification.tags,
                classification.provider,
                classification.model,
                classification.error,
                complete=classification.complete,
                input_tokens=classification.input_tokens,
            )
            entry.models = conversation.models
            entry.message_count = conversation.message_count
            self._save_catalog()
        return {
            "key": key,
            "ok": classification.complete,
            "title": entry.title,
            "tags": [tag.name for tag in classification.tags],
            "provider": classification.provider,
            "error": classification.error,
            "needs_classification": entry.needs_classification,
        }

    def publish_key(self, key: str, job: Job) -> dict[str, Any]:
        entry = self.entries.get(key)
        if entry is None:
            return {"key": key, "ok": False, "error": "找不到這個對話"}
        options: PublishOptions = getattr(job, "options", PublishOptions())
        page = self.gemini_page() if entry.provider == "gemini" else None
        result, record = publish_entry(entry, self._taxonomy, options, gemini_page=page)
        if record:
            with self.lock:
                self.ledger.upsert(record)
                self.ledger.save()
        return result.to_dict()

    # -- misc ------------------------------------------------------------
    def sources_payload(self) -> dict[str, Any]:
        from . import gemini_web

        profile = self._gemini_profile()
        gemini = gemini_web.profile_status(profile, self._settings.gemini_port)
        gemini["state"] = self.source_state.get("gemini", {})
        owui = dict(self.source_state.get("openwebui", {}))
        owui["web_base"] = self._settings.owui_web_base
        return {"openwebui": owui, "gemini": gemini}

    def settings_payload(self) -> dict[str, Any]:
        settings = self._settings
        key = settings.openjev_api_key
        return {
            "classifier_provider": settings.classifier_provider,
            "classifier_model": settings.decision_model if settings.classifier_provider == "gemini" else settings.openjev_model,
            "classifier_base_url": settings.decision_base_url if settings.classifier_provider == "gemini" else settings.openjev_base_url,
            "classifier_key_set": bool(settings.gemini_api_key if settings.classifier_provider == "gemini" else key),
            "openjev_base_url": settings.openjev_base_url,
            "openjev_model": settings.openjev_model,
            "openjev_key_set": bool(key),
            "openjev_key_hint": f"…{key[-4:]}" if len(key) >= 8 else "",
            "open_browser": settings.open_browser,
            "gemini_headless": settings.gemini_headless,
            "gemini_port": settings.gemini_port,
            "gemini_profile": str(self._gemini_profile()),
            "owui_base_url": settings.owui_web_base,
            "taxonomy_path": settings.taxonomy_path,
            "repo_root": str(settings.repo_root),
            "data_dir": str(self.data_dir),
            "ledger_path": str(self.ledger.path),
        }

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "openjev_base_url",
            "openjev_model",
            "openjev_api_key",
            "open_browser",
            "gemini_headless",
            "gemini_port",
            "gemini_profile",
            "owui_base_url",
            "taxonomy_path",
        }
        values: dict[str, Any] = {}
        for key, value in payload.items():
            if key not in allowed:
                continue
            if key == "openjev_api_key":
                if value in (None, ""):
                    continue
                values[key] = str(value).strip()
            elif key == "gemini_headless":
                values[key] = bool(value)
            elif key == "gemini_port":
                try:
                    port = int(value)
                except (TypeError, ValueError):
                    continue
                if 1024 <= port <= 65535:
                    values[key] = port
            else:
                values[key] = str(value).strip()
        save_studio_settings(values, self._settings.repo_root)
        self.reload_settings()
        return self.settings_payload()


def _iso(moment: datetime | None) -> str:
    return moment.isoformat(timespec="seconds") if moment else ""


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "ChatblogStudio/1.0"
    protocol_version = "HTTP/1.1"

    service: StudioService  # injected below

    # -- utilities -------------------------------------------------------
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > 2_000_000:
            raise ValueError("request too large")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("invalid JSON body") from exc
        return payload if isinstance(payload, dict) else {}

    def _authorised(self) -> bool:
        token = self.headers.get("X-Studio-Token") or ""
        if not token:
            query = urlsplit(self.path).query
            match = re.search(r"(?:^|&)token=([^&]+)", query)
            if match:
                token = unquote(match.group(1))
        try:
            return secrets.compare_digest(token.encode("utf-8"), self.service.token.encode("utf-8"))
        except (UnicodeEncodeError, TypeError):
            return False

    def _static(self, name: str) -> None:
        path = (STATIC_DIR / name).resolve()
        if STATIC_DIR.resolve() not in path.parents:
            self._error(404, "not found")
            return
        if not path.is_file():
            self._error(404, "not found")
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".json": "application/json; charset=utf-8",
        }.get(path.suffix, "application/octet-stream")
        self._send(200, path.read_bytes(), content_type)

    # -- routing ---------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self._static("index.html")
            return
        if path in ("/app.js", "/app.css", "/favicon.svg"):
            self._static(path.lstrip("/"))
            return
        if not path.startswith("/api/"):
            self._error(404, "not found")
            return
        if path != "/api/bootstrap" and not self._authorised():
            self._error(401, "unauthorised")
            return
        try:
            self._route_get(path)
        except Exception as exc:  # noqa: BLE001
            self._error(500, str(exc))

    def do_POST(self) -> None:  # noqa: N802 - stdlib
        path = urlsplit(self.path).path
        if not path.startswith("/api/") or not self._authorised():
            self._error(401, "unauthorised")
            return
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._error(400, str(exc))
            return
        try:
            self._route_post(path, payload)
        except SystemOneError as exc:
            self._error(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._error(500, str(exc))

    def _route_get(self, path: str) -> None:
        service = self.service
        if path == "/api/bootstrap":
            self._json(
                200,
                {
                    "token": service.token,
                    "settings": service.settings_payload(),
                    "sources": service.sources_payload(),
                    "counts": {"chats": len(service.entries), "published": len(service.ledger.records)},
                    "catalog_updated_at": service.catalog_updated_at,
                },
            )
        elif path == "/api/chats":
            self._json(
                200,
                {
                    "entries": service.decorated(),
                    "updated_at": service.catalog_updated_at,
                    "sources": service.sources_payload(),
                },
            )
        elif path == "/api/jobs":
            self._json(200, {"jobs": [job.snapshot() for job in service.jobs.list()]})
        elif path.startswith("/api/jobs/"):
            job = service.jobs.get(path.rsplit("/", 1)[-1])
            if job is None:
                self._error(404, "job not found")
            else:
                self._json(200, job.snapshot())
        elif path == "/api/settings":
            self._json(200, service.settings_payload())
        elif path == "/api/gemini/status":
            self._json(200, service.sources_payload()["gemini"])
        else:
            self._error(404, "not found")

    def _route_post(self, path: str, payload: dict[str, Any]) -> None:
        service = self.service

        if path == "/api/refresh":
            providers = payload.get("providers") or ["openwebui", "gemini"]
            providers = [name for name in providers if name in ("openwebui", "gemini")] or [
                "openwebui",
                "gemini",
            ]

            def worker(key: str, job: Job) -> dict[str, Any]:
                job.message = f"讀取 {key} 對話列表中…"
                errors = service.refresh([key])
                return {"key": key, "ok": not errors, "error": errors.get(key, "")}

            job = service.jobs.start("refresh", providers, worker)
            self._json(200, job.snapshot())
            return

        if path == "/api/classify":
            keys = [str(key) for key in payload.get("keys") or []]
            if payload.get("all"):
                keys = [key for key, entry in service.entries.items() if entry.needs_classification]
            if not keys:
                self._error(400, "沒有選擇對話")
                return
            job = service.jobs.start(
                "classify", keys, service.classify_key, on_finish=service.close_gemini_page
            )
            self._json(200, job.snapshot())
            return

        if path == "/api/publish":
            keys = [str(key) for key in payload.get("keys") or []]
            if not keys:
                self._error(400, "沒有選擇對話")
                return
            options = PublishOptions(
                private=bool(payload.get("private")),
                force_assets=bool(payload.get("force_assets")),
                date=str(payload.get("date") or ""),
            )
            job = service.jobs.start(
                "publish", keys, service.publish_key, options=options, on_finish=service.close_gemini_page
            )
            self._json(200, job.snapshot())
            return

        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            job = service.jobs.get(path.split("/")[3])
            if job is None:
                self._error(404, "job not found")
            else:
                job.cancelled = True
                self._json(200, job.snapshot())
            return

        if path == "/api/open":
            url = str(payload.get("url") or "")
            opened = open_external(url, str(payload.get("browser") or service.settings.open_browser))
            self._json(200, {"ok": True, "browser": opened})
            return

        if path == "/api/settings":
            self._json(200, {"ok": True, "settings": service.update_settings(payload)})
            return

        if path == "/api/openjev/test":
            client = service.systemone_client()
            try:
                info = client.health()
            except SystemOneError as exc:
                self._json(200, {"ok": False, "error": str(exc)})
                return
            self._json(200, {"ok": True, "info": info})
            return

        if path == "/api/gemini/login":
            from . import gemini_web

            gemini_web.open_for_login(service._gemini_profile(), service.settings.gemini_port)
            self._json(200, {"ok": True, "message": "已開啟 Chrome，請登入 Google 後關閉該視窗。"})
            return

        if path == "/api/gemini/check":
            from . import gemini_web

            profile = service._gemini_profile()
            try:
                with gemini_web.browser_page(
                    profile,
                    service.settings.gemini_port,
                    headless=service.settings.gemini_headless,
                    url=gemini_web.GEMINI_APP,
                ) as page:
                    gemini_web._goto_app(page)
                    items = gemini_web.list_conversations(page, max_rounds=2, pause_ms=300)
                self._json(200, {"ok": True, "logged_in": True, "count": len(items)})
            except gemini_web.GeminiNotLoggedIn:
                self._json(200, {"ok": True, "logged_in": False})
            except Exception as exc:  # noqa: BLE001
                self._json(200, {"ok": False, "logged_in": False, "error": str(exc)})
            return

        if path == "/api/reveal":
            target = Path(str(payload.get("path") or ""))
            if not str(target):
                self._error(400, "沒有路徑")
                return
            try:
                if os.name == "nt":
                    subprocess.Popen(["explorer", "/select,", str(target)])
                else:
                    webbrowser.open(str(target if target.is_dir() else target.parent))
            except Exception as exc:  # noqa: BLE001
                self._error(500, str(exc))
                return
            self._json(200, {"ok": True})
            return

        self._error(404, "not found")


def serve(port: int = DEFAULT_PORT, host: str = "127.0.0.1", open_browser: bool = True) -> None:
    service = StudioService(port=port)
    handler = type("BoundStudioHandler", (StudioHandler,), {"service": service})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    url = f"http://{host}:{port}/"
    print(f"Chatblog Studio: {url}")
    print(f"  索引：{service.ledger.path}")
    print(f"  目錄快取：{service.data_dir / 'catalog.json'}")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n再見。")
    finally:
        httpd.server_close()
