from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.async_queue import ClaimedJob
from app.worker import process_job


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
