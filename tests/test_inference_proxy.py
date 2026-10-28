from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from fastapi.testclient import TestClient

from app import deployment_routes

READY_STATUS = {
    "endpoint": "http://sentiment.default.svc.cluster.local",
    "conditions": [{"type": "Available", "status": "True"}],
}


class FakeRuntime:
    """Stands in for aiohttp.ClientSession and the response it returns."""

    def __init__(self, status: int = 200, error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, **_kwargs: Any) -> FakeRuntime:
        return self

    async def __aenter__(self) -> FakeRuntime:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, json: dict[str, Any]) -> FakeRuntime:
        if self.error is not None:
            raise self.error
        self.calls.append((url, json))
        return self

    async def json(self) -> dict[str, Any]:
        return {"model": "sentiment", "version": "v1", "label": "positive"}


def deploy(client: TestClient, gateway: Any, status: dict[str, Any]) -> None:
    client.put("/v1/models/sentiment", json={})
    client.put("/v1/models/sentiment/versions/v1", json={"runtime_image": "runtime:v1"})
    client.put("/v1/deployments/default/sentiment", json={"model": "sentiment", "version": "v1"})
    gateway.resources[("default", "sentiment")]["status"] = status


def test_dashboard_is_served_at_root(deployment_client: tuple[TestClient, Any]) -> None:
    client, _ = deployment_client

    response = client.get("/")

    assert response.status_code == 200
    assert "Kernexys Console" in response.text


def test_infer_proxies_to_controller_reported_endpoint(
    deployment_client: tuple[TestClient, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, gateway = deployment_client
    deploy(client, gateway, READY_STATUS)
    runtime = FakeRuntime()
    monkeypatch.setattr(deployment_routes.aiohttp, "ClientSession", runtime)

    response = client.post("/v1/deployments/default/sentiment/infer", json={"text": "great"})

    assert response.status_code == 200
    assert response.json()["label"] == "positive"
    assert runtime.calls == [
        ("http://sentiment.default.svc.cluster.local/v1/infer", {"text": "great"})
    ]


def test_infer_rejects_unready_deployment(deployment_client: tuple[TestClient, Any]) -> None:
    client, gateway = deployment_client
    deploy(client, gateway, {})

    response = client.post("/v1/deployments/default/sentiment/infer", json={"text": "great"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "deployment_not_ready"


@pytest.mark.parametrize(
    ("runtime", "status", "code"),
    [
        (FakeRuntime(status=500), 502, "runtime_error"),
        (FakeRuntime(error=aiohttp.ClientConnectionError("refused")), 503, "runtime_unavailable"),
    ],
)
def test_infer_sanitizes_runtime_failures(
    deployment_client: tuple[TestClient, Any],
    monkeypatch: pytest.MonkeyPatch,
    runtime: FakeRuntime,
    status: int,
    code: str,
) -> None:
    client, gateway = deployment_client
    deploy(client, gateway, READY_STATUS)
    monkeypatch.setattr(deployment_routes.aiohttp, "ClientSession", runtime)

    response = client.post("/v1/deployments/default/sentiment/infer", json={"text": "great"})

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
