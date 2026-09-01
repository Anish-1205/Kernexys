from __future__ import annotations

from fastapi.testclient import TestClient


def test_model_resource_is_idempotent_and_listable(client: TestClient) -> None:
    created = client.put("/v1/models/sentiment", json={"description": "Sentiment classifier"})
    repeated = client.put("/v1/models/sentiment", json={"description": "Sentiment classifier"})
    updated = client.put("/v1/models/sentiment", json={"description": "Updated description"})

    assert created.status_code == 201
    assert repeated.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["description"] == "Updated description"

    fetched = client.get("/v1/models/sentiment")
    listed = client.get("/v1/models?limit=10&offset=0")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "sentiment"
    assert [item["name"] for item in listed.json()["items"]] == ["sentiment"]


def test_model_version_is_immutable_and_idempotent(client: TestClient) -> None:
    client.put("/v1/models/sentiment", json={"description": None})
    version = {
        "runtime_image": "ghcr.io/example/sentiment:v1",
        "artifact_digest": "sha256:" + "a" * 64,
        "metadata": {"labels": ["negative", "positive"]},
    }

    created = client.put("/v1/models/sentiment/versions/v1", json=version)
    repeated = client.put("/v1/models/sentiment/versions/v1", json=version)
    conflict = client.put(
        "/v1/models/sentiment/versions/v1",
        json={**version, "runtime_image": "ghcr.io/example/sentiment:changed"},
        headers={"x-request-id": "immutable-test"},
    )

    assert created.status_code == 201
    assert created.json()["metadata"] == version["metadata"]
    assert repeated.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "immutable_model_version"
    assert conflict.json()["error"]["request_id"] == "immutable-test"

    fetched = client.get("/v1/models/sentiment/versions/v1")
    listed = client.get("/v1/models/sentiment/versions")
    assert fetched.status_code == 200
    assert fetched.json()["runtime_image"] == version["runtime_image"]
    assert [item["version"] for item in listed.json()["items"]] == ["v1"]


def test_missing_resources_return_structured_errors(client: TestClient) -> None:
    missing_model = client.get("/v1/models/unknown", headers={"x-request-id": "missing"})
    missing_version = client.put(
        "/v1/models/unknown/versions/v1",
        json={"runtime_image": "example/runtime:v1"},
    )

    assert missing_model.status_code == 404
    assert missing_model.json()["error"]["code"] == "model_not_found"
    assert missing_model.json()["error"]["request_id"] == "missing"
    assert missing_version.status_code == 404


def test_invalid_input_is_rejected(client: TestClient) -> None:
    invalid_name = client.put("/v1/models/INVALID_NAME", json={})
    unknown_field = client.put("/v1/models/valid-name", json={"unknown": True})
    invalid_digest = client.put(
        "/v1/models/valid-name/versions/v1",
        json={
            "runtime_image": "example/runtime:v1",
            "artifact_digest": "md5:bad",
        },
    )

    assert invalid_name.status_code == 422
    assert invalid_name.json()["error"]["code"] == "validation_error"
    assert unknown_field.status_code == 422
    assert invalid_digest.status_code == 422
