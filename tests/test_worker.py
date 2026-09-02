from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.async_queue import AsyncQueueError, ClaimedJob
from app.worker import process_job, recover_periodically


class Response:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self.body = body

    async def __aenter__(self) -> Response:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def json(self) -> dict[str, Any]:
        return self.body


class Session:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.url = ""
        self.payload: dict[str, Any] = {}

    def post(self, url: str, json: dict[str, Any]) -> Response:
        self.url = url
        self.payload = json
        return self.response


@pytest.mark.anyio
async def test_worker_persists_successful_runtime_result() -> None:
    queue = AsyncMock()
    session = Session(Response(200, {"label": "positive"}))
    job = ClaimedJob("job-1", {"endpoint": "http://runtime", "text": "reliable"})

    await process_job(queue, session, job)  # type: ignore[arg-type]

    queue.finish.assert_awaited_once_with("job-1", "succeeded", result={"label": "positive"})
    assert session.url == "http://runtime/v1/infer"


@pytest.mark.anyio
async def test_worker_records_sanitized_failure() -> None:
    queue = AsyncMock()
    session = Session(Response(503, {"detail": "secret"}))
    job = ClaimedJob("job-2", {"endpoint": "http://runtime", "text": "retry"})

    await process_job(queue, session, job)  # type: ignore[arg-type]

    queue.finish.assert_awaited_once_with(
        "job-2", "failed", error="The model runtime request failed."
    )


def _draining_sweep(stop: asyncio.Event, steps: list[object]) -> object:
    """Return a ``recover_processing`` side effect that walks ``steps`` then stops.

    Each list entry is either an int returned as the recovered count or an
    exception instance to raise. Once ``steps`` is exhausted the shutdown event
    is set so ``recover_periodically`` exits its loop.
    """
    pending = iter(steps)

    async def sweep(*_args: object, **_kwargs: object) -> int:
        step = next(pending, None)
        if step is None:
            stop.set()
            return 0
        if isinstance(step, BaseException):
            raise step
        assert isinstance(step, int)
        return step

    return sweep


@pytest.mark.anyio
async def test_recovery_sweep_retries_after_a_lease_blocked_attempt() -> None:
    """A restart that races a still-held recovery lease must not strand the job.

    The first sweeps return 0 (lease held by a departed worker); recovery must
    keep retrying so a later sweep reclaims the job once the lease lapses.
    """
    queue = AsyncMock()
    stop = asyncio.Event()
    queue.recover_processing.side_effect = _draining_sweep(stop, [0, 0, 1])

    async with asyncio.timeout(5):
        await recover_periodically(queue, stop, interval_seconds=0.01)

    assert queue.recover_processing.await_count >= 3


@pytest.mark.anyio
async def test_recovery_sweep_survives_transient_redis_errors() -> None:
    queue = AsyncMock()
    stop = asyncio.Event()
    queue.recover_processing.side_effect = _draining_sweep(
        stop, [AsyncQueueError("Redis is unavailable"), 2]
    )

    async with asyncio.timeout(5):
        await recover_periodically(queue, stop, interval_seconds=0.01)

    assert queue.recover_processing.await_count >= 2


@pytest.mark.anyio
async def test_recovery_sweep_stops_on_shutdown_signal() -> None:
    queue = AsyncMock()
    queue.recover_processing.return_value = 0
    stop = asyncio.Event()
    stop.set()

    async with asyncio.timeout(5):
        await recover_periodically(queue, stop, interval_seconds=30)

    queue.recover_processing.assert_not_awaited()
