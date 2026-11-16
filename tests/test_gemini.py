from chatblog.gemini import (
    GeminiShareData,
    GeminiTurn,
    build_conversation_from_share,
    dedupe_query_text,
    extract_share_id,
    parse_header_metadata,
    parse_model_name,
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


def test_parse_gemini_header_metadata_handles_narrow_spaces():
    header = "Created with Pro September 24, 2026 at 12:01\u202fAM Published September 24, 2026 at 12:52\u202fAM"

    model, created_at, published_at = parse_header_metadata(header)

    assert model == "Pro"
    assert created_at is not None
    assert created_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-24 00:01:00"
    assert published_at is not None
    assert published_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-24 00:52:00"


def test_parse_model_name_falls_back_to_gemini():
    assert parse_model_name("Created with 3.1 Pro June 28, 2026 at 10:58 PM") == "3.1 Pro"
    assert parse_model_name("沒有限定模型") == "Gemini"


def test_parse_model_name_does_not_swallow_published_sentence():
    # Regression: "Created with Pro" and the creation date are separate spans,
    # so flattening the header used to produce the model "Pro Published".
    assert parse_model_name("Created with Pro Published September 24, 2026 at 12:52 AM") == "Pro"


def test_dedupe_query_text_removes_screen_reader_duplicate():
    prompt = "為什麼色情影片在國內是禁播的，黄果短剧卻可以大量生產？"
    duplicated = f"You said {prompt}\n\n{prompt}"

    assert dedupe_query_text(duplicated) == prompt
    assert dedupe_query_text(prompt) == prompt
    assert dedupe_query_text("  第一段\n\n第二段  ") == "第一段\n\n第二段"


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
                    assistant_html=(
                        "<h3>小標題</h3><p>第一答</p>"
                        "<ul><li><p>重點</p></li></ul>"
                        "<p>引用<source-footnote><sup>1</sup></source-footnote>"
                        '<sources-carousel-inline><source-inline-chip>廣告</source-inline-chip></sources-carousel-inline></p>'
                        '<script>alert("x")</script>'
                    ),
                    images=[
                        ImageAttachment(
                            url="/images/gemini/0857f1489b17/image-01.jpg",
                            alt="示意图",
                            caption="示意图 caption",
                            source_url="https://example.com/image.jpg",
                        )
                    ],
                ),
                GeminiTurn(user="第二问", assistant_html="<p>第二答</p>"),
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
    assert conversation.messages["turn-1-assistant"].content_format == "html"
    assert conversation.messages["turn-1-user"].content_format == "markdown"

    post = render_hexo_post(conversation, override_date="2026-06-28")
    assert 'source_provider: "gemini"' in post
    assert 'source_chat_id: "0857f1489b17"' in post
    assert "第一问" in post
    assert "第二答" in post
    assert "<h3>小標題</h3>" in post
    assert "<ul><li><p>重點</p></li></ul>" in post
    assert "廣告" not in post
    assert "alert" not in post
    assert '<figure class="dialog-attachment">' in post
    assert 'src="/images/gemini/0857f1489b17/image-01.jpg"' in post


def test_extract_share_id_handles_short_and_canonical_urls():
    assert extract_share_id("https://gemini.google.com/share/0857f1489b17") == "0857f1489b17"
    assert extract_share_id("https://share.gemini.google/WbEoJEIlbTpC") == "WbEoJEIlbTpC"
    assert extract_share_id("https://gemini.google.com/share/de5a44c3ef54?skid=abc") == "de5a44c3ef54"


def _batchexecute(payload, rpc="MaZiqc") -> str:
    import json as _json

    entry = ["wrb.fr", rpc, _json.dumps(payload, ensure_ascii=False), None, None, None, "generic"]
    return ")]}'\n\n123\n" + _json.dumps([entry], ensure_ascii=False) + "\n25\n[[\"e\",4]]\n"


def test_parse_conversation_list_reads_ids_titles_and_timestamps():
    from chatblog.gemini_web import parse_conversation_list

    rows = [
        ["c_abc123", "第一個對話", None, None, None, [1762000000, 123456789], None, None, None, 2],
        ["c_def456", "第二個對話", None, None, None, [1761900000, 0], None, None, None, 2],
        ["c_abc123", "重複", None, None, None, [1762000000, 0], None, None, None, 2],
    ]
    items = parse_conversation_list(_batchexecute(rows))

    assert [item.chat_id for item in items] == ["abc123", "def456"]
    assert items[0].title == "第一個對話"
    from datetime import datetime as _dt

    assert items[0].updated_at == _dt.fromtimestamp(1762000000)


def test_parse_conversation_list_handles_the_paged_shape():
    from chatblog.gemini_web import parse_conversation_list

    rows = [["c_xyz789", "分頁對話", None, None, None, [1761800000, 0], None, None, None, 2]]
    payload = [None, "cursor-token", rows]
    items = parse_conversation_list(_batchexecute(payload))

    assert len(items) == 1
    assert items[0].chat_id == "xyz789"


def test_parse_conversation_list_survives_garbage():
    from chatblog.gemini_web import parse_conversation_list

    assert parse_conversation_list("") == []
    assert parse_conversation_list(")]}'\n\n1\n[[]]\n") == []
    assert parse_conversation_list("not json at all") == []
