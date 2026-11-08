"""The post-deploy smoke script, run in-process against the real application factory and against a deliberately broken app."""

import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mpd_assistant.api import app as app_module
from mpd_assistant.core import config, crypto

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke_test.py"
spec = importlib.util.spec_from_file_location("smoke_test", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def _env(monkeypatch, **extra):
    base = {
        "SECRET_KEY": "x" * 16, "DATABASE_URL": "postgresql://u:p@127.0.0.1:1/d", "REDIS_URL": "redis://127.0.0.1:1",
        "DATA_ENCRYPTION_KEY": crypto.generate_key(), "BLIND_INDEX_KEY": crypto.generate_key(), "METRICS_TOKEN": "metrics-token",
        "ENV": "development", "ADMIN_TOKEN": "staff",
    }
    for key, value in {**base, **extra}.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()


def test_a_healthy_app_passes_every_check(monkeypatch):
    _env(monkeypatch)
    client = TestClient(app_module.create())
    results = smoke.run_checks(client, metrics_token="metrics-token")
    failed = [(r.name, r.detail) for r in results if not r.ok]
    assert failed == [], failed
    assert len(results) >= 11
    config.get_settings.cache_clear()


def test_a_wrong_metrics_token_fails_only_that_check(monkeypatch):
    _env(monkeypatch)
    client = TestClient(app_module.create())
    failed = {r.name for r in smoke.run_checks(client, metrics_token="wrong") if not r.ok}
    assert failed == {"metrics with the token"}
    config.get_settings.cache_clear()


def test_a_broken_app_fails_loudly():
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "down"}

    @app.post("/v2/webhooks/stripe")
    def stripe():
        return {"accepted": True}  # an unsigned webhook must never be accepted

    results = smoke.run_checks(TestClient(app))
    failed = {r.name for r in results if not r.ok}
    assert {"health endpoint", "visitor session", "unsigned Stripe webhook is refused", "security headers"} <= failed
    assert all(r.detail for r in results if not r.ok)


def test_a_network_error_is_a_failed_check_not_a_crash():
    results = smoke.run_checks(TestClient(FastAPI()), tools={"calendar": "http://127.0.0.1:1"})
    names = {r.name: r for r in results}
    assert not names["calendar service is healthy"].ok and "Error" in names["calendar service is healthy"].detail


def test_command_line_exit_code(monkeypatch, capsys):
    class Down:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return TestClient(FastAPI())

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(smoke.httpx, "Client", Down)
    assert smoke.main(["http://example.invalid"]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "checks passed" in out
