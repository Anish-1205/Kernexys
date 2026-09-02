"""Deterministic recovery/claim race tests against a real Redis.

Set ``KERNEXYS_TEST_REDIS_URL`` (e.g. ``redis://localhost:6379/15``) to run
these; the target database is flushed around every test. The recovery sweep is
a single atomic Redis script, so exercising each sequential ordering of a sweep
against ``finish``/``claim`` covers every possible interleaving.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis

from app.async_queue import (
    JOB_PREFIX,
    PROCESSING_KEY,
    QUEUE_KEY,
    RECOVERY_LOCK_KEY,
    RedisInferenceQueue,
)

pytestmark = pytest.mark.integration

LEASE = 60
PAYLOAD = {"deployment": "default/sentiment", "endpoint": "http://runtime", "text": "hi"}


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    url = os.getenv("KERNEXYS_TEST_REDIS_URL")
    if not url:
        pytest.skip("KERNEXYS_TEST_REDIS_URL is set by make redis-integration")
    client: Redis = Redis.from_url(url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        pytest.skip(f"Redis unavailable at {url}: {exc}")
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest.fixture
def queue(redis_client: Redis) -> RedisInferenceQueue:
    return RedisInferenceQueue(
        redis_client, capacity=100, job_ttl_seconds=600, recovery_lock_seconds=LEASE
    )


async def _seed_running_claim(redis_client: Redis, queue: RedisInferenceQueue, job_id: str) -> None:
    """Enqueue ``job_id`` and take a real claim for it."""
    assert (await queue.enqueue(job_id, PAYLOAD)).created
    claimed = await queue.claim(timeout_seconds=1)
    assert claimed is not None and claimed.job_id == job_id


async def _backdate_claim(redis_client: Redis, job_id: str, age_seconds: float = 10_000) -> None:
    await redis_client.hset(JOB_PREFIX + job_id, "claimed_at", repr(time.time() - age_seconds))


async def _sweep_again(redis_client: Redis, queue: RedisInferenceQueue) -> int:
    """Run a recovery sweep, ignoring the once-per-lease lock from a prior call."""
    await redis_client.delete(RECOVERY_LOCK_KEY)
    return await queue.recover_processing()


@pytest.mark.anyio
async def test_finish_just_before_sweep_is_not_resurrected(
    redis_client: Redis, queue: RedisInferenceQueue
) -> None:
    await _seed_running_claim(redis_client, queue, "job-a")
    await _backdate_claim(redis_client, "job-a")

    await queue.finish("job-a", "failed", error="sanitized")
    recovered = await queue.recover_processing()

    assert recovered == 0
    assert await redis_client.hget(JOB_PREFIX + "job-a", "status") == "failed"
    assert await redis_client.lrange(QUEUE_KEY, 0, -1) == []
    assert await redis_client.lrange(PROCESSING_KEY, 0, -1) == []


@pytest.mark.anyio
async def test_requeue_then_late_finish_settles_terminal_without_reexecution(
    redis_client: Redis, queue: RedisInferenceQueue
) -> None:
    await _seed_running_claim(redis_client, queue, "job-b")
    await _backdate_claim(redis_client, "job-b")

    assert await queue.recover_processing() == 1
    assert await redis_client.lrange(QUEUE_KEY, 0, -1) == ["job-b"]
    assert await redis_client.hget(JOB_PREFIX + "job-b", "status") == "queued"
    assert not await redis_client.hexists(JOB_PREFIX + "job-b", "claimed_at")

    # the departed worker's finish() lands late, after the requeue
    await queue.finish("job-b", "succeeded", result={"label": "positive"})

    # the next claim must not re-run a terminal job
    assert await queue.claim(timeout_seconds=1) is None
    record = await redis_client.hgetall(JOB_PREFIX + "job-b")
    assert record["status"] == "succeeded"
    assert json.loads(record["result"]) == {"label": "positive"}
    assert await redis_client.lrange(PROCESSING_KEY, 0, -1) == []
    assert await redis_client.lrange(QUEUE_KEY, 0, -1) == []


@pytest.mark.anyio
async def test_claim_interrupted_before_stamp_is_grace_stamped_not_requeued(
    redis_client: Redis, queue: RedisInferenceQueue
) -> None:
    assert (await queue.enqueue("job-c", PAYLOAD)).created
    # BLMOVE happened, the process died before claim() wrote status/claimed_at
    moved = await redis_client.lmove(QUEUE_KEY, PROCESSING_KEY, "LEFT", "RIGHT")
    assert moved == "job-c"
    assert await redis_client.hget(JOB_PREFIX + "job-c", "status") == "queued"
    assert not await redis_client.hexists(JOB_PREFIX + "job-c", "claimed_at")

    recovered = await queue.recover_processing()

    assert recovered == 0
    assert await redis_client.lrange(PROCESSING_KEY, 0, -1) == ["job-c"]
    assert await redis_client.lrange(QUEUE_KEY, 0, -1) == []
    assert await redis_client.hexists(JOB_PREFIX + "job-c", "claimed_at")


@pytest.mark.anyio
async def test_grace_stamped_entry_recovered_once_the_stamp_ages(
    redis_client: Redis, queue: RedisInferenceQueue
) -> None:
    assert (await queue.enqueue("job-d", PAYLOAD)).created
    await redis_client.lmove(QUEUE_KEY, PROCESSING_KEY, "LEFT", "RIGHT")

    assert await queue.recover_processing() == 0  # first sweep only stamps
    await _backdate_claim(redis_client, "job-d")  # stamp ages past the lease

    assert await _sweep_again(redis_client, queue) == 1
    assert await redis_client.lrange(QUEUE_KEY, 0, -1) == ["job-d"]
    assert await redis_client.hget(JOB_PREFIX + "job-d", "status") == "queued"
    assert await redis_client.lrange(PROCESSING_KEY, 0, -1) == []


@pytest.mark.anyio
async def test_fresh_claim_racing_a_sweep_is_never_requeued(
    redis_client: Redis, queue: RedisInferenceQueue
) -> None:
    assert (await queue.enqueue("job-e", PAYLOAD)).created
    # a live worker's BLMOVE, mid-claim, one instruction before the stamp
    await redis_client.lmove(QUEUE_KEY, PROCESSING_KEY, "LEFT", "RIGHT")

    assert await queue.recover_processing() == 0  # sweep only grace-stamps

    # the worker now completes the claim it was in the middle of
    await redis_client.hset(
        JOB_PREFIX + "job-e", mapping={"status": "running", "claimed_at": repr(time.time())}
    )
    assert await _sweep_again(redis_client, queue) == 0  # claim is now young

    await queue.finish("job-e", "succeeded", result={"label": "negative"})
    assert await redis_client.lrange(QUEUE_KEY, 0, -1) == []  # never duplicated onto the queue
    assert await redis_client.lrange(PROCESSING_KEY, 0, -1) == []


@pytest.mark.anyio
async def test_stranded_running_job_is_recovered(
    redis_client: Redis, queue: RedisInferenceQueue
) -> None:
    await _seed_running_claim(redis_client, queue, "job-f")
    await _backdate_claim(redis_client, "job-f")  # worker vanished mid-request

    assert await queue.recover_processing() == 1
    assert await redis_client.lrange(QUEUE_KEY, 0, -1) == ["job-f"]
    assert await redis_client.hget(JOB_PREFIX + "job-f", "status") == "queued"
    assert not await redis_client.hexists(JOB_PREFIX + "job-f", "claimed_at")
    assert await redis_client.lrange(PROCESSING_KEY, 0, -1) == []

    # a recovered job is claimable again -> at least once
    assert (await queue.claim(timeout_seconds=1)).job_id == "job-f"


@pytest.mark.anyio
async def test_expired_record_is_unlinked_from_processing(
    redis_client: Redis, queue: RedisInferenceQueue
) -> None:
    await redis_client.rpush(PROCESSING_KEY, "ghost")  # job hash already TTL'd away

    assert await queue.recover_processing() == 0
    assert await redis_client.lrange(PROCESSING_KEY, 0, -1) == []
    assert await redis_client.lrange(QUEUE_KEY, 0, -1) == []


@pytest.mark.anyio
async def test_happy_path_lifecycle(redis_client: Redis, queue: RedisInferenceQueue) -> None:
    assert (await queue.enqueue("job-g", PAYLOAD)).created
    claimed = await queue.claim(timeout_seconds=1)
    assert claimed is not None and claimed.payload == PAYLOAD
    await queue.finish("job-g", "succeeded", result={"label": "positive"})

    record = await queue.get("job-g")
    assert record is not None and record["status"] == "succeeded"
    assert 0 < await redis_client.ttl(JOB_PREFIX + "job-g") <= 600
    assert await redis_client.lrange(PROCESSING_KEY, 0, -1) == []
    assert await redis_client.lrange(QUEUE_KEY, 0, -1) == []
