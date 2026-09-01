from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import create_database_engine
from app.db_models import Base
from app.main import create_app

pytestmark = pytest.mark.integration


def test_control_api_server_side_applies_real_custom_resource(tmp_path: Path) -> None:
    kubeconfig = os.getenv("KERNEXYS_TEST_KUBECONFIG")
    if not kubeconfig:
        pytest.skip("KERNEXYS_TEST_KUBECONFIG is set by make api-kubernetes-integration")
    database_path = (tmp_path / "api-kubernetes.db").as_posix()
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{database_path}",
        kubernetes_enabled=True,
        kubernetes_config_mode="kubeconfig",
        kubernetes_kubeconfig=kubeconfig,
    )
    engine = create_database_engine(settings)

    async def create_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    try:
        with TestClient(create_app(settings, engine=engine)) as client:
            assert client.get("/health/ready").status_code == 200
            assert client.put("/v1/models/sentiment", json={}).status_code == 201
            assert (
                client.put(
                    "/v1/models/sentiment/versions/v1",
                    json={"runtime_image": "kernexys/model-runtime:v1"},
                ).status_code
                == 201
            )
            assert (
                client.put(
                    "/v1/models/sentiment/versions/v2",
                    json={"runtime_image": "kernexys/model-runtime:v2"},
                ).status_code
                == 201
            )

            desired = client.put(
                "/v1/deployments/api-integration/sentiment",
                json={"model": "sentiment", "version": "v1", "replicas": 2},
            )
            assert desired.status_code == 200, desired.text
            assert desired.json()["generation"] == 1
            assert desired.json()["spec"]["runtime_image"] == "kernexys/model-runtime:v1"

            repeated = client.put(
                "/v1/deployments/api-integration/sentiment",
                json={"model": "sentiment", "version": "v1", "replicas": 2},
            )
            assert repeated.status_code == 200, repeated.text
            assert repeated.json()["resource_version"] == desired.json()["resource_version"]

            updated = client.put(
                "/v1/deployments/api-integration/sentiment",
                json={"model": "sentiment", "version": "v2", "replicas": 2},
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["generation"] == 2
            assert updated.json()["spec"]["runtime_image"] == "kernexys/model-runtime:v2"

            rolled_back = client.post(
                "/v1/deployments/api-integration/sentiment/rollback",
                json={"version": "v1"},
            )
            assert rolled_back.status_code == 200, rolled_back.text
            assert rolled_back.json()["generation"] == 3
            assert rolled_back.json()["spec"]["runtime_image"] == "kernexys/model-runtime:v1"

            fetched = client.get("/v1/deployments/api-integration/sentiment")
            assert fetched.status_code == 200
            assert fetched.json()["spec"]["replicas"] == 2

            assert client.delete("/v1/deployments/api-integration/sentiment").status_code == 204
            for _attempt in range(20):
                missing = client.get("/v1/deployments/api-integration/sentiment")
                if missing.status_code == 404:
                    break
                time.sleep(0.1)
            assert missing.status_code == 404
    finally:
        asyncio.run(engine.dispose())
