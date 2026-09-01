"""Deployment API backed exclusively by ModelDeployment custom resources."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.errors import ApiError
from app.kubernetes import DeploymentGateway, DeploymentGatewayError
from app.repository import RegistryRepository
from app.schemas import (
    DeploymentRead,
    DeploymentResources,
    DeploymentSpecRead,
    DeploymentStatus,
    DeploymentUpsert,
    ResourceName,
    RollbackRequest,
)

deployment_router = APIRouter(prefix="/v1/deployments", tags=["deployments"])
Session = Annotated[AsyncSession, Depends(get_session)]
NamespacedResourceName = Annotated[ResourceName, Path()]


def get_deployment_gateway(request: Request) -> DeploymentGateway:
    gateway = request.app.state.deployment_gateway
    if gateway is None:
        raise ApiError(
            503,
            "kubernetes_disabled",
            "Kubernetes deployment operations are not enabled for this API process.",
        )
    return gateway


Gateway = Annotated[DeploymentGateway, Depends(get_deployment_gateway)]


@deployment_router.put("/{namespace}/{name}", response_model=DeploymentRead)
async def put_deployment(
    namespace: NamespacedResourceName,
    name: NamespacedResourceName,
    body: DeploymentUpsert,
    session: Session,
    gateway: Gateway,
) -> DeploymentRead:
    version = await RegistryRepository(session).get_version(body.model, body.version)
    if version is None:
        raise ApiError(
            404,
            "model_version_not_found",
            f"Model version '{body.model}:{body.version}' was not found.",
        )

    resource = _desired_resource(
        namespace=namespace,
        name=name,
        desired=body,
        runtime_image=version.runtime_image,
        artifact_digest=version.artifact_digest,
    )
    try:
        observed = await gateway.apply(namespace, name, resource)
    except DeploymentGatewayError as exc:
        raise _deployment_error(exc, namespace, name) from exc
    return _resource_to_read(observed)


@deployment_router.get("/{namespace}/{name}", response_model=DeploymentRead)
async def get_deployment(
    namespace: NamespacedResourceName,
    name: NamespacedResourceName,
    gateway: Gateway,
) -> DeploymentRead:
    try:
        observed = await gateway.get(namespace, name)
    except DeploymentGatewayError as exc:
        raise _deployment_error(exc, namespace, name) from exc
    return _resource_to_read(observed)


@deployment_router.delete("/{namespace}/{name}", status_code=204)
async def delete_deployment(
    namespace: NamespacedResourceName,
    name: NamespacedResourceName,
    gateway: Gateway,
) -> Response:
    try:
        await gateway.delete(namespace, name)
    except DeploymentGatewayError as exc:
        raise _deployment_error(exc, namespace, name) from exc
    return Response(status_code=204)


@deployment_router.post("/{namespace}/{name}/rollback", response_model=DeploymentRead)
async def rollback_deployment(
    namespace: NamespacedResourceName,
    name: NamespacedResourceName,
    body: RollbackRequest,
    session: Session,
    gateway: Gateway,
) -> DeploymentRead:
    try:
        current = await gateway.get(namespace, name)
    except DeploymentGatewayError as exc:
        raise _deployment_error(exc, namespace, name) from exc

    current_spec = current.get("spec", {})
    current_model = current_spec.get("model", {}).get("name")
    if not isinstance(current_model, str):
        raise ApiError(
            502,
            "invalid_deployment_state",
            "The stored ModelDeployment does not contain a valid model identity.",
        )
    version = await RegistryRepository(session).get_version(current_model, body.version)
    if version is None:
        raise ApiError(
            404,
            "model_version_not_found",
            f"Model version '{current_model}:{body.version}' was not found.",
        )

    try:
        desired = DeploymentUpsert(
            model=current_model,
            version=body.version,
            replicas=current_spec.get("replicas", 1),
            port=current_spec.get("runtime", {}).get("port", 8080),
            resources=current_spec.get("resources", {}),
        )
    except (TypeError, ValueError) as exc:
        raise ApiError(
            502,
            "invalid_deployment_state",
            "The stored ModelDeployment spec cannot be rolled back safely.",
        ) from exc

    resource = _desired_resource(
        namespace=namespace,
        name=name,
        desired=desired,
        runtime_image=version.runtime_image,
        artifact_digest=version.artifact_digest,
        resource_version=current.get("metadata", {}).get("resourceVersion"),
    )
    try:
        observed = await gateway.apply(namespace, name, resource)
    except DeploymentGatewayError as exc:
        raise _deployment_error(exc, namespace, name) from exc
    return _resource_to_read(observed)


def _desired_resource(
    namespace: str,
    name: str,
    desired: DeploymentUpsert,
    runtime_image: str,
    artifact_digest: str | None,
    resource_version: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "name": name,
        "namespace": namespace,
        "labels": {
            "app.kubernetes.io/managed-by": "kernexys-control-api",
            "app.kubernetes.io/part-of": "kernexys",
        },
    }
    if artifact_digest:
        metadata["annotations"] = {
            "platform.kernexys.io/artifact-digest": artifact_digest,
        }
    if resource_version:
        metadata["resourceVersion"] = resource_version

    return {
        "apiVersion": "platform.kernexys.io/v1alpha1",
        "kind": "ModelDeployment",
        "metadata": metadata,
        "spec": {
            "model": {"name": desired.model, "version": desired.version},
            "runtime": {"image": runtime_image, "port": desired.port},
            "replicas": desired.replicas,
            "resources": desired.resources.model_dump(),
        },
    }


def _resource_to_read(resource: dict[str, Any]) -> DeploymentRead:
    try:
        metadata = resource["metadata"]
        spec = resource["spec"]
        model = spec["model"]
        runtime = spec["runtime"]
        status = DeploymentStatus.model_validate(resource.get("status", {}))
        return DeploymentRead(
            name=metadata["name"],
            namespace=metadata["namespace"],
            generation=metadata.get("generation", 0),
            resource_version=metadata.get("resourceVersion", ""),
            created_at=metadata.get("creationTimestamp"),
            spec=DeploymentSpecRead(
                model=model["name"],
                version=model["version"],
                runtime_image=runtime["image"],
                replicas=spec.get("replicas", 1),
                port=runtime.get("port", 8080),
                resources=DeploymentResources.model_validate(spec.get("resources", {})),
            ),
            status=status,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError(
            502,
            "invalid_deployment_state",
            "Kubernetes returned a malformed ModelDeployment resource.",
        ) from exc


def _deployment_error(error: DeploymentGatewayError, namespace: str, name: str) -> ApiError:
    if error.status == 404:
        return ApiError(
            404,
            "deployment_not_found",
            f"Deployment '{namespace}/{name}' was not found.",
        )
    if error.status == 409:
        return ApiError(
            409,
            "deployment_conflict",
            "The desired state conflicts with another Kubernetes field manager or update.",
        )
    if error.status == 422:
        return ApiError(
            422,
            "deployment_rejected",
            "Kubernetes rejected the ModelDeployment desired state.",
        )
    if error.status in {401, 403}:
        return ApiError(
            503,
            "kubernetes_forbidden",
            "The control API is not authorized to manage ModelDeployments.",
        )
    return ApiError(
        503,
        "kubernetes_unavailable",
        "The Kubernetes API is unavailable.",
    )
