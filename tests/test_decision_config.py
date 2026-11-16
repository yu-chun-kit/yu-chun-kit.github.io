from chatblog import config, studio
from chatblog.systemone import GeminiDecisionClient, SystemOneClient


def test_dotenv_selects_gemini_and_studio_hides_its_key(tmp_path, monkeypatch):
    for name in ("GEMINI_API_KEY", "CHATBLOG_CLASSIFIER", "CHATBLOG_DECISION_BASE_URL",
                 "CHATBLOG_DECISION_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "discover_repo_root", lambda: tmp_path)
    (tmp_path / ".env").write_text(
        "GEMINI_API_KEY=private-test-value\n"
        "CHATBLOG_DECISION_BASE_URL=https://proxy.example/googleai/v1beta/openai\n",
        encoding="utf-8",
    )
    settings = config.load_settings()
    monkeypatch.setattr(studio, "load_settings", lambda: settings)
    service = studio.StudioService()
    client = service.systemone_client()
    assert isinstance(client, GeminiDecisionClient)
    assert client.api_key == "private-test-value"
    assert client.base_url == "https://proxy.example/googleai/v1beta"
    payload = service.settings_payload()
    assert payload["classifier_model"] == "gemini-decision-1"
    assert payload["classifier_key_set"] is True
    assert "private-test-value" not in str(payload)


def test_explicit_openjev_override_preserves_previous_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "discover_repo_root", lambda: tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-value")
    monkeypatch.setenv("CHATBLOG_CLASSIFIER", "openjev")
    monkeypatch.setenv("OPENJEV_API_KEY", "openjev-test-value")
    service = object.__new__(studio.StudioService)
    service._settings = config.load_settings()
    client = service.systemone_client()
    assert type(client) is SystemOneClient
    assert client.api_key == "openjev-test-value"
