from __future__ import annotations

import asyncio
from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.async_queue import EnqueueResult
from app.config import Settings
from app.database import create_database_engine
from app.db_models import Base
from app.kubernetes import DeploymentGatewayError
from app.main import create_app


class FakeDeploymentGateway:
    def __init__(self) -> None:
        self.resources: dict[tuple[str, str], dict[str, Any]] = {}
        self.apply_calls = 0
        self.writes = 0
        self.closed = False
        self.ready_error: DeploymentGatewayError | None = None
        self.operation_error: DeploymentGatewayError | None = None

    async def check_ready(self) -> None:
        if self.ready_error is not None:
            raise self.ready_error

    async def apply(
        self,
        namespace: str,
        name: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        self._raise_operation_error()
        self.apply_calls += 1
        key = (namespace, name)
        existing = self.resources.get(key)
        desired = deepcopy(body)
        desired_metadata = desired.setdefault("metadata", {})
        supplied_resource_version = desired_metadata.pop("resourceVersion", None)
        if existing is not None and supplied_resource_version not in {
            None,
            existing["metadata"]["resourceVersion"],
        }:
            raise DeploymentGatewayError(409, "resource version conflict")

        if existing is not None:
            unchanged = (
                existing["spec"] == desired["spec"]
                and existing["metadata"].get("labels") == desired_metadata.get("labels")
                and existing["metadata"].get("annotations") == desired_metadata.get("annotations")
            )
            if unchanged:
                return deepcopy(existing)
            generation = existing["metadata"]["generation"] + (existing["spec"] != desired["spec"])
            resource_version = str(int(existing["metadata"]["resourceVersion"]) + 1)
            created_at = existing["metadata"]["creationTimestamp"]
            status = deepcopy(existing.get("status", {}))
        else:
            generation = 1
            resource_version = "1"
            created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            status = {}

        desired_metadata.update(
            {
                "name": name,
                "namespace": namespace,
                "generation": generation,
                "resourceVersion": resource_version,
                "creationTimestamp": created_at,
            }
        )
        desired["status"] = status
        self.resources[key] = desired
        self.writes += 1
        return deepcopy(desired)

    async def get(self, namespace: str, name: str) -> dict[str, Any]:
        self._raise_operation_error()
        try:
            return deepcopy(self.resources[(namespace, name)])
        except KeyError as exc:
            raise DeploymentGatewayError(404, "not found") from exc

    async def delete(self, namespace: str, name: str) -> bool:
        self._raise_operation_error()
        return self.resources.pop((namespace, name), None) is not None

    async def close(self) -> None:
        self.closed = True

    def _raise_operation_error(self) -> None:
        if self.operation_error is not None:
            raise self.operation_error


class FakeInferenceQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, str]] = {}
        self.full = False
        self.closed = False

    async def check_ready(self) -> None:
        return None

    async def enqueue(self, job_id: str, payload: dict[str, Any]) -> EnqueueResult:
        if self.full:
            return EnqueueResult(created=False, full=True)
        if job_id in self.jobs:
            if self.jobs[job_id]["payload"] != str(payload):
                return EnqueueResult(created=False, full=False, conflict=True)
            return EnqueueResult(created=False, full=False)
        self.jobs[job_id] = {"status": "queued", "payload": str(payload)}
        return EnqueueResult(created=True, full=False)

    async def get(self, job_id: str) -> dict[str, str] | None:
        return deepcopy(self.jobs.get(job_id))

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = (tmp_path / "test.db").as_posix()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{database_path}")
    engine = create_database_engine(settings)

    async def create_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    with TestClient(create_app(settings, engine=engine)) as test_client:
        yield test_client
    asyncio.run(engine.dispose())


@pytest.fixture
def deployment_client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, FakeDeploymentGateway]]:
    database_path = (tmp_path / "deployments.db").as_posix()
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{database_path}",
        kubernetes_enabled=True,
    )
    engine = create_database_engine(settings)

    async def create_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    gateway = FakeDeploymentGateway()
    with TestClient(create_app(settings, engine=engine, deployment_gateway=gateway)) as test_client:
        yield test_client, gateway
    asyncio.run(engine.dispose())


@pytest.fixture
def async_client(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, FakeDeploymentGateway, FakeInferenceQueue]]:
    database_path = (tmp_path / "async.db").as_posix()
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{database_path}",
        kubernetes_enabled=True,
        async_inference_enabled=True,
    )
    engine = create_database_engine(settings)

    async def create_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    gateway = FakeDeploymentGateway()
    queue = FakeInferenceQueue()
    application = create_app(
        settings,
        engine=engine,
        deployment_gateway=gateway,
        async_queue=queue,  # type: ignore[arg-type]
    )
    with TestClient(application) as test_client:
        yield test_client, gateway, queue
    asyncio.run(engine.dispose())
