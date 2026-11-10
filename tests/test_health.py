from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app


def test_health_ok_and_never_leaks_secrets(monkeypatch):
    secret = "sk-test-should-never-appear"
    monkeypatch.setenv("ASSEMBLYAI_API_KEY", secret)
    get_settings.cache_clear()
    try:
        r = TestClient(app).get("/health")
    finally:
        get_settings.cache_clear()
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "ASSEMBLYAI_API_KEY" not in body["missing_secrets"]
    assert secret not in r.text


def test_missing_secrets_listed_when_unset():
    s = Settings(_env_file=None, assemblyai_api_key="", kavach_warning_voice_id="",
                 telegram_bot_token="", telegram_chat_id="")
    assert s.missing_secrets() == ["ASSEMBLYAI_API_KEY", "TELEGRAM_BOT_TOKEN"]


def test_defaults_match_plan():
    s = Settings(_env_file=None)
    assert s.language == "english"
    assert s.stt_language_codes == ["en"]
    assert s.sample_rate == 16000
    assert s.risk_threshold == 60
    assert s.persona_voice_id != s.kavach_warning_voice_id


def test_env_file_is_gitignored():
    with open(".gitignore") as f:
        assert ".env" in f.read().split()
