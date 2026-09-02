"""Health and model registry HTTP routes."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.errors import ApiError
from app.repository import RegistryRepository, version_matches
from app.schemas import (
    ModelList,
    ModelRead,
    ModelUpsert,
    ResourceName,
    VersionCreate,
    VersionList,
    VersionName,
    VersionRead,
)

health_router = APIRouter(tags=["health"])
registry_router = APIRouter(prefix="/v1", tags=["model registry"])
Session = Annotated[AsyncSession, Depends(get_session)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0)]
logger = logging.getLogger("kernexys.readiness")


@health_router.get("/health/live", summary="Process liveness")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/health/ready", summary="Dependency readiness")
async def ready(request: Request, session: Session) -> dict[str, str]:
    dependency = "database"
    try:
        async with asyncio.timeout(request.app.state.settings.readiness_timeout_seconds):
            await session.execute(text("SELECT 1"))
            if request.app.state.settings.kubernetes_enabled:
                dependency = "kubernetes"
                gateway = request.app.state.deployment_gateway
                if gateway is None:
                    raise RuntimeError("Kubernetes gateway is not initialized")
                await gateway.check_ready()
            if request.app.state.settings.async_inference_enabled:
                dependency = "redis"
                queue = request.app.state.async_queue
                if queue is None:
                    raise RuntimeError("Async queue is not initialized")
                await queue.check_ready()
    except Exception as exc:
        logger.warning(
            "readiness_dependency_unavailable",
            extra={"dependency": dependency, "error_type": type(exc).__name__},
        )
        raise ApiError(
            503,
            "not_ready",
            "A required control-plane dependency is unavailable.",
            {"dependency": dependency},
        ) from exc
    return {"status": "ready"}


@registry_router.put(
    "/models/{model_name}",
    response_model=ModelRead,
    responses={201: {"model": ModelRead}},
)
async def put_model(
    model_name: Annotated[ResourceName, Path()],
    body: ModelUpsert,
    response: Response,
    session: Session,
) -> ModelRead:
    result = await RegistryRepository(session).put_model(model_name, body.description)
    response.status_code = 201 if result.created else 200
    return ModelRead.model_validate(result.value)


@registry_router.get("/models", response_model=ModelList)
async def list_models(
    session: Session,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> ModelList:
    values = await RegistryRepository(session).list_models(limit, offset)
    return ModelList(
        items=[ModelRead.model_validate(value) for value in values], limit=limit, offset=offset
    )


@registry_router.get("/models/{model_name}", response_model=ModelRead)
async def get_model(
    model_name: Annotated[ResourceName, Path()],
    session: Session,
) -> ModelRead:
    value = await RegistryRepository(session).get_model(model_name)
    if value is None:
        raise ApiError(404, "model_not_found", f"Model '{model_name}' was not found.")
    return ModelRead.model_validate(value)


@registry_router.put(
    "/models/{model_name}/versions/{version}",
    response_model=VersionRead,
    responses={201: {"model": VersionRead}, 409: {"description": "Version is immutable"}},
)
async def put_version(
    model_name: Annotated[ResourceName, Path()],
    version: Annotated[VersionName, Path()],
    body: VersionCreate,
    response: Response,
    session: Session,
) -> VersionRead:
    repository = RegistryRepository(session)
    if await repository.get_model(model_name) is None:
        raise ApiError(404, "model_not_found", f"Model '{model_name}' was not found.")

    result = await repository.put_version(
        model_name,
        version,
        body.runtime_image,
        body.artifact_digest,
        body.metadata,
    )
    if not result.created and not version_matches(
        result.value,
        body.runtime_image,
        body.artifact_digest,
        body.metadata,
    ):
        raise ApiError(
            409,
            "immutable_model_version",
            f"Model version '{model_name}:{version}' already exists with different content.",
        )
    response.status_code = 201 if result.created else 200
    return VersionRead.model_validate(result.value)


@registry_router.get("/models/{model_name}/versions", response_model=VersionList)
async def list_versions(
    model_name: Annotated[ResourceName, Path()],
    session: Session,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> VersionList:
    repository = RegistryRepository(session)
    if await repository.get_model(model_name) is None:
        raise ApiError(404, "model_not_found", f"Model '{model_name}' was not found.")
    values = await repository.list_versions(model_name, limit, offset)
    return VersionList(
        items=[VersionRead.model_validate(value) for value in values],
        limit=limit,
        offset=offset,
    )


@registry_router.get("/models/{model_name}/versions/{version}", response_model=VersionRead)
async def get_version(
    model_name: Annotated[ResourceName, Path()],
    version: Annotated[VersionName, Path()],
    session: Session,
) -> VersionRead:
    value = await RegistryRepository(session).get_version(model_name, version)
    if value is None:
        raise ApiError(
            404,
            "model_version_not_found",
            f"Model version '{model_name}:{version}' was not found.",
        )
    return VersionRead.model_validate(value)
