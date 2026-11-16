from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

from .owui_local import DEFAULT_CONTAINER, DEFAULT_DB_PATH, DEFAULT_SSH_HOST


DEFAULT_API_BASE = "http://localhost:3000/api/v1"
DEFAULT_WEB_BASE = "http://192.168.128.111:3000"
DEFAULT_OPENJEV_BASE = "https://api.codiv.ai"
DEFAULT_OPENJEV_MODEL = "openjev-latest"
_ENV_REPO_ROOT = "CHATBLOG_REPO_ROOT"
_REPO_MARKERS = ("_config.yml", "package.json")
_STUDIO_SETTINGS = ("settings.json",)


def _looks_like_repo_root(path: Path) -> bool:
    return all((path / marker).is_file() for marker in _REPO_MARKERS)


def discover_repo_root(start: Path | None = None) -> Path:
    """Find the Hexo repository, independently of where chatblog is installed.

    ``CHATBLOG_REPO_ROOT`` wins, then we walk up from the working directory and
    from this file.  This keeps the CLI usable when it is not installed in
    editable mode (``src/chatblog`` inside site-packages has no repo around it).
    """
    override = os.environ.get(_ENV_REPO_ROOT)
    if override:
        return Path(override).expanduser().resolve()

    candidates: list[Path] = []
    for origin in (start, Path.cwd(), Path(__file__).resolve()):
        if origin is None:
            continue
        origin = Path(origin).resolve()
        candidates.append(origin)
        candidates.extend(origin.parents)

    for candidate in candidates:
        if _looks_like_repo_root(candidate):
            return candidate

    return Path(__file__).resolve().parents[2]


REPO_ROOT = discover_repo_root()


class Settings(BaseModel):
    api_base: str = DEFAULT_API_BASE
    api_token: str = ""
    repo_root: Path = REPO_ROOT
    posts_dir: Path = REPO_ROOT / "source" / "_posts"
    #: Fallback source when no usable API token exists (see chatblog.owui_local)
    owui_ssh_host: str = DEFAULT_SSH_HOST
    owui_ssh_container: str = DEFAULT_CONTAINER
    owui_db_path: str = DEFAULT_DB_PATH
    owui_local_db: str = ""
    owui_uploads_root: str = ""
    #: Web UI used for the "open in browser" links (no ``/api/v1`` suffix).
    owui_web_base: str = DEFAULT_WEB_BASE
    #: Local state (ledger, cache, settings, Gemini profile pointer).
    data_dir: Path = REPO_ROOT / ".chatblog"
    #: Gemini browser source (see chatblog.gemini_web).
    gemini_profile: str = ""
    gemini_port: int = 9333
    gemini_headless: bool = True
    #: Studio preferences.
    open_browser: str = "auto"
    openjev_base_url: str = DEFAULT_OPENJEV_BASE
    openjev_api_key: str = ""
    openjev_model: str = DEFAULT_OPENJEV_MODEL
    classifier_provider: str = "openjev"
    decision_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    decision_model: str = "gemini-decision-1"
    gemini_api_key: str = ""
    taxonomy_path: str = ""


def studio_settings_path(repo_root: Path | None = None) -> Path:
    root = repo_root or discover_repo_root()
    return root / ".chatblog" / "settings.json"


def load_studio_settings(repo_root: Path | None = None) -> dict:
    """Read the GUI's persisted preferences (never contains the API key by default)."""
    path = studio_settings_path(repo_root)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_studio_settings(values: dict, repo_root: Path | None = None) -> Path:
    root = repo_root or discover_repo_root()
    path = studio_settings_path(root)
    current = load_studio_settings(root)
    current.update({key: value for key, value in values.items() if value is not None})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return ""


def load_settings() -> Settings:
    """Load configuration from repo .env files, the studio settings and env."""
    repo_root = discover_repo_root()

    for env_file in (repo_root / ".env", repo_root / "scripts" / ".env"):
        load_dotenv(env_file)

    studio = load_studio_settings(repo_root)
    posts_env = os.environ.get("CHATBLOG_POSTS_DIR")
    api_base = os.environ.get("OPENWEBUI_API_BASE", DEFAULT_API_BASE).rstrip("/")
    web_base = str(studio.get("owui_base_url") or "").rstrip("/")
    if not web_base:
        web_base = api_base.removesuffix("/api/v1").rstrip("/") or DEFAULT_WEB_BASE
        if "localhost" in web_base or "127.0.0.1" in web_base:
            web_base = DEFAULT_WEB_BASE

    def studio_value(key: str, default):
        value = studio.get(key)
        return default if value in (None, "") else value

    return Settings(
        api_base=api_base,
        api_token=os.environ.get("OPENWEBUI_API_TOKEN", ""),
        repo_root=repo_root,
        posts_dir=Path(posts_env).expanduser() if posts_env else repo_root / "source" / "_posts",
        owui_ssh_host=os.environ.get("CHATBLOG_OWUI_SSH_HOST", DEFAULT_SSH_HOST),
        owui_ssh_container=os.environ.get("CHATBLOG_OWUI_CONTAINER", DEFAULT_CONTAINER),
        owui_db_path=os.environ.get("CHATBLOG_OWUI_DB_PATH", DEFAULT_DB_PATH),
        owui_local_db=os.environ.get("CHATBLOG_OWUI_LOCAL_DB", ""),
        owui_uploads_root=os.environ.get("CHATBLOG_OWUI_UPLOADS", ""),
        owui_web_base=web_base,
        data_dir=repo_root / ".chatblog",
        gemini_profile=str(studio_value("gemini_profile", os.environ.get("CHATBLOG_GEMINI_PROFILE", ""))),
        gemini_port=int(studio_value("gemini_port", 9333)),
        gemini_headless=bool(studio_value("gemini_headless", True)),
        open_browser=str(studio_value("open_browser", "auto")),
        classifier_provider=_first_env("CHATBLOG_CLASSIFIER")
        or ("gemini" if _first_env("GEMINI_API_KEY") else "openjev"),
        decision_base_url=_first_env("CHATBLOG_DECISION_BASE_URL")
        or "https://generativelanguage.googleapis.com/v1beta",
        decision_model=_first_env("CHATBLOG_DECISION_MODEL") or "gemini-decision-1",
        gemini_api_key=_first_env("GEMINI_API_KEY"),
        openjev_base_url=_first_env("CHATBLOG_OPENJEV_BASE_URL", "OPENJEV_BASE_URL")
        or str(studio_value("openjev_base_url", DEFAULT_OPENJEV_BASE)),
        openjev_api_key=_first_env("OPENJEV_API_KEY", "CODIV_API_KEY", "TYPESAFE_API_KEY")
        or str(studio.get("openjev_api_key") or ""),
        openjev_model=_first_env("OPENJEV_MODEL")
        or str(studio_value("openjev_model", DEFAULT_OPENJEV_MODEL)),
        taxonomy_path=str(studio_value("taxonomy_path", "")),
    )
