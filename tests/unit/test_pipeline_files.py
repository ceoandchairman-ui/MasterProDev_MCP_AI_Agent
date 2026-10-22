"""CI, deploy and Railway configuration: the pieces that have to agree for a deploy to migrate, start and verify itself."""

import importlib.util
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
DEPLOY = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8"))

spec = importlib.util.spec_from_file_location("check_railway_topology", ROOT / "scripts" / "check_railway_topology.py")
topology = importlib.util.module_from_spec(spec)
spec.loader.exec_module(topology)


def step_text(job):
    return "\n".join(str(s.get("run", "")) + " " + str(s.get("name", "")) for s in job["steps"])


# --- CI -----------------------------------------------------------------------------------
def test_ci_has_the_expected_jobs_and_the_live_job_runs_after_the_unit_tests():
    assert set(CI["jobs"]) == {"secrets", "test", "live", "eval"}
    assert CI["jobs"]["live"]["needs"] == "test"


def test_the_live_job_uses_the_same_images_as_the_local_stack_and_does_not_block_yet():
    live = CI["jobs"]["live"]
    local = yaml.safe_load((ROOT / "deploy" / "compose.dev.yml").read_text(encoding="utf-8"))["services"]
    assert live["services"]["postgres"]["image"] == local["postgres"]["image"]  # pgvector, not plain Postgres
    assert live["services"]["redis"]["image"] == local["redis"]["image"]  # Redis Stack, not plain Redis
    assert live["continue-on-error"] is True  # until the tests have passed once against real services
    assert "tests/integration/test_live_stack.py -m live" in step_text(live)
    assert live["env"]["INTEGRATION_DATABASE_URL"].startswith("postgresql://mpd:mpd@localhost")


def test_the_unit_test_job_does_not_collect_the_live_tests():
    assert "tests/unit tests/privacy" in step_text(CI["jobs"]["test"]) and "integration" not in step_text(CI["jobs"]["test"])


# --- deploy ---------------------------------------------------------------------------------
def test_deploy_no_longer_migrates_from_the_runner_and_runs_the_full_smoke_checks():
    job = DEPLOY["jobs"]["deploy"]
    runs = [str(s.get("run", "")) for s in job["steps"]]
    assert not any("alembic" in r for r in runs)  # the runner cannot reach Railway's private Postgres address
    assert any("railway up --service api" in r for r in runs)
    assert any("scripts/smoke_test.py" in r for r in runs)
    order = [i for i, r in enumerate(runs) if "railway up" in r or "smoke_test.py" in r]
    assert order == sorted(order) and len(order) == 2  # deploy first, then verify


def test_the_smoke_script_the_deploy_calls_needs_only_httpx():
    source = (ROOT / "scripts" / "smoke_test.py").read_text(encoding="utf-8")
    assert "mpd_assistant" not in source  # so the workflow can run it with a bare `pip install httpx`


# --- Railway ----------------------------------------------------------------------------------
def test_the_api_migrates_before_it_takes_traffic():
    import tomllib

    deploy = tomllib.loads((ROOT / "deploy" / "railway" / "api.toml").read_text(encoding="utf-8"))["deploy"]
    assert deploy["preDeployCommand"] == ["alembic upgrade head"] and deploy["healthcheckPath"] == "/health"
    image = (ROOT / "deploy" / "dockerfiles" / "api.Dockerfile").read_text(encoding="utf-8")
    assert "COPY alembic.ini" in image and "COPY migrations" in image  # the command can only run if the image carries them


def test_the_repository_passes_its_own_topology_check():
    assert topology.check() == []


def test_the_checker_rejects_an_api_that_does_not_migrate(tmp_path, monkeypatch):
    copy = tmp_path / "railway"
    shutil.copytree(ROOT / "deploy" / "railway", copy)
    api = copy / "api.toml"
    api.write_text(api.read_text(encoding="utf-8").replace('preDeployCommand = ["alembic upgrade head"]', ""), encoding="utf-8")
    monkeypatch.setattr(topology, "RAILWAY_DIR", copy)
    errors = topology.check()
    assert any("preDeployCommand" in e for e in errors)


def test_the_checker_still_rejects_keys_railway_does_not_support(tmp_path, monkeypatch):
    copy = tmp_path / "railway"
    shutil.copytree(ROOT / "deploy" / "railway", copy)
    worker = copy / "worker.toml"
    worker.write_text(worker.read_text(encoding="utf-8").replace("[deploy]", "[deploy]\nmemoryMB = 512"), encoding="utf-8")
    monkeypatch.setattr(topology, "RAILWAY_DIR", copy)
    assert any("unsupported deploy keys" in e and "memoryMB" in e for e in topology.check())
