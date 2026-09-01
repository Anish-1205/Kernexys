from __future__ import annotations

from fastapi.testclient import TestClient

from runtime_app.config import Settings
from runtime_app.main import create_app


def test_health_inference_and_metrics_contract() -> None:
    settings = Settings(model_name="sentiment", model_version="v1", baked_model_version="v1")
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").json() == {"status": "alive"}
        assert client.get("/health/ready").json() == {
            "status": "ready",
            "model": "sentiment",
            "version": "v1",
        }

        response = client.post(
            "/v1/infer",
            headers={"x-request-id": "runtime-test-1"},
            json={"text": "I love this excellent result"},
        )
        assert response.status_code == 200
        assert response.headers["x-request-id"] == "runtime-test-1"
        assert response.json() == {
            "model": "sentiment",
            "version": "v1",
            "label": "positive",
            "confidence": 0.967705,
            "request_id": "runtime-test-1",
        }

        metrics = client.get("/metrics").text
        assert 'kernexys_runtime_info{model="sentiment",version="v1"} 1.0' in metrics
        assert (
            'kernexys_inference_requests_total{model="sentiment",outcome="success",'
            'version="v1"} 1.0' in metrics
        )


def test_validation_errors_are_bounded_and_measured() -> None:
    settings = Settings(max_request_bytes=256)
    with TestClient(create_app(settings)) as client:
        invalid = client.post("/v1/infer", json={"text": ""})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "validation_error"

        oversized = client.post("/v1/infer", json={"text": "x" * 512})
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "request_too_large"
        assert oversized.headers["x-request-id"]

        metrics = client.get("/metrics").text
        assert (
            'kernexys_inference_requests_total{model="sentiment",outcome="error",version="v1"} 2.0'
            in metrics
        )


def test_unknown_fields_are_rejected() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.post("/v1/infer", json={"text": "good", "unknown": True})

    assert response.status_code == 422
