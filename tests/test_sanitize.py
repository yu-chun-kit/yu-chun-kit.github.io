from chatblog.sanitize import sanitize_html


def test_keeps_conversation_structure():
    raw = (
        '<div class="markdown"><h3 data-path-to-node="2">1. 标題</h3>'
        "<p>前<b>重點</b>後</p>"
        "<ul><li><p>項目一</p></li><li><p>項目二</p></li></ul></div>"
    )

    clean = sanitize_html(raw)

    assert "<h3>1. 标題</h3>" in clean
    assert "<strong>" not in clean  # <b> is kept as-is, not rewritten
    assert "<p>前<b>重點</b>後</p>" in clean
    assert "<ul><li><p>項目一</p></li><li><p>項目二</p></li></ul>" in clean
    assert "class=" not in clean
    assert "data-path-to-node" not in clean


def test_drops_scripts_styles_and_gemini_widgets():
    raw = (
        "<script>alert('x')</script><style>p{color:red}</style>"
        "<p>答案<source-footnote><sup>1</sup></source-footnote></p>"
        '<sources-carousel-inline><source-inline-chip>廣告標題</source-inline-chip></sources-carousel-inline>'
        "<follow-up><div>建議追問</div></follow-up>"
        "<mat-icon>content_copy</mat-icon>"
    )

    clean = sanitize_html(raw)

    assert clean == "<p>答案</p>"
    assert "alert" not in clean
    assert "廣告標題" not in clean
    assert "建議追問" not in clean
    assert "content_copy" not in clean


def test_unwraps_unknown_tags_but_keeps_text():
    clean = sanitize_html('<p>前<span class="citation-4">引用</span><user-query>後</user-query></p>')

    assert clean == "<p>前<span>引用</span>後</p>"


def test_blocks_dangerous_links_and_attributes():
    clean = sanitize_html(
        '<p><a href="javascript:alert(1)" onclick="alert(1)">壞</a>'
        '<a href="https://example.com/a?b=1&amp;c=2" title="有效">好</a>'
        '<a href="/relative/path">相對</a></p>'
    )

    assert 'onclick' not in clean
    assert "javascript:" not in clean
    assert '<a>壞</a>' in clean
    assert '<a href="https://example.com/a?b=1&amp;c=2" title="有效">好</a>' in clean
    assert '<a href="/relative/path">相對</a>' in clean


def test_closes_unbalanced_markup():
    clean = sanitize_html("<p>沒有結尾<ul><li>一")

    assert clean == "<p>沒有結尾<ul><li>一</li></ul></p>"


def test_handles_empty_input():
    assert sanitize_html("") == ""
    assert sanitize_html("純文字") == "純文字"
