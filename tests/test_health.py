from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.database import get_session


def test_liveness_and_readiness(client: TestClient) -> None:
    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


def test_request_id_is_propagated(client: TestClient) -> None:
    response = client.get("/health/live", headers={"x-request-id": "test-request.42"})

    assert response.headers["x-request-id"] == "test-request.42"


def test_invalid_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health/live", headers={"x-request-id": "bad request id"})

    assert re.fullmatch(r"[0-9a-f-]{36}", response.headers["x-request-id"])


def test_request_body_is_bounded(client: TestClient) -> None:
    response = client.put(
        "/v1/models/large",
        content=b"x" * 1_048_577,
        headers={"content-type": "application/json", "x-request-id": "oversize-test"},
    )

    assert response.status_code == 413
    assert response.json()["error"] == {
        "code": "request_too_large",
        "message": "Request bodies are limited to 1048576 bytes.",
        "request_id": "oversize-test",
        "details": None,
    }


def test_database_outage_is_sanitized(client: TestClient) -> None:
    class UnavailableSession:
        async def scalars(self, *_args: object, **_kwargs: object) -> None:
            raise OperationalError("SELECT models", {}, RuntimeError("password=secret"))

    async def unavailable_session():  # type: ignore[no-untyped-def]
        yield UnavailableSession()

    client.app.dependency_overrides[get_session] = unavailable_session
    try:
        response = client.get("/v1/models", headers={"x-request-id": "database-outage"})
    finally:
        client.app.dependency_overrides.pop(get_session)

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "database_unavailable",
        "message": "The model registry database is unavailable.",
        "request_id": "database-outage",
        "details": None,
    }
    assert "secret" not in response.text
