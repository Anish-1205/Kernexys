from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import ConnectionError

from app.async_queue import AsyncQueueError, RedisInferenceQueue


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
async def test_recover_processing_requeues_existing_jobs_and_drops_expired_ids() -> None:
    redis = AsyncMock()
    redis.set.return_value = True
    redis.lmove.side_effect = ["existing", "expired", None]
    redis.exists.side_effect = [1, 0]
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    recovered = await queue.recover_processing()

    assert recovered == 1
    redis.hset.assert_awaited_once()
    redis.lrem.assert_awaited_once()


@pytest.mark.anyio
async def test_recovery_lease_prevents_scale_out_from_requeuing_active_work() -> None:
    redis = AsyncMock()
    redis.set.return_value = False
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    assert await queue.recover_processing() == 0
    redis.lmove.assert_not_awaited()


@pytest.mark.anyio
async def test_finish_atomically_persists_result_expiry_and_acknowledgement() -> None:
    redis = MagicMock()
    pipeline = Pipeline()
    redis.pipeline.return_value = pipeline
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    await queue.finish("job-1", "succeeded", result={"label": "positive"})

    assert [name for name, _args in pipeline.calls] == ["hset", "expire", "lrem"]
