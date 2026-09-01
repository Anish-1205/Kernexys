"""Integration tests for async queue edge cases and error scenarios."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import ConnectionError, TimeoutError as RedisTimeoutError

from app.async_queue import AsyncQueueError, EnqueueResult, RedisInferenceQueue


class Pipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.execute_should_fail = False

    async def __aenter__(self) -> Pipeline:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def hset(self, *args: object, **kwargs: object) -> Pipeline:
        self.calls.append(("hset", args, kwargs))
        return self

    def expire(self, *args: object, **kwargs: object) -> Pipeline:
        self.calls.append(("expire", args, kwargs))
        return self

    def lrem(self, *args: object, **kwargs: object) -> Pipeline:
        self.calls.append(("lrem", args, kwargs))
        return self

    async def execute(self) -> list[int]:
        if self.execute_should_fail:
            raise ConnectionError("connection refused")
        return [1, 1, 1]


@pytest.mark.anyio
async def test_enqueue_raises_async_queue_error_on_redis_failure() -> None:
    redis = AsyncMock()
    redis.eval.side_effect = ConnectionError("connection refused")
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    with pytest.raises(AsyncQueueError, match="Redis is unavailable"):
        await queue.enqueue("job-1", {"text": "hello"})


@pytest.mark.anyio
async def test_get_returns_none_for_nonexistent_job() -> None:
    redis = AsyncMock()
    redis.hgetall.return_value = {}
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    result = await queue.get("nonexistent")

    assert result is None


@pytest.mark.anyio
async def test_get_returns_job_data_when_exists() -> None:
    redis = AsyncMock()
    redis.hgetall.return_value = {"status": "succeeded", "result": '{"label":"positive"}'}
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    result = await queue.get("job-1")

    assert result == {"status": "succeeded", "result": '{"label":"positive"}'}


@pytest.mark.anyio
async def test_get_raises_async_queue_error_on_redis_failure() -> None:
    redis = AsyncMock()
    redis.hgetall.side_effect = ConnectionError("connection refused")
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    with pytest.raises(AsyncQueueError, match="Redis is unavailable"):
        await queue.get("job-1")


@pytest.mark.anyio
async def test_claim_returns_none_when_no_jobs_available() -> None:
    redis = AsyncMock()
    redis.blmove.return_value = None
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    claimed = await queue.claim()

    assert claimed is None


@pytest.mark.anyio
async def test_claim_skips_already_succeeded_job() -> None:
    redis = AsyncMock()
    redis.blmove.return_value = "job-1"
    redis.hgetall.return_value = {"status": "succeeded", "payload": '{"text":"hello"}'}
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    claimed = await queue.claim()

    assert claimed is None
    redis.lrem.assert_awaited_once()


@pytest.mark.anyio
async def test_claim_skips_already_failed_job() -> None:
    redis = AsyncMock()
    redis.blmove.return_value = "job-1"
    redis.hgetall.return_value = {"status": "failed", "payload": '{"text":"hello"}'}
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    claimed = await queue.claim()

    assert claimed is None
    redis.lrem.assert_awaited_once()


@pytest.mark.anyio
async def test_claim_skips_job_missing_payload() -> None:
    redis = AsyncMock()
    redis.blmove.return_value = "job-1"
    redis.hgetall.return_value = {"status": "queued"}
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    with pytest.raises(AsyncQueueError, match="state is unavailable"):
        await queue.claim()


@pytest.mark.anyio
async def test_claim_handles_invalid_payload_json() -> None:
    redis = AsyncMock()
    redis.blmove.return_value = "job-1"
    redis.hgetall.return_value = {"status": "queued", "payload": "not json"}
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    with pytest.raises(AsyncQueueError, match="state is unavailable"):
        await queue.claim()


@pytest.mark.anyio
async def test_claim_raises_async_queue_error_on_redis_failure() -> None:
    redis = AsyncMock()
    redis.blmove.side_effect = ConnectionError("connection refused")
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    with pytest.raises(AsyncQueueError, match="Redis queue state is unavailable or invalid"):
        await queue.claim()


@pytest.mark.anyio
async def test_finish_persists_success_with_result() -> None:
    redis = MagicMock()
    pipeline = Pipeline()
    redis.pipeline.return_value = pipeline
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    await queue.finish("job-1", "succeeded", result={"label": "positive"})

    assert [name for name, _args, _kwargs in pipeline.calls] == ["hset", "expire", "lrem"]


@pytest.mark.anyio
async def test_finish_persists_failure_with_error() -> None:
    redis = MagicMock()
    pipeline = Pipeline()
    redis.pipeline.return_value = pipeline
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    await queue.finish("job-1", "failed", error="runtime error")

    assert [name for name, _args, _kwargs in pipeline.calls] == ["hset", "expire", "lrem"]


@pytest.mark.anyio
async def test_finish_raises_async_queue_error_on_redis_failure() -> None:
    redis = MagicMock()
    pipeline = Pipeline()
    pipeline.execute_should_fail = True
    redis.pipeline.return_value = pipeline
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    with pytest.raises(AsyncQueueError, match="Redis is unavailable"):
        await queue.finish("job-1", "succeeded", result={"label": "positive"})


@pytest.mark.anyio
async def test_recover_processing_handles_redis_unavailability_on_set() -> None:
    redis = AsyncMock()
    redis.set.side_effect = ConnectionError("connection refused")
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    with pytest.raises(AsyncQueueError, match="Redis is unavailable"):
        await queue.recover_processing()


@pytest.mark.anyio
async def test_recover_processing_handles_redis_unavailability_during_recovery() -> None:
    redis = AsyncMock()
    redis.set.return_value = True
    redis.lmove.side_effect = ConnectionError("connection refused")
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    with pytest.raises(AsyncQueueError, match="Redis is unavailable"):
        await queue.recover_processing()


@pytest.mark.anyio
async def test_recover_processing_with_multiple_pending_jobs() -> None:
    redis = AsyncMock()
    redis.set.return_value = True
    redis.lmove.side_effect = ["job-1", "job-2", None]
    redis.exists.side_effect = [1, 1]
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    recovered = await queue.recover_processing()

    assert recovered == 2


@pytest.mark.anyio
async def test_recover_processing_handles_partial_job_loss() -> None:
    redis = AsyncMock()
    redis.set.return_value = True
    redis.lmove.side_effect = ["job-1", "job-2", "job-3", None]
    redis.exists.side_effect = [1, 0, 1]
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    recovered = await queue.recover_processing()

    assert recovered == 2
    redis.lrem.assert_awaited_once()


@pytest.mark.anyio
async def test_close_closes_redis_connection() -> None:
    redis = AsyncMock()
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    await queue.close()

    redis.aclose.assert_awaited_once()


@pytest.mark.anyio
async def test_check_ready_pings_redis() -> None:
    redis = AsyncMock()
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    await queue.check_ready()

    redis.ping.assert_awaited_once()


@pytest.mark.anyio
async def test_enqueue_result_created_flag() -> None:
    result = EnqueueResult(created=True, full=False)
    assert result.created
    assert not result.full
    assert not result.conflict


@pytest.mark.anyio
async def test_enqueue_result_full_flag() -> None:
    result = EnqueueResult(created=False, full=True)
    assert not result.created
    assert result.full
    assert not result.conflict


@pytest.mark.anyio
async def test_enqueue_result_conflict_flag() -> None:
    result = EnqueueResult(created=False, full=False, conflict=True)
    assert not result.created
    assert not result.full
    assert result.conflict


@pytest.mark.anyio
async def test_recovery_lease_duration_configuration() -> None:
    redis = AsyncMock()
    redis.set.return_value = True
    redis.lmove.return_value = None
    queue = RedisInferenceQueue(
        redis, capacity=10, job_ttl_seconds=60, recovery_lock_seconds=120
    )

    await queue.recover_processing()

    call_kwargs = redis.set.await_args[1]
    assert call_kwargs.get("ex") == 120


@pytest.mark.anyio
async def test_claim_timeout_configuration() -> None:
    redis = AsyncMock()
    redis.blmove.return_value = None
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    await queue.claim(timeout_seconds=5)

    call_args = redis.blmove.await_args[0]
    assert call_args[2] == 5


@pytest.mark.anyio
async def test_claim_default_timeout() -> None:
    redis = AsyncMock()
    redis.blmove.return_value = None
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    await queue.claim()

    call_args = redis.blmove.await_args[0]
    assert call_args[2] == 2


@pytest.mark.anyio
async def test_finish_includes_result_in_mapping_when_provided() -> None:
    redis = MagicMock()
    pipeline = Pipeline()
    redis.pipeline.return_value = pipeline
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    await queue.finish("job-1", "succeeded", result={"label": "positive"})

    assert len(pipeline.calls) > 0
    hset_calls = [c for c in pipeline.calls if c[0] == "hset"]
    assert len(hset_calls) > 0
    mapping = hset_calls[0][2].get("mapping", {})
    assert "result" in mapping


@pytest.mark.anyio
async def test_finish_excludes_result_in_mapping_when_not_provided() -> None:
    redis = MagicMock()
    pipeline = Pipeline()
    redis.pipeline.return_value = pipeline
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    await queue.finish("job-1", "failed", error="timeout")

    assert len(pipeline.calls) > 0
    hset_calls = [c for c in pipeline.calls if c[0] == "hset"]
    assert len(hset_calls) > 0
    mapping = hset_calls[0][2].get("mapping", {})
    assert "result" not in mapping


@pytest.mark.anyio
async def test_finish_includes_error_in_mapping_when_provided() -> None:
    redis = MagicMock()
    pipeline = Pipeline()
    redis.pipeline.return_value = pipeline
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    await queue.finish("job-1", "failed", error="timeout")

    assert len(pipeline.calls) > 0
    hset_calls = [c for c in pipeline.calls if c[0] == "hset"]
    assert len(hset_calls) > 0
    mapping = hset_calls[0][2].get("mapping", {})
    assert "error" in mapping


@pytest.mark.anyio
async def test_finish_excludes_error_in_mapping_when_not_provided() -> None:
    redis = MagicMock()
    pipeline = Pipeline()
    redis.pipeline.return_value = pipeline
    queue = RedisInferenceQueue(redis, capacity=10, job_ttl_seconds=60)

    await queue.finish("job-1", "succeeded", result={"label": "positive"})

    assert len(pipeline.calls) > 0
    hset_calls = [c for c in pipeline.calls if c[0] == "hset"]
    assert len(hset_calls) > 0
    mapping = hset_calls[0][2].get("mapping", {})
    assert "error" not in mapping
