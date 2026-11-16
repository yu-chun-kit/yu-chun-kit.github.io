"""Client for the System One wire API used by Jev and OpenJev.

TypeSafe's Jev answers *typed questions* about a ``state`` instead of
generating text::

    POST /v1/systemone
    {"model": "openjev-latest",
     "state": "...conversation...",
     "questions": {"domain": {"type": "choice", "instructions": "...",
                              "criteria": {"philosophy": "...", ...}}}}

The response is ``{"model": ..., "answers": {name: {...}}, "usage": ...}``.
Every answer is a probability distribution, so a tag can carry a confidence
and a low-confidence tag can be flagged instead of being trusted blindly.

The same client talks to:

* the free OpenJev tier on Codiv (``https://api.codiv.ai``),
* a self-hosted ``openjev`` / ``wev serve`` server,
* TypeSafe's own ``https://api.typesafe.ai``.

Only the base URL, key and model name change.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.codiv.ai"
DEFAULT_MODEL = "openjev-latest"
DEFAULT_TIMEOUT = 90.0

#: Hosts that answer ``GET /v1/models`` (OpenJev does, TypeSafe does too).
_RETRY_STATUSES = {429, 502, 503, 504, 529}


class SystemOneError(RuntimeError):
    """Raised when the System One endpoint cannot answer a request."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class SystemOneUsage:
    input_tokens: int = 0
    output_tokens: int = 0


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "").strip()[:300] or response.reason_phrase
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("error") or payload
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("error_type") or detail
        return str(detail)[:300]
    return str(payload)[:300]


class SystemOneClient:
    """Small, dependency-light wrapper around ``POST /v1/systemone``."""

    provider = "openjev"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or ""
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key.strip()}"
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        owned = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            for attempt in range(3):
                response = client.request(
                    method, f"{self.base_url}{path}", headers=self._headers(), **kwargs
                )
                if response.status_code not in _RETRY_STATUSES or attempt == 2:
                    return response
                time.sleep(1.5 * (attempt + 1))
            return response  # pragma: no cover - loop always returns
        except httpx.HTTPError as exc:
            raise SystemOneError(f"連不到 {self.base_url}：{exc}") from exc
        finally:
            if owned:
                client.close()

    def ask(
        self,
        state: str,
        questions: dict[str, dict[str, Any]],
        *,
        samples: int | None = None,
        sequential: bool = False,
    ) -> dict[str, Any]:
        """Ask every typed question about ``state`` and return raw answers."""
        if not questions:
            raise ValueError("questions must not be empty")
        if not self.configured:
            raise SystemOneError("未設定 API key（Codiv / OpenJev / TypeSafe）")

        payload: dict[str, Any] = {
            "model": self.model,
            "state": state,
            "questions": questions,
        }
        if samples and samples > 1:
            payload["samples"] = int(samples)
        if sequential:
            payload["sequential"] = True

        response = self._request("POST", "/v1/systemone", json=payload)
        if response.status_code >= 400:
            raise SystemOneError(
                f"System One 回應 {response.status_code}：{_error_detail(response)}",
                status=response.status_code,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise SystemOneError("System One 回應不是 JSON") from exc
        answers = data.get("answers") if isinstance(data, dict) else None
        if not isinstance(answers, dict):
            raise SystemOneError("System One 回應缺少 answers")
        usage = data.get("usage") or {}
        return {
            "answers": answers,
            "model": str(data.get("model") or self.model),
            "usage": SystemOneUsage(
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
            ),
        }

    def health(self, timeout: float = 10.0) -> dict[str, Any]:
        """Ping the endpoint so the settings dialog can say "connected"."""
        if not self.configured:
            raise SystemOneError("未設定 API key")
        try:
            response = self._request("GET", "/v1/models")
        except SystemOneError:
            raise
        if response.status_code < 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            models = None
            if isinstance(payload, dict):
                # OpenAI style is {"data": [{"id": ...}]}; Codiv answers
                # {"models": [{"name": ..., "description": ...}]}.
                models = payload.get("data") or payload.get("models")
            names = [
                str(item.get("id") or item.get("name"))
                for item in models or []
                if isinstance(item, dict) and (item.get("id") or item.get("name"))
            ]
            return {"ok": True, "models": names, "model": self.model}

        # Some deployments only expose /v1/systemone; a one-question probe is
        # a stronger check than a 404 on the listing route.
        probe = self.ask(
            "Ping.",
            {"ok": {"type": "noul", "instructions": "Is this a harmless connectivity test?"}},
        )
        return {"ok": True, "models": [], "model": probe["model"], "probe": probe["answers"]}


class GeminiDecisionClient(SystemOneClient):
    """Google Decisions API with the classifier's existing typed-answer interface."""

    provider = "gemini"

    def __init__(
        self,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        api_key: str = "",
        model: str = "gemini-decision-1",
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ) -> None:
        # Accept the user's OpenAI-compatible proxy base, but use the native API.
        base_url = base_url.rstrip("/").removesuffix("/openai")
        super().__init__(base_url, api_key, model, timeout, client)

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-goog-api-key": self.api_key.strip(),
        }

    def ask(
        self,
        state: str,
        questions: dict[str, dict[str, Any]],
        *,
        samples: int | None = None,
        sequential: bool = False,
    ) -> dict[str, Any]:
        if not questions:
            raise ValueError("questions must not be empty")
        if not self.configured:
            raise SystemOneError("未設定 GEMINI_API_KEY")
        response = self._request(
            "POST", "/decisions",
            json={"model": self.model, "input": state, "questions": questions},
        )
        if response.status_code >= 400:
            detail = _error_detail(response).replace(self.api_key.strip(), "[REDACTED]")
            raise SystemOneError(
                f"Gemini Decisions 回應 {response.status_code}：{detail}",
                status=response.status_code,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise SystemOneError("Gemini Decisions 回應不是 JSON") from exc
        if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
            raise SystemOneError("Gemini Decisions 回應缺少 answers")
        if any(not isinstance(data["answers"].get(name), dict) for name in questions):
            raise SystemOneError("Gemini Decisions 回應缺少問題的答案")
        usage = data.get("usage") or {}
        return {
            "answers": data["answers"],
            "model": self.model,
            "usage": SystemOneUsage(
                input_tokens=int(usage.get("total_input_tokens") or 0),
                output_tokens=int(usage.get("total_output_tokens") or 0),
            ),
        }

    def health(self, timeout: float = 10.0) -> dict[str, Any]:
        probe = self.ask(
            "A connectivity check.",
            {"ok": {"type": "noul", "instructions": "Is this a connectivity check?"}},
        )
        return {"ok": True, "models": [self.model], "model": self.model, "probe": probe["answers"]}
