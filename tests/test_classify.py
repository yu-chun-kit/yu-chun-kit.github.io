from datetime import datetime

from chatblog.classify import (
    build_state,
    classify_text,
    conversation_transcript,
    node_text,
)
from chatblog.models import Conversation, DialogNode
from chatblog.systemone import SystemOneClient, SystemOneError
from chatblog.taxonomy import load_taxonomy


def build_conversation() -> Conversation:
    messages = {
        "u1": DialogNode(id="u1", role="user", content="<p>如何用 Hexo 部署？</p>", children_ids=["a1"]),
        "a1": DialogNode(
            id="a1",
            role="assistant",
            content="<p>用 GitHub Actions。</p>",
            parent_id="u1",
            children_ids=["u2"],
            model_name="gpt-x",
        ),
        "u2": DialogNode(id="u2", role="user", content="謝謝", parent_id="a1", children_ids=[]),
    }
    return Conversation(
        source_provider="openwebui",
        source_chat_id="chat-1",
        title="Hexo 部署",
        root_id="u1",
        created_at=datetime(2026, 10, 1, 8, 0),
        updated_at=datetime(2026, 10, 2, 9, 30),
        messages=messages,
    )


class FakeClient:
    configured = True

    def __init__(self, answers=None, error=None):
        self.answers = answers or {}
        self.error = error

    def ask(self, state, questions, **kwargs):
        if self.error:
            raise SystemOneError(self.error)
        return {
            "answers": self.answers,
            "model": "openjev-latest",
            "usage": type("Usage", (), {"input_tokens": 42, "output_tokens": 0})(),
        }


def test_node_text_strips_markup():
    node = DialogNode(id="x", role="user", content="<p>a\u00a0 b</p><script>x</script>")
    assert node_text(node) == "a b x"


def test_transcript_walks_main_line_and_keeps_branches():
    conversation = build_conversation()
    conversation.messages["a1"].children_ids = ["u2", "b1"]
    conversation.messages["b1"] = DialogNode(
        id="b1", role="assistant", content="分支答案", parent_id="a1", children_ids=["u3"]
    )
    conversation.messages["u3"] = DialogNode(
        id="u3", role="user", content="分支追問", parent_id="b1", children_ids=[]
    )
    transcript = conversation_transcript(conversation)
    assert "我：如何用 Hexo 部署？" in transcript
    assert "AI：用 GitHub Actions。" in transcript
    assert "分支答案" in transcript  # extra roots/trees are not dropped
    assert "我：謝謝" in transcript


def test_build_state_clips_long_transcripts():
    state = build_state(
        "長對話",
        "gemini",
        "字" * 20_000,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 2, 1),
        models=["gemini-2.5-pro"],
        message_count=12,
    )
    assert "標題：長對話" in state
    assert "更新：2026-02-01" in state
    assert "訊息數：12" in state
    assert "中略" in state
    assert len(state) < 20_000


def test_classify_text_uses_model_answers():
    taxonomy = load_taxonomy()
    client = FakeClient(
        answers={
            "domain": {"type": "choice", "choice": "technology", "confidence": 0.9},
            "concept": {"type": "choice", "choice": "hexo", "confidence": 0.8},
            "depth": {"type": "score", "score": 1.0, "confidence": 0.5},
        }
    )
    result = classify_text("Hexo 部署", "hexo deployment", taxonomy, client)
    assert result.provider == "openjev"
    assert result.complete is True
    assert result.model == "openjev-latest"
    assert result.input_tokens >= 42
    assert [tag.name for tag in result.tags][:2] == ["技術程式", "Hexo"]
    assert "深度 2/5" in [tag.name for tag in result.tags]


def test_classify_text_falls_back_to_rules_on_error():
    taxonomy = load_taxonomy()
    client = FakeClient(error="quota exhausted")
    result = classify_text("Hexo 部署", "用 hexo 和 docker 部署", taxonomy, client)
    assert result.provider == "rules"
    assert result.error == "quota exhausted"
    assert result.complete is False
    assert result.tags[0].name == "技術程式"


def test_rules_only_when_no_client():
    taxonomy = load_taxonomy()
    result = classify_text("Hexo 部署", "用 hexo 部署", taxonomy, None)
    assert result.provider == "rules"
    assert result.tags
    assert result.complete is False


def test_followup_failure_keeps_coarse_tags_and_usage_but_remains_pending():
    class FollowupFails(FakeClient):
        def ask(self, state, questions, **kwargs):
            if "domain" not in questions:
                raise SystemOneError("Gemini Decisions 回應 429：quota exhausted", status=429)
            return super().ask(state, questions, **kwargs)

    client = FollowupFails(answers={
        "domain": {"type": "choice", "choice": "technology", "confidence": 0.95},
    })
    client.provider = "gemini"
    result = classify_text("Hexo", "Deploy a Hexo blog.", load_taxonomy(), client)
    assert result.provider == "gemini"
    assert result.tags[0].name == "技術程式"
    assert result.input_tokens == 42
    assert "429" in result.error
    assert result.complete is False
    assert result.to_dict()["complete"] is False


def test_gemini_classification_records_actual_provider():
    client = FakeClient(answers={
        "domain": {"type": "choice", "choice": "technology", "confidence": 0.95},
    })
    client.provider = "gemini"
    result = classify_text("Hexo", "Deploy a Hexo blog.", load_taxonomy(), client)
    assert result.provider == "gemini"
    assert result.tags
