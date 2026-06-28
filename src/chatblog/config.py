from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_API_BASE = "http://localhost:3000/api/v1"


class Settings(BaseModel):
    api_base: str = DEFAULT_API_BASE
    api_token: str = ""
    repo_root: Path = REPO_ROOT
    posts_dir: Path = REPO_ROOT / "source" / "_posts"


def load_settings() -> Settings:
    """Load configuration from repo .env files and process environment."""
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv(REPO_ROOT / "scripts" / ".env")

    return Settings(
        api_base=os.environ.get("OPENWEBUI_API_BASE", DEFAULT_API_BASE).rstrip("/"),
        api_token=os.environ.get("OPENWEBUI_API_TOKEN", ""),
    )
