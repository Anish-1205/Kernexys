"""Redis-backed asynchronous inference worker."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

import aiohttp

from app.async_queue import AsyncQueueError, ClaimedJob, RedisInferenceQueue
from app.config import Settings
from app.logging_config import configure_logging

logger = logging.getLogger("kernexys.worker")


async def process_job(
    queue: RedisInferenceQueue,
    session: aiohttp.ClientSession,
    job: ClaimedJob,
) -> None:
    try:
        async with session.post(
            job.payload["endpoint"].rstrip("/") + "/v1/infer",
            json={"text": job.payload["text"]},
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"runtime returned HTTP {response.status}")
            result: dict[str, Any] = await response.json()
        await queue.finish(job.job_id, "succeeded", result=result)
    except (TimeoutError, aiohttp.ClientError, RuntimeError, KeyError, ValueError) as exc:
        logger.warning("async_inference_failed", extra={"job_id": job.job_id, "error": str(exc)})
        await queue.finish(job.job_id, "failed", error="The model runtime request failed.")


async def consume(
    queue: RedisInferenceQueue,
    session: aiohttp.ClientSession,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        try:
            job = await queue.claim()
            if job is not None:
                await process_job(queue, session, job)
        except AsyncQueueError:
            logger.exception("queue_operation_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass


async def recover_periodically(
    queue: RedisInferenceQueue,
    stop: asyncio.Event,
    interval_seconds: float,
) -> None:
    """Re-run processing-list recovery once per recovery-lease interval.

    Startup-only recovery strands a crashed worker's in-flight job whenever the
    recovery lease is still held by a worker that has since departed: the
    restarted worker's single attempt returns 0 and it never looks again. Re-
    running the sweep lets some worker reclaim such jobs once the lease lapses.
    ``recover_processing`` still gates each sweep on a Redis ``SET NX EX`` lease,
    so at most one worker sweeps the processing list per interval.
    """
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
        else:
            return
        try:
            recovered = await queue.recover_processing()
        except AsyncQueueError:
            logger.exception("recovery_sweep_failed")
            continue
        if recovered:
            logger.info("async_jobs_recovered", extra={"recovered_jobs": recovered})


async def run_worker(settings: Settings, stop: asyncio.Event) -> None:
    recovery_lease_seconds = max(settings.async_inference_timeout_seconds * 2, 30)
    queue = RedisInferenceQueue.create(
        settings.redis_url,
        settings.async_queue_capacity,
        settings.async_job_ttl_seconds,
        settings.redis_socket_timeout_seconds,
        recovery_lease_seconds,
    )
    timeout = aiohttp.ClientTimeout(total=settings.async_inference_timeout_seconds)
    try:
        recovered = await queue.recover_processing()
        logger.info("worker_started", extra={"recovered_jobs": recovered})
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(recover_periodically(queue, stop, recovery_lease_seconds))
                for _ in range(settings.async_worker_concurrency):
                    tasks.create_task(consume(queue, session, stop))
    finally:
        await queue.close()


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)

    async def runner() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda _signum, _frame: loop.call_soon_threadsafe(stop.set))
        await run_worker(settings, stop)

    asyncio.run(runner())


if __name__ == "__main__":  # pragma: no cover
    main()
