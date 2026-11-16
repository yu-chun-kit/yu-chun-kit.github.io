import json
import pytest

from chatblog import cli, studio
from chatblog.catalog import ChatEntry
from chatblog.classify import Classification
from chatblog.config import Settings
from chatblog.models import Conversation, DialogNode
from chatblog.taxonomy import Tag


@pytest.fixture
def service(tmp_path, monkeypatch):
    settings = Settings(
        repo_root=tmp_path,
        posts_dir=tmp_path / "posts",
        data_dir=tmp_path / ".chatblog",
    )
    monkeypatch.setattr(studio, "load_settings", lambda: settings)
    return studio.StudioService()


@pytest.mark.parametrize(
    ("provider", "error", "complete"),
    [("gemini", "", True), ("rules", "quota exhausted", False),
     ("gemini", "follow-up quota exhausted", False)],
)
def test_each_classification_is_saved_before_return_and_survives_restart(
    service, monkeypatch, provider, error, complete
):
    from chatblog import classify

    conversation = Conversation(
        source_provider="openwebui", source_chat_id="x", title="Hexo", root_id="u",
        messages={"u": DialogNode(id="u", role="user", content="Deploy Hexo")},
    )
    monkeypatch.setattr(cli, "fetch_conversation", lambda *args, **kwargs: conversation)
    monkeypatch.setattr(service, "systemone_client", lambda: object())
    monkeypatch.setattr(classify, "classify_conversation", lambda *args: Classification(
        tags=[Tag("技術程式", "domain", 0.9)], provider=provider,
        model="gemini-decision-1" if provider == "gemini" else "",
        error=error, input_tokens=123,
    ))
    entry = ChatEntry(key="openwebui:x", provider="openwebui", chat_id="x", title="Hexo")
    service.entries[entry.key] = entry
    job = studio.Job(kind="classify", keys=[entry.key])

    result = service.classify_key(entry.key, job)

    assert result["ok"] is complete
    assert result["needs_classification"] is not complete
    assert job.token_usage == 123
    restarted = studio.StudioService()
    saved = restarted.entries[entry.key]
    assert saved.tags == entry.tags
    assert saved.classification["complete"] is complete
    assert saved.classification["input_tokens"] == 123
    assert saved.classification["error"] == error
    assert saved.needs_classification is not complete


def test_classify_all_retries_rules_and_partial_results(service, monkeypatch):
    for chat_id, provider, complete in (
        ("done", "gemini", True), ("partial", "gemini", False), ("rules", "rules", False),
    ):
        entry = ChatEntry(key=f"openwebui:{chat_id}", provider="openwebui", chat_id=chat_id)
        entry.set_tags([Tag("技術程式", "domain", 0.9)], provider=provider, complete=complete)
        service.entries[entry.key] = entry
    entry = ChatEntry(key="openwebui:new", provider="openwebui", chat_id="new")
    service.entries[entry.key] = entry

    scheduled = []

    def start(kind, keys, worker, **kwargs):
        scheduled.extend(keys)
        return studio.Job(kind=kind, keys=keys, status="done")

    monkeypatch.setattr(service.jobs, "start", start)
    handler = object.__new__(studio.StudioHandler)
    handler.service = service
    handler._json = lambda *args: None
    handler._route_post("/api/classify", {"all": True})
    assert set(scheduled) == {"openwebui:partial", "openwebui:rules", "openwebui:new"}


def test_failed_atomic_save_preserves_previous_catalog(service, monkeypatch):
    service._save_catalog()
    original = service._catalog_path().read_bytes()
    entry = ChatEntry(key="openwebui:x", provider="openwebui", chat_id="x")
    service.entries[entry.key] = entry

    def fail_replace(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(studio.os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk unavailable"):
        service._save_catalog()
    assert service._catalog_path().read_bytes() == original
    assert json.loads(original)["entries"] == {}
