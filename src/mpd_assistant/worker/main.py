"""Background worker: `python -m mpd_assistant.worker.main` loops forever; `--once <job>` runs a single job and exits.

Jobs are idempotent, so a crash or a second replica running the same job is harmless. A Redis lock keeps two
replicas from doing the same work at the same time.
"""

import argparse
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from mpd_assistant.core.config import get_settings
from mpd_assistant.core.db import check_engine, ensure_tenant, make_engine
from mpd_assistant.core.kv import KeyValueStore, MemoryKV, RedisKV
from mpd_assistant.core.llm.factory import build_llm
from mpd_assistant.core.logging import configure_logging
from mpd_assistant.ingestion.indexer import index_directory
from mpd_assistant.memory.consolidation import Consolidator
from mpd_assistant.memory.long_term.sql import SqlMemoryRepository
from mpd_assistant.memory.long_term.store import MemoryStore
from mpd_assistant.multimodal.ocr import build_ocr
from mpd_assistant.retrieval.embeddings import build_embedder
from mpd_assistant.worker.jobs.retention import purge_conversations

logger = logging.getLogger("mpd.worker")


@dataclass
class Job:
    name: str
    every_seconds: int
    run: Callable[[], Awaitable[object]]


def _kv(url: str) -> KeyValueStore:
    try:
        import redis

        client = redis.Redis.from_url(url, socket_timeout=2.0, socket_connect_timeout=2.0, health_check_interval=30)
        client.ping()
        return RedisKV(client)
    except Exception:
        logger.warning("Redis unavailable; job locks are process-local")
        return MemoryKV()


def build_jobs() -> Dict[str, Job]:
    s = get_settings()
    engine = make_engine(s.DATABASE_URL, statement_timeout_ms=300000)  # jobs may run long statements; five minutes at most
    if not check_engine(engine):
        raise SystemExit("Database is unreachable")
    tenant = ensure_tenant(engine)
    jobs: Dict[str, Job] = {}

    async def retention():
        return purge_conversations(engine, user_days=s.CONVERSATION_RETENTION_DAYS, guest_days=s.GUEST_RETENTION_DAYS)

    jobs["retention"] = Job("retention", 24 * 3600, retention)

    llm = build_llm(s)
    store = MemoryStore(repo=SqlMemoryRepository(engine))

    from mpd_assistant.identity.sql import SqlUserRepository

    users = SqlUserRepository(engine, tenant)

    async def consolidate():
        return await Consolidator(store, llm, users.memory_consent, time.time).run()

    jobs["consolidate"] = Job("consolidate", 24 * 3600, consolidate)

    embedder = build_embedder(s)
    if embedder is not None:

        async def reindex():
            return await index_directory(engine, tenant, Path(s.KNOWLEDGE_BASE_PATH), embedder, ocr=build_ocr(s))

        jobs["reindex"] = Job("reindex", 6 * 3600, reindex)
    return jobs


async def run_job(job: Job, kv: KeyValueStore) -> None:
    lock = f"joblock:{job.name}"
    if kv.incr(lock, max(60, job.every_seconds // 2)) > 1:
        return  # another replica ran it within this window
    started = time.perf_counter()
    try:
        result = await job.run()
        logger.info("job %s finished in %.1fs: %s", job.name, time.perf_counter() - started, result)
    except Exception:
        logger.exception("job %s failed", job.name)
        kv.delete(lock)  # let the next tick retry


async def loop(jobs: Dict[str, Job], kv: KeyValueStore, tick: int = 60) -> None:
    next_run: Dict[str, float] = {name: 0.0 for name in jobs}
    while True:
        now = time.time()
        for name, job in jobs.items():
            if now >= next_run[name]:
                next_run[name] = now + job.every_seconds
                await run_job(job, kv)
        await asyncio.sleep(tick)


def main(argv: List[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", metavar="JOB", help="run one job and exit (retention, consolidate, reindex)")
    args = parser.parse_args(argv)
    s = get_settings()
    configure_logging(s.LOG_LEVEL)
    jobs = build_jobs()
    if args.once:
        if args.once not in jobs:
            raise SystemExit(f"Unknown or unavailable job: {args.once}. Available: {', '.join(jobs)}")
        asyncio.run(jobs[args.once].run())
        return
    asyncio.run(loop(jobs, _kv(s.REDIS_URL)))


if __name__ == "__main__":
    main()
