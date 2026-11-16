import base64
from pathlib import Path

import httpx
import pytest

from chatblog.assets import download_conversation_images
from chatblog.models import Conversation, DialogNode, ImageAttachment


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def build_conversation(*urls: str, chat_id: str = "abc123") -> Conversation:
    attachments = [ImageAttachment(url=url) for url in urls]
    return Conversation(
        source_provider="gemini",
        source_chat_id=chat_id,
        title="Test",
        root_id="turn-1-assistant",
        messages={
            "turn-1-assistant": DialogNode(
                id="turn-1-assistant",
                role="assistant",
                content="<p>hi</p>",
                content_format="html",
                attachments=attachments,
            )
        },
    )


def mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_downloads_images_and_rewrites_urls(tmp_path: Path):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG_BYTES)

    conversation = build_conversation("https://example.com/a.png")
    result = download_conversation_images(conversation, tmp_path, client=mock_client(handler))

    target = tmp_path / "images" / "gemini" / "abc123" / "image-01.png"
    assert target.read_bytes() == PNG_BYTES
    assert result.downloaded == [target]
    assert result.failed == []
    assert seen == ["https://example.com/a.png"]

    attachment = conversation.messages["turn-1-assistant"].attachments[0]
    assert attachment.url == "/images/gemini/abc123/image-01.png"
    assert attachment.source_url == "https://example.com/a.png"


def test_existing_file_is_reused_without_requests(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not download again")

    target = tmp_path / "images" / "gemini" / "abc123" / "image-01.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(PNG_BYTES)

    conversation = build_conversation("https://example.com/a.png")
    result = download_conversation_images(conversation, tmp_path, client=mock_client(handler))

    assert result.reused == [target]
    assert result.downloaded == []
    assert conversation.messages["turn-1-assistant"].attachments[0].url == "/images/gemini/abc123/image-01.png"


def test_already_localised_attachments_are_left_alone(tmp_path: Path):
    conversation = build_conversation("/images/gemini/abc123/image-01.png")

    result = download_conversation_images(conversation, tmp_path)

    assert result.total == 0
    assert not (tmp_path / "images").exists()


def test_force_redownloads_existing_file(tmp_path: Path):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"jpegdata")

    conversation = build_conversation("https://example.com/a.png")
    result = download_conversation_images(conversation, tmp_path, force=True, client=mock_client(handler))

    assert calls == ["https://example.com/a.png"]
    assert [path.name for path in result.downloaded] == ["image-01.jpg"]


def test_failed_download_keeps_remote_url(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"nope")

    conversation = build_conversation("https://example.com/missing.png")
    result = download_conversation_images(conversation, tmp_path, client=mock_client(handler))

    assert result.failed and result.failed[0][0] == "https://example.com/missing.png"
    assert result.downloaded == []
    assert conversation.messages["turn-1-assistant"].attachments[0].url == "https://example.com/missing.png"


def test_conversation_without_images_creates_no_directory(tmp_path: Path):
    conversation = build_conversation()

    result = download_conversation_images(conversation, tmp_path)

    assert result.total == 0
    assert not (tmp_path / "images").exists()


def test_relative_urls_use_base_url_and_bearer_header(tmp_path: Path):
    seen: list[tuple[str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG_BYTES)

    conversation = build_conversation("/api/v1/files/file-1/content", chat_id="chat-9")
    result = download_conversation_images(
        conversation,
        tmp_path,
        base_url="http://192.168.128.111:3000/api/v1",
        headers={"Authorization": "Bearer test-token"},
        client=mock_client(handler),
    )

    assert seen == [("http://192.168.128.111:3000/api/v1/files/file-1/content", "Bearer test-token")]
    assert result.downloaded == [tmp_path / "images" / "gemini" / "chat-9" / "image-01.png"]

    attachment = conversation.messages["turn-1-assistant"].attachments[0]
    assert attachment.url == "/images/gemini/chat-9/image-01.png"
    assert attachment.source_url == "/api/v1/files/file-1/content"


def test_relative_urls_are_ignored_without_base_url(tmp_path: Path):
    conversation = build_conversation("/api/v1/files/file-1/content")

    result = download_conversation_images(conversation, tmp_path)

    assert result.total == 0
    assert not (tmp_path / "images").exists()


def test_inline_data_url_is_decoded(tmp_path: Path):
    payload = base64.b64encode(PNG_BYTES).decode()
    conversation = build_conversation(f"data:image/png;base64,{payload}", chat_id="chat-7")

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("data URLs must not hit the network")

    result = download_conversation_images(conversation, tmp_path, client=mock_client(handler))

    target = tmp_path / "images" / "gemini" / "chat-7" / "image-01.png"
    assert target.read_bytes() == PNG_BYTES
    attachment = conversation.messages["turn-1-assistant"].attachments[0]
    assert attachment.url == "/images/gemini/chat-7/image-01.png"
    assert attachment.source_url == ""


def test_broken_data_url_is_reported(tmp_path: Path):
    conversation = build_conversation("data:image/png;base64,", chat_id="chat-7")

    result = download_conversation_images(conversation, tmp_path)

    assert result.failed and result.failed[0][0] == "inline data URL"


def test_reused_data_url_never_leaks_into_source_url(tmp_path: Path):
    """Regression: a reused image used to keep the raw data URL as source link."""
    target = tmp_path / "images" / "gemini" / "abc123" / "image-01.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(PNG_BYTES)

    payload = base64.b64encode(PNG_BYTES).decode()
    conversation = build_conversation(f"data:image/png;base64,{payload}")
    result = download_conversation_images(conversation, tmp_path)

    attachment = conversation.messages["turn-1-assistant"].attachments[0]
    assert result.reused == [target]
    assert attachment.url == "/images/gemini/abc123/image-01.png"
    assert attachment.source_url == ""


def test_openwebui_assets_live_under_their_provider(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG_BYTES)

    conversation = build_conversation("https://example.com/a.png", chat_id="chat-42")
    conversation.source_provider = "openwebui"

    result = download_conversation_images(
        conversation,
        tmp_path,
        base_url="http://192.168.128.111:3000/api/v1",
        client=mock_client(handler),
    )

    target = tmp_path / "images" / "openwebui" / "chat-42" / "image-01.png"
    assert result.downloaded == [target]
    assert conversation.messages["turn-1-assistant"].attachments[0].url == "/images/openwebui/chat-42/image-01.png"


@pytest.mark.parametrize(
    ("url", "content_type", "expected"),
    [
        ("https://example.com/a", "image/webp", ".webp"),
        ("https://example.com/a.JPG", "", ".jpg"),
        ("https://example.com/a", "", ".jpg"),
        ("https://example.com/a.png", "image/jpeg", ".jpg"),
    ],
)
def test_extension_detection(tmp_path: Path, url: str, content_type: str, expected: str):
    def handler(request: httpx.Request) -> httpx.Response:
        headers = {"content-type": content_type} if content_type else {}
        return httpx.Response(200, headers=headers, content=b"x")

    conversation = build_conversation(url)
    result = download_conversation_images(conversation, tmp_path, client=mock_client(handler))

    assert result.downloaded[0].name == f"image-01{expected}"
