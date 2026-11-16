import json

import httpx
import pytest

from chatblog.systemone import GeminiDecisionClient, SystemOneClient, SystemOneError


def make_client(handler, api_key="sk-test") -> SystemOneClient:
    return SystemOneClient(
        "https://api.example.test",
        api_key,
        "openjev-latest",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_ask_posts_typed_questions_and_returns_answers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "model": "openjev-latest",
                "answers": {
                    "has_code": {"type": "noul", "noul": 0.81},
                    "domain": {"type": "choice", "choice": "technology", "confidence": 0.9},
                },
                "usage": {"input_tokens": 321, "output_tokens": 0},
            },
        )

    client = make_client(handler)
    result = client.ask("state text", {"has_code": {"type": "noul", "instructions": "code?"}})

    assert seen["url"] == "https://api.example.test/v1/systemone"
    assert seen["auth"] == "Bearer sk-test"
    assert result["answers"]["has_code"]["noul"] == 0.81
    assert result["usage"].input_tokens == 321
    assert result["model"] == "openjev-latest"


def test_missing_key_fails_fast():
    client = SystemOneClient("https://api.example.test", "", "openjev-latest")
    assert client.configured is False
    with pytest.raises(SystemOneError, match="API key"):
        client.ask("state", {"q": {"type": "noul", "instructions": "?"}})


def test_error_status_includes_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid api key"})

    client = make_client(handler)
    with pytest.raises(SystemOneError) as info:
        client.ask("state", {"q": {"type": "noul", "instructions": "?"}})
    assert info.value.status == 401
    assert "invalid api key" in str(info.value)


def test_health_lists_models():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "openjev-latest"}]})

    info = make_client(handler).health()
    assert info["models"] == ["openjev-latest"]


def test_health_falls_back_to_a_probe_when_listing_is_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(
            200,
            json={"model": "openjev-latest", "answers": {"ok": {"type": "noul", "noul": 0.9}}},
        )

    info = make_client(handler).health()
    assert info["ok"] is True
    assert info["probe"]["ok"]["noul"] == 0.9


def test_gemini_uses_native_proxy_path_auth_input_and_usage():
    questions = {"ok": {"type": "noul", "instructions": "Is this a test?"}}

    def handler(request):
        assert str(request.url) == "https://proxy.example/googleai/v1beta/decisions"
        assert request.headers["x-goog-api-key"] == "test-key"
        assert "authorization" not in request.headers
        assert json.loads(request.content) == {
            "model": "gemini-decision-1", "input": "A test.", "questions": questions,
        }
        return httpx.Response(200, json={
            "answers": {"ok": {"type": "noul", "noul": 0.99, "confidence": 0.99}},
            "usage": {"total_input_tokens": 93, "total_output_tokens": 0},
        })

    client = GeminiDecisionClient(
        "https://proxy.example/googleai/v1beta/openai/", "test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.ask("A test.", questions)
    assert result["model"] == "gemini-decision-1"
    assert result["usage"].input_tokens == 93
    assert result["usage"].output_tokens == 0


@pytest.mark.parametrize("payload", [{}, {"answers": {}}, {"answers": {"ok": None}}])
def test_gemini_rejects_missing_answers(payload):
    client = GeminiDecisionClient("https://proxy.example/v1beta", "test-key", client=httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    ))
    with pytest.raises(SystemOneError):
        client.health()


def test_gemini_error_redacts_key_and_preserves_status():
    client = GeminiDecisionClient("https://proxy.example/v1beta", "secret-test-key", client=httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(403, json={
            "error": {"message": "Denied: secret-test-key"},
        })),
    ))
    with pytest.raises(SystemOneError) as info:
        client.health()
    assert info.value.status == 403
    assert "secret-test-key" not in str(info.value)
