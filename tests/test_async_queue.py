from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import ConnectionError

from app.async_queue import (
    JOB_PREFIX,
    PROCESSING_KEY,
    QUEUE_KEY,
    AsyncQueueError,
    RedisInferenceQueue,
)


class Pipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def __aenter__(self) -> Pipeline:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def hset(self, *args: object, **_kwargs: object) -> Pipeline:
        self.calls.append(("hset", args))
        return self

    def expire(self, *args: object) -> Pipeline:
        self.calls.append(("expire", args))
        return self

    def lrem(self, *args: object) -> Pipeline:
        self.calls.append(("lrem", args))
        return self

    async def execute(self) -> list[int]:
        return [1, 1, 1]


@pytest.mark.anyio
async def test_enqueue_maps_atomic_script_results() -> None:
    redis = AsyncMock()
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)
    redis.eval.side_effect = [1, 0, -1, -2]

    created = await queue.enqueue("job-1", {"text": "hello"})
    repeated = await queue.enqueue("job-1", {"text": "hello"})
    full = await queue.enqueue("job-2", {"text": "hello"})
    conflict = await queue.enqueue("job-1", {"text": "different"})

    assert created.created and not created.full
    assert not repeated.created and not repeated.full
    assert full.full and not full.created
    assert conflict.conflict and not conflict.created
    assert redis.eval.await_count == 4


@pytest.mark.anyio
async def test_redis_failure_is_sanitized() -> None:
    redis = AsyncMock()
    redis.ping.side_effect = ConnectionError("redis.internal:6379 secret")
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    with pytest.raises(AsyncQueueError, match="Redis is unavailable"):
        await queue.check_ready()


@pytest.mark.anyio
async def test_claim_moves_job_to_processing_and_marks_running() -> None:
    redis = AsyncMock()
    redis.blmove.return_value = "job-1"
    redis.hgetall.return_value = {"status": "queued", "payload": '{"text":"hello"}'}
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    claimed = await queue.claim()

    assert claimed is not None
    assert claimed.job_id == "job-1"
    assert claimed.payload == {"text": "hello"}
    redis.hset.assert_awaited_once()


@pytest.mark.anyio
async def test_recover_processing_runs_one_atomic_scan_under_the_lease() -> None:
    redis = AsyncMock()
    redis.set.return_value = True
    redis.eval.return_value = 2
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60, recovery_lock_seconds=30)

    recovered = await queue.recover_processing()

    assert recovered == 2
    redis.set.assert_awaited_once()
    assert redis.set.await_args.kwargs == {"nx": True, "ex": 30}
    redis.eval.assert_awaited_once()
    _script, numkeys, processing, queue_key, prefix, stranded_before, now = (
        redis.eval.await_args.args
    )
    assert (numkeys, processing, queue_key, prefix) == (
        2,
        PROCESSING_KEY,
        QUEUE_KEY,
        JOB_PREFIX,
    )
    assert float(now) - float(stranded_before) == pytest.approx(30)
    # the scan itself never issues piecemeal list/hash writes from Python
    redis.lrange.assert_not_awaited()
    redis.lrem.assert_not_awaited()
    redis.hset.assert_not_awaited()
    redis.rpush.assert_not_awaited()


@pytest.mark.anyio
async def test_recovery_lease_prevents_scale_out_from_requeuing_active_work() -> None:
    redis = AsyncMock()
    redis.set.return_value = False
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    assert await queue.recover_processing() == 0
    redis.eval.assert_not_awaited()


@pytest.mark.anyio
async def test_recover_processing_sanitizes_redis_failure() -> None:
    redis = AsyncMock()
    redis.set.return_value = True
    redis.eval.side_effect = ConnectionError("redis.internal:6379 secret")
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    with pytest.raises(AsyncQueueError, match="Redis is unavailable"):
        await queue.recover_processing()


@pytest.mark.anyio
async def test_finish_atomically_persists_result_expiry_and_acknowledgement() -> None:
    redis = MagicMock()
    pipeline = Pipeline()
    redis.pipeline.return_value = pipeline
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    await queue.finish("job-1", "succeeded", result={"label": "positive"})

    assert [name for name, _args in pipeline.calls] == ["hset", "expire", "lrem"]
