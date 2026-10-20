"""A short set of requests against a running API: is it up, does a conversation work, are the doors that should be shut shut.

    python scripts/smoke_test.py http://localhost:8000
    python scripts/smoke_test.py https://api.example.com --metrics-token "$METRICS_TOKEN" \\
        --tool calendar=http://localhost:8001 --tool gmail=http://localhost:8002

Exit code 0 when every check passes, 1 otherwise. It sends no real customer data and creates only anonymous visitor
sessions, so it is safe to run after every deploy.
"""

import argparse
import sys
from dataclasses import dataclass
from typing import Callable, Dict, List

import httpx


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""


def _check(results: List[Result], name: str, fn: Callable[[], str | None]) -> None:
    """fn returns None on success or a short reason on failure; raising counts as a failure."""
    try:
        problem = fn()
    except Exception as exc:  # a network error or a malformed body is a failed check, not a crash
        problem = f"{type(exc).__name__}: {exc}"[:200]
    results.append(Result(name, problem is None, problem or ""))


def run_checks(client: httpx.Client, metrics_token: str | None = None, tools: Dict[str, str] | None = None) -> List[Result]:
    results: List[Result] = []
    state: Dict[str, str] = {}

    def health() -> str | None:
        r = client.get("/health")
        return None if r.status_code == 200 and r.json() == {"status": "ok"} else f"status {r.status_code}: {r.text[:80]}"

    def headers() -> str | None:
        r = client.get("/health")
        missing = [h for h in ("x-content-type-options", "content-security-policy", "referrer-policy") if h not in r.headers]
        return None if not missing else "missing " + ", ".join(missing)

    def session() -> str | None:
        r = client.post("/v2/session")
        if r.status_code != 201 or not r.json().get("session_id"):
            return f"status {r.status_code}"
        state["sid"] = r.json()["session_id"]
        return None

    def chat(message: str, expect_words: int = 1) -> Callable[[], str | None]:
        def run() -> str | None:
            r = client.post("/v2/chat", json={"message": message, "session_id": state.get("sid", "")})
            if r.status_code != 200:
                return f"status {r.status_code}: {r.text[:80]}"
            reply = r.json().get("reply", "")
            if len(reply.split()) < expect_words:
                return "empty reply"
            if "Traceback" in reply or "Exception" in reply:
                return "reply leaks an error"
            return None

        return run

    def shut(method: str, path: str, allowed: tuple, **kw) -> Callable[[], str | None]:
        def run() -> str | None:
            r = client.request(method, path, **kw)
            return None if r.status_code in allowed else f"expected {allowed}, got {r.status_code}"

        return run

    _check(results, "health endpoint", health)
    _check(results, "security headers", headers)
    _check(results, "visitor session", session)
    _check(results, "greeting reply", chat("hi"))
    _check(results, "question reply", chat("What services does MasterProDev offer?", expect_words=3))
    _check(results, "staff routes refuse anonymous callers", shut("GET", "/v2/admin/overview", (401, 404)))
    _check(results, "metrics refuse anonymous callers", shut("GET", "/metrics", (401, 404)))
    _check(results, "unsigned Stripe webhook is refused", shut("POST", "/v2/webhooks/stripe", (400, 404), content=b"{}"))
    _check(results, "unsigned Twilio webhook is refused", shut("POST", "/v2/channels/twilio", (403, 404), data={"From": "+14165550123", "Body": "hi"}))
    _check(results, "account export needs a verified session", shut("GET", "/v2/account/export", (403, 422), params={"session_id": state.get("sid", "x")}))
    _check(results, "interactive docs are not exposed", shut("GET", "/docs", (404,)))

    if metrics_token:
        def metrics() -> str | None:
            r = client.get("/metrics", headers={"Authorization": f"Bearer {metrics_token}"})
            if r.status_code != 200:
                return f"status {r.status_code}"
            return None if "mpd_turns_total" in r.text else "mpd_turns_total is missing"

        _check(results, "metrics with the token", metrics)

    for name, base in (tools or {}).items():
        def tool_health(base: str = base) -> str | None:
            r = httpx.get(base.rstrip("/") + "/health", timeout=10)
            return None if r.status_code == 200 else f"status {r.status_code}"

        def tool_closed(base: str = base) -> str | None:
            r = httpx.post(base.rstrip("/") + "/tools", timeout=10)
            return None if r.status_code in (401, 503) else f"an unauthenticated call got {r.status_code}"

        _check(results, f"{name} service is healthy", tool_health)
        _check(results, f"{name} service refuses calls without the service key", tool_closed)
    return results


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base_url", help="for example http://localhost:8000")
    parser.add_argument("--metrics-token", help="also check /metrics with this token")
    parser.add_argument("--tool", action="append", default=[], metavar="NAME=URL", help="also check a tool service; repeatable")
    args = parser.parse_args(argv)
    tools = dict(item.split("=", 1) for item in args.tool if "=" in item)
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        results = run_checks(client, args.metrics_token, tools)
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"{'PASS' if r.ok else 'FAIL'}  {r.name.ljust(width)}  {r.detail}")
    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
