from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _ready_deployment(gateway: Any) -> None:
    gateway.resources[("default", "sentiment")] = {
        "metadata": {"name": "sentiment", "namespace": "default"},
        "spec": {},
        "status": {
            "endpoint": "http://sentiment.default.svc.cluster.local",
            "conditions": [{"type": "Available", "status": "True"}],
        },
    }


def test_enqueue_is_idempotent_and_pollable(async_client: tuple[TestClient, Any, Any]) -> None:
    client, gateway, _queue = async_client
    _ready_deployment(gateway)
    headers = {"idempotency-key": "caller-request-1"}

    created = client.post(
        "/v1/async-inference/default/sentiment/jobs", json={"text": "reliable"}, headers=headers
    )
    repeated = client.post(
        "/v1/async-inference/default/sentiment/jobs", json={"text": "reliable"}, headers=headers
    )

    assert created.status_code == 202
    assert repeated.status_code == 200
    assert repeated.json()["job_id"] == created.json()["job_id"]
    polled = client.get(f"/v1/async-inference/jobs/{created.json()['job_id']}")
    assert polled.json()["status"] == "queued"


def test_enqueue_rejects_unready_deployment(async_client: tuple[TestClient, Any, Any]) -> None:
    client, gateway, _queue = async_client
    _ready_deployment(gateway)
    gateway.resources[("default", "sentiment")]["status"]["conditions"] = []

    response = client.post("/v1/async-inference/default/sentiment/jobs", json={"text": "wait"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "deployment_not_ready"


def test_enqueue_applies_backpressure(async_client: tuple[TestClient, Any, Any]) -> None:
    client, gateway, queue = async_client
    _ready_deployment(gateway)
    queue.full = True

    response = client.post(
        "/v1/async-inference/default/sentiment/jobs", json={"text": "overloaded"}
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "queue_full"


def test_idempotency_key_rejects_different_payload(
    async_client: tuple[TestClient, Any, Any],
) -> None:
    client, gateway, _queue = async_client
    _ready_deployment(gateway)
    headers = {"idempotency-key": "same-key"}
    assert (
        client.post(
            "/v1/async-inference/default/sentiment/jobs", json={"text": "first"}, headers=headers
        ).status_code
        == 202
    )

    response = client.post(
        "/v1/async-inference/default/sentiment/jobs", json={"text": "second"}, headers=headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"
