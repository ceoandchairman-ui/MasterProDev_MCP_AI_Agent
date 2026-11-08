"""The local integration stack: compose file shape, image packaging, and the secrets script."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from mpd_assistant.core.crypto import FieldCipher

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "deploy" / "compose.dev.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]

spec = importlib.util.spec_from_file_location("dev_env", ROOT / "scripts" / "dev_env.py")
dev_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev_env)


def test_the_stack_has_the_expected_services_and_profiles():
    assert set(SERVICES) == {"postgres", "redis", "migrate", "api", "worker", "mcp-calendar", "mcp-gmail", "mcp-quoting", "mcp-db"}
    always_on = {name for name, s in SERVICES.items() if "profiles" not in s}
    assert always_on == {"postgres", "redis", "migrate"}  # the default `up` is just the stores and the schema
    assert SERVICES["api"]["profiles"] == ["app"] and SERVICES["worker"]["profiles"] == ["app"]
    assert all(SERVICES[s]["profiles"] == ["tools"] for s in ("mcp-calendar", "mcp-gmail", "mcp-quoting", "mcp-db"))


def test_stores_use_the_images_the_code_needs_and_are_pinned():
    assert SERVICES["postgres"]["image"].startswith("pgvector/pgvector:")
    assert SERVICES["redis"]["image"].startswith("redis/redis-stack-server:")  # plain Redis lacks the search and JSON modules
    for name in ("postgres", "redis"):
        assert not SERVICES[name]["image"].endswith(":latest")


def test_every_published_port_is_local_only():
    for name, service in SERVICES.items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} on every interface"


def test_the_app_waits_for_the_schema_and_the_stores():
    for name in ("api", "worker"):
        needs = SERVICES[name]["depends_on"]
        assert needs["migrate"]["condition"] == "service_completed_successfully" and needs["redis"]["condition"] == "service_healthy"
    assert SERVICES["migrate"]["command"] == ["alembic", "upgrade", "head"]
    assert SERVICES["migrate"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert SERVICES["api"]["environment"]["REDIS_URL"] == "redis://redis:6379/0"


def test_secrets_come_from_the_generated_file_not_the_compose_file():
    text = (ROOT / "deploy" / "compose.dev.yml").read_text(encoding="utf-8")
    for secret in ("DATA_ENCRYPTION_KEY", "BLIND_INDEX_KEY", "MCP_SERVICE_KEY", "ADMIN_TOKEN"):
        assert secret not in text.replace("DATA_ENCRYPTION_KEY, BLIND", "")  # none is written into the compose file
    assert all(SERVICES[s]["env_file"] == "../.env.dev" for s in ("api", "worker", "mcp-calendar", "mcp-gmail", "mcp-quoting", "mcp-db"))


def test_every_dockerfile_the_stack_builds_exists():
    for service in SERVICES.values():
        build = service.get("build")
        if build:
            assert (ROOT / build["dockerfile"]).exists(), build["dockerfile"]


def test_the_api_image_carries_the_migrations():
    dockerfile = (ROOT / "deploy" / "dockerfiles" / "api.Dockerfile").read_text(encoding="utf-8")
    assert "COPY alembic.ini" in dockerfile and "COPY migrations" in dockerfile
    assert (ROOT / "alembic.ini").exists() and (ROOT / "migrations" / "env.py").exists()


# --- scripts/dev_env.py ------------------------------------------------------------------
def test_generated_env_has_usable_keys_and_no_placeholders():
    values = dict(line.split("=", 1) for line in dev_env.build().splitlines() if "=" in line and not line.startswith("#"))
    FieldCipher(values["DATA_ENCRYPTION_KEY"])  # a valid encryption key
    FieldCipher(values["BLIND_INDEX_KEY"])
    assert len(values["SECRET_KEY"]) >= 32 and values["DATA_ENCRYPTION_KEY"] != values["BLIND_INDEX_KEY"]
    from mpd_assistant.core.startup import PLACEHOLDER_MARKERS

    assert not any(marker in v.lower() for v in values.values() for marker in PLACEHOLDER_MARKERS)
    assert dev_env.build() != dev_env.build()  # fresh values every time


def test_dev_env_never_overwrites_without_force(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dev_env, "TARGET", tmp_path / ".env.dev")
    assert dev_env.main([]) == 0
    first = (tmp_path / ".env.dev").read_text(encoding="utf-8")
    assert dev_env.main([]) == 1 and (tmp_path / ".env.dev").read_text(encoding="utf-8") == first
    assert "--force" in capsys.readouterr().err
    assert dev_env.main(["--force"]) == 0 and (tmp_path / ".env.dev").read_text(encoding="utf-8") != first


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_the_generated_file_is_git_ignored():
    done = subprocess.run(["git", "check-ignore", ".env.dev"], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, "add .env.dev to .gitignore"
