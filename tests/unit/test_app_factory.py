from fastapi.testclient import TestClient

from mpd_assistant.api import app as app_module
from mpd_assistant.core import config, crypto


def _env(monkeypatch, env="development"):
    key = crypto.generate_key()
    for k, v in {
        "SECRET_KEY": "x" * 16,
        "DATABASE_URL": "postgresql://u:p@h/d",
        "REDIS_URL": "redis://localhost:1",
        "DATA_ENCRYPTION_KEY": key,
        "BLIND_INDEX_KEY": crypto.generate_key(),
        "METRICS_TOKEN": "m",
        "ENV": env,
    }.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()


def test_factory_builds_working_app_in_development(monkeypatch):
    _env(monkeypatch)
    client = TestClient(app_module.create())
    assert client.get("/health").json() == {"status": "ok"}
    assert "Hello" in client.post("/v2/chat", json={"message": "hi"}).json()["reply"]
    config.get_settings.cache_clear()


def test_production_refuses_to_start_without_keys(monkeypatch):
    _env(monkeypatch, "production")
    monkeypatch.delenv("DATA_ENCRYPTION_KEY")
    config.get_settings.cache_clear()
    try:
        app_module.build_services()
    except RuntimeError as exc:
        assert "DATA_ENCRYPTION_KEY" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
    config.get_settings.cache_clear()
