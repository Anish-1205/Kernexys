from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.kubernetes import DeploymentGatewayError


def register_version(
    client: TestClient,
    version: str,
    image: str,
    digest_character: str | None = None,
) -> None:
    client.put("/v1/models/sentiment", json={"description": "Reference classifier"})
    body: dict[str, Any] = {"runtime_image": image}
    if digest_character:
        body["artifact_digest"] = "sha256:" + digest_character * 64
    response = client.put(f"/v1/models/sentiment/versions/{version}", json=body)
    assert response.status_code in {200, 201}


def test_deployment_put_is_registry_validated_and_idempotent(
    deployment_client: tuple[TestClient, Any],
) -> None:
    client, gateway = deployment_client
    register_version(client, "v1", "kernexys/model-runtime:v1", "a")
    body = {
        "model": "sentiment",
        "version": "v1",
        "replicas": 2,
        "resources": {
            "requests": {"cpu": "50m", "memory": "64Mi"},
            "limits": {"cpu": "500m", "memory": "256Mi"},
        },
    }

    created = client.put("/v1/deployments/demo/sentiment-api", json=body)
    repeated = client.put("/v1/deployments/demo/sentiment-api", json=body)

    assert created.status_code == 200
    assert repeated.status_code == 200
    assert created.json() == repeated.json()
    assert created.json()["spec"] == {
        "model": "sentiment",
        "version": "v1",
        "runtime_image": "kernexys/model-runtime:v1",
        "replicas": 2,
        "port": 8080,
        "resources": body["resources"],
    }
    assert gateway.apply_calls == 2
    assert gateway.writes == 1
    resource = gateway.resources[("demo", "sentiment-api")]
    assert resource["kind"] == "ModelDeployment"
    assert resource["metadata"]["annotations"] == {
        "platform.kernexys.io/artifact-digest": "sha256:" + "a" * 64
    }


def test_unknown_model_version_is_rejected_before_kubernetes_write(
    deployment_client: tuple[TestClient, Any],
) -> None:
    client, gateway = deployment_client

    response = client.put(
        "/v1/deployments/default/missing",
        json={"model": "sentiment", "version": "missing"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_version_not_found"
    assert gateway.apply_calls == 0


def test_get_surfaces_controller_status(
    deployment_client: tuple[TestClient, Any],
) -> None:
    client, gateway = deployment_client
    register_version(client, "v1", "kernexys/model-runtime:v1")
    client.put(
        "/v1/deployments/default/sentiment",
        json={"model": "sentiment", "version": "v1"},
    )
    gateway.resources[("default", "sentiment")]["status"] = {
        "observedGeneration": 1,
        "desiredReplicas": 1,
        "readyReplicas": 1,
        "activeModel": "sentiment",
        "activeVersion": "v1",
        "endpoint": "http://sentiment.default.svc.cluster.local",
        "conditions": [
            {
                "type": "Available",
                "status": "True",
                "observedGeneration": 1,
                "reason": "MinimumReplicasAvailable",
                "message": "All desired runtime replicas are available.",
                "lastTransitionTime": "2026-09-01T12:00:00Z",
            }
        ],
    }

    response = client.get("/v1/deployments/default/sentiment")

    assert response.status_code == 200
    assert response.json()["status"]["activeVersion"] == "v1"
    assert response.json()["status"]["conditions"][0]["type"] == "Available"


def test_rollback_uses_registered_image_and_preserves_runtime_settings(
    deployment_client: tuple[TestClient, Any],
) -> None:
    client, gateway = deployment_client
    register_version(client, "v1", "kernexys/model-runtime:v1")
    register_version(client, "v2", "kernexys/model-runtime:v2")
    client.put(
        "/v1/deployments/default/sentiment",
        json={
            "model": "sentiment",
            "version": "v2",
            "replicas": 3,
            "port": 9090,
            "resources": {"requests": {"cpu": "100m"}},
        },
    )

    response = client.post(
        "/v1/deployments/default/sentiment/rollback",
        json={"version": "v1"},
    )

    assert response.status_code == 200
    assert response.json()["spec"] == {
        "model": "sentiment",
        "version": "v1",
        "runtime_image": "kernexys/model-runtime:v1",
        "replicas": 3,
        "port": 9090,
        "resources": {"requests": {"cpu": "100m"}, "limits": {}},
    }
    assert gateway.writes == 2


def test_delete_is_idempotent_and_missing_get_is_structured(
    deployment_client: tuple[TestClient, Any],
) -> None:
    client, _gateway = deployment_client
    register_version(client, "v1", "kernexys/model-runtime:v1")
    client.put(
        "/v1/deployments/default/sentiment",
        json={"model": "sentiment", "version": "v1"},
    )

    first = client.delete("/v1/deployments/default/sentiment")
    repeated = client.delete("/v1/deployments/default/sentiment")
    missing = client.get("/v1/deployments/default/sentiment")

    assert first.status_code == 204
    assert repeated.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "deployment_not_found"


def test_kubernetes_failures_are_sanitized(
    deployment_client: tuple[TestClient, Any],
) -> None:
    client, gateway = deployment_client
    register_version(client, "v1", "kernexys/model-runtime:v1")
    gateway.operation_error = DeploymentGatewayError(403, "sensitive RBAC detail")

    response = client.put(
        "/v1/deployments/default/sentiment",
        json={"model": "sentiment", "version": "v1"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "kubernetes_forbidden"
    assert "sensitive" not in response.text


def test_readiness_tracks_kubernetes_when_enabled(
    deployment_client: tuple[TestClient, Any],
) -> None:
    client, gateway = deployment_client
    gateway.ready_error = DeploymentGatewayError(503, "offline")

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "not_ready"


def test_deployment_api_is_explicitly_disabled_without_kubernetes(client: TestClient) -> None:
    response = client.get("/v1/deployments/default/sentiment")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "kubernetes_disabled"


def test_resource_quantities_are_validated(
    deployment_client: tuple[TestClient, Any],
) -> None:
    client, _gateway = deployment_client

    response = client.put(
        "/v1/deployments/default/sentiment",
        json={
            "model": "sentiment",
            "version": "v1",
            "resources": {"requests": {"cpu": "not a quantity"}},
        },
    )

    assert response.status_code == 422
