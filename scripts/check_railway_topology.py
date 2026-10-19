"""Checks deploy/railway against topology.yaml and edge.yaml. Exits non-zero on any mismatch."""

import sys
import tomllib
from pathlib import Path

import yaml

RAILWAY_DIR = Path(__file__).resolve().parent.parent / "deploy" / "railway"
ALLOWED_TOP = {"build", "deploy"}
ALLOWED_DEPLOY = {"healthcheckPath", "healthcheckTimeout", "restartPolicyType", "restartPolicyMaxRetries", "numReplicas"}
REQUIRED_VOLUMES = {"postgres", "redis-state", "weaviate", "prometheus", "grafana"}


def check() -> list[str]:
    errors: list[str] = []
    topo = yaml.safe_load((RAILWAY_DIR / "topology.yaml").read_text(encoding="utf-8"))
    edge = yaml.safe_load((RAILWAY_DIR / "edge.yaml").read_text(encoding="utf-8"))
    services: dict = topo["services"]

    public = {n for n, s in services.items() if s.get("public")}
    if public != set(topo["networking"]["public_services"]):
        errors.append(f"public services {sorted(public)} do not match networking.public_services")
    if public - {"api", "grafana"}:
        errors.append(f"only api and grafana may be public, found {sorted(public)}")

    missing_vol = REQUIRED_VOLUMES - {n for n, s in services.items() if "volume" in s}
    if missing_vol:
        errors.append(f"services missing a volume: {sorted(missing_vol)}")

    for name, spec in services.items():
        if "volume" in spec and spec["volume"].get("size_gb", 0) <= 0:
            errors.append(f"{name}: volume size must be positive")
        if "config" not in spec:
            continue
        path = RAILWAY_DIR / spec["config"]
        if not path.exists():
            errors.append(f"{name}: {spec['config']} does not exist")
            continue
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        if set(data) - ALLOWED_TOP:
            errors.append(f"{spec['config']}: unsupported sections {sorted(set(data) - ALLOWED_TOP)}")
        deploy = data.get("deploy", {})
        if set(deploy) - ALLOWED_DEPLOY:
            errors.append(f"{spec['config']}: unsupported deploy keys {sorted(set(deploy) - ALLOWED_DEPLOY)}")
        replicas = deploy.get("numReplicas", 1)
        if "volume" in spec and replicas != 1:
            errors.append(f"{name}: a service with a volume must have one replica")
        if name == "api":
            for env, env_spec in topo["environments"].items():
                if env_spec["api_replicas"] != replicas and env == "production":
                    errors.append(f"api: production api_replicas={env_spec['api_replicas']} but {spec['config']} has numReplicas={replicas}")

    cost = topo["cost"]
    if not cost["monthly_budget_usd"] < cost["hard_limit_usd"]:
        errors.append("cost: hard_limit_usd must exceed monthly_budget_usd")
    if max(cost["usage_alert_usd"]) > cost["hard_limit_usd"]:
        errors.append("cost: a usage alert is above the hard limit")

    api_settings = edge["app_settings"]
    if int(api_settings["TRUSTED_PROXY_HOPS"]) < 1:
        errors.append("edge: TRUSTED_PROXY_HOPS must be at least 1 behind Railway")
    if int(api_settings["EDGE_REQUESTS_PER_MINUTE"]) <= 0:
        errors.append("edge: EDGE_REQUESTS_PER_MINUTE is 0, which turns per-IP limiting off")
    return errors


if __name__ == "__main__":
    problems = check()
    for p in problems:
        print(f"FAIL {p}")
    if not problems:
        print("OK railway topology matches the tomls")
    sys.exit(1 if problems else 0)
