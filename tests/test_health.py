from __future__ import annotations

import re

from fastapi.testclient import TestClient


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
