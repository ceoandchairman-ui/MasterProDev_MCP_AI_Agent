"""Load test for the chat endpoint. Reports latency percentiles per message type and the error and rate-limit share.

  python scripts/load_test.py --url https://api.example.com --concurrency 50 --requests 500

Targets (NFR-03): templated replies p95 under 0.3 s; knowledge answers p95 under 15 s. Each simulated visitor keeps one
session, so memory growth and per-session state are exercised too. Point it at a test deployment, not at production
traffic you care about: it spends real model tokens on the knowledge questions.

Note the API limits each client IP (EDGE_REQUESTS_PER_MINUTE); load from one machine will see 429s unless the limit is
raised for the test. 429s are counted separately from errors.
"""

import argparse
import asyncio
import itertools
import random
import statistics
import time
from collections import defaultdict
from typing import Dict, List

import httpx

MESSAGES = {
    "templated": ["hello", "hi there", "what services do you offer"],
    "knowledge": [
        "Do you build mobile apps for logistics companies?",
        "What cloud platforms do you work with?",
        "How does your discovery process work?",
        "Can you help us move an on-premise system to the cloud?",
    ],
}
P95_TARGET_SECONDS = {"templated": 0.3, "knowledge": 15.0}


def percentile(values: List[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else 0.0


async def visitor(client: httpx.AsyncClient, base: str, jobs: "asyncio.Queue", results: Dict[str, List[float]], counts: Dict[str, int]) -> None:
    session_id = None
    while True:
        try:
            kind, message = jobs.get_nowait()
        except asyncio.QueueEmpty:
            return
        started = time.perf_counter()
        try:
            resp = await client.post(f"{base}/v2/chat", json={"message": message, "session_id": session_id}, timeout=60.0)
        except httpx.HTTPError:
            counts["error"] += 1
            continue
        elapsed = time.perf_counter() - started
        if resp.status_code == 429:
            counts["rate_limited"] += 1
        elif resp.status_code != 200:
            counts["error"] += 1
        else:
            counts["ok"] += 1
            session_id = resp.json().get("session_id", session_id)
            results[kind].append(elapsed)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--knowledge-share", type=float, default=0.4, help="share of messages that need the model")
    args = parser.parse_args()

    pools = {k: itertools.cycle(v) for k, v in MESSAGES.items()}
    jobs: asyncio.Queue = asyncio.Queue()
    for _ in range(args.requests):
        kind = "knowledge" if random.random() < args.knowledge_share else "templated"
        jobs.put_nowait((kind, next(pools[kind])))

    results: Dict[str, List[float]] = defaultdict(list)
    counts: Dict[str, int] = defaultdict(int)
    started = time.perf_counter()
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=args.concurrency)) as client:
        await asyncio.gather(*[visitor(client, args.url.rstrip("/"), jobs, results, counts) for _ in range(args.concurrency)])
    wall = time.perf_counter() - started

    failed = False
    print(f"{args.requests} requests, concurrency {args.concurrency}, {wall:.1f}s, {args.requests / wall:.1f} req/s")
    print(f"ok={counts['ok']} rate_limited={counts['rate_limited']} errors={counts['error']}")
    for kind, values in sorted(results.items()):
        p95 = percentile(values, 0.95)
        target = P95_TARGET_SECONDS[kind]
        verdict = "ok" if p95 <= target else "OVER TARGET"
        failed |= p95 > target
        print(f"{kind:10} n={len(values):4} p50={statistics.median(values):6.2f}s p95={p95:6.2f}s p99={percentile(values, 0.99):6.2f}s  target p95<={target}s  {verdict}")
    if counts["error"] > 0.01 * args.requests:
        print("ERROR RATE ABOVE 1%")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
