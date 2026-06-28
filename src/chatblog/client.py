from __future__ import annotations

from typing import Any

import httpx

from .models import ChatSummary
from .normalize import normalize_chat_list


class OpenWebUIClient:
    def __init__(self, api_base: str, api_token: str, timeout: float = 30.0) -> None:
        if not api_token:
            raise ValueError("OPENWEBUI_API_TOKEN is not set")
        self.api_base = api_base.rstrip("/")
        self.api_token = api_token
        self.timeout = timeout

    def request_json(self, endpoint: str) -> Any:
        url = f"{self.api_base}{endpoint}"
        headers = {"Authorization": f"Bearer {self.api_token}", "Accept": "application/json"}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    def fetch_chat(self, chat_id: str) -> dict[str, Any]:
        data = self.request_json(f"/chats/{chat_id}")
        if not isinstance(data, dict):
            raise ValueError("OpenWebUI chat response is not an object")
        return data

    def list_chats(self, limit: int = 10, page: int = 1) -> list[ChatSummary]:
        limit = max(limit, 1)
        page = max(page, 1)

        errors: list[Exception] = []
        for endpoint in (f"/chats/?page={page}", f"/chats?page={page}"):
            try:
                return normalize_chat_list(self.request_json(endpoint))[:limit]
            except Exception as exc:  # pragma: no cover - fallback behavior is integration-level
                errors.append(exc)

        for endpoint in ("/chats/", "/chats"):
            try:
                chats = normalize_chat_list(self.request_json(endpoint))
                offset = (page - 1) * limit
                return chats[offset : offset + limit]
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        message = "; ".join(str(error) for error in errors[-2:])
        raise RuntimeError(f"Could not fetch OpenWebUI chat list: {message}")
