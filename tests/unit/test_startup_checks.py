import pytest

from mpd_assistant.core.startup import assert_production_ready, problems

GOOD = {
    "ENV": "production",
    "SECRET_KEY": "s3cure-random-value",
    "DATABASE_URL": "postgresql://u:p@db.railway.internal/app",
    "REDIS_URL": "redis://:pw@redis.railway.internal:6379",
    "DATA_ENCRYPTION_KEY": "abc123",
    "BLIND_INDEX_KEY": "def456",
    "MCP_SERVICE_KEY": "svc789",
    "METRICS_TOKEN": "met000",
    "PUBLIC_DOMAIN": "https://assistant.masterprodev.com",
}


def test_complete_production_config_passes():
    assert_production_ready(GOOD)


def test_missing_and_placeholder_values_are_reported():
    env = dict(GOOD, DATA_ENCRYPTION_KEY="", SECRET_KEY="change-me")
    issues = problems(env)
    assert "DATA_ENCRYPTION_KEY is not set" in issues
    assert "SECRET_KEY still holds a placeholder value" in issues
    with pytest.raises(RuntimeError):
        assert_production_ready(env)


def test_development_is_never_blocked():
    assert_production_ready({"ENV": "development"})
