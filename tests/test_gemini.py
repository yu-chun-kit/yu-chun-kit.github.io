from chatblog.gemini import (
    GeminiShareData,
    GeminiTurn,
    build_conversation_from_share,
    extract_share_id,
    parse_header_metadata,
)
from chatblog.models import ImageAttachment
from chatblog.render import render_hexo_post


def test_parse_gemini_header_metadata():
    header = (
        "匮乏：留学与小说的核心驱动\n"
        "https://gemini.google.com/share/0857f1489b17\n"
        "Created with 3.1 Pro June 28, 2026 at 10:58 PM\n"
        "Published June 28, 2026 at 11:12 PM"
    )

    model, created_at, published_at = parse_header_metadata(header)

    assert model == "3.1 Pro"
    assert created_at is not None
    assert created_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-06-28 22:58:00"
    assert published_at is not None
    assert published_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-06-28 23:12:00"


def test_build_gemini_conversation_and_render_provider():
    conversation = build_conversation_from_share(
        GeminiShareData(
            url="https://gemini.google.com/share/0857f1489b17",
            title="匮乏：留学与小说的核心驱动",
            model="3.1 Pro",
            created_at=None,
            published_at=None,
            turns=[
                GeminiTurn(
                    user="第一问",
                    assistant="第一答",
                    images=[
                        ImageAttachment(
                            url="/images/gemini/0857f1489b17/image-01.jpg",
                            alt="示意图",
                            caption="示意图 caption",
                            source_url="https://example.com/image.jpg",
                        )
                    ],
                ),
                GeminiTurn(user="第二问", assistant="第二答"),
            ],
        )
    )

    assert conversation.source_provider == "gemini"
    assert conversation.source_chat_id == "0857f1489b17"
    assert conversation.root_id == "turn-1-user"
    assert conversation.message_count == 4
    assert conversation.branch_count == 0
    assert conversation.models == ["3.1 Pro"]
    assert conversation.messages["turn-1-assistant"].children_ids == ["turn-2-user"]
    assert conversation.messages["turn-1-assistant"].attachments[0].alt == "示意图"

    post = render_hexo_post(conversation, override_date="2026-06-28")
    assert 'source_provider: "gemini"' in post
    assert 'source_chat_id: "0857f1489b17"' in post
    assert "第一问" in post
    assert "第二答" in post
    assert '<figure class="dialog-attachment">' in post
    assert 'src="/images/gemini/0857f1489b17/image-01.jpg"' in post


def test_extract_share_id_handles_short_and_canonical_urls():
    assert extract_share_id("https://gemini.google.com/share/0857f1489b17") == "0857f1489b17"
    assert extract_share_id("https://share.gemini.google/WbEoJEIlbTpC") == "WbEoJEIlbTpC"
