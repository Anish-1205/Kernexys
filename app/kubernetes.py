"""Narrow async gateway for ModelDeployment custom resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import aiohttp
from kubernetes_asyncio import client, config
from kubernetes_asyncio.client.exceptions import ApiException

from app.config import Settings

GROUP = "platform.kernexys.io"
VERSION = "v1alpha1"
PLURAL = "modeldeployments"
FIELD_MANAGER = "kernexys-control-api"


@dataclass(frozen=True, slots=True)
class DeploymentGatewayError(Exception):
    status: int
    reason: str

    def __str__(self) -> str:
        return f"Kubernetes API error {self.status}: {self.reason}"


class DeploymentGateway(Protocol):
    async def check_ready(self) -> None: ...

    async def apply(self, namespace: str, name: str, body: dict[str, Any]) -> dict[str, Any]: ...

    async def get(self, namespace: str, name: str) -> dict[str, Any]: ...

    async def delete(self, namespace: str, name: str) -> bool: ...

    async def close(self) -> None: ...


class KubernetesDeploymentGateway:
    def __init__(
        self,
        custom_objects: client.CustomObjectsApi,
        api_client: client.ApiClient,
        request_timeout_seconds: int,
    ) -> None:
        self._custom_objects = custom_objects
        self._api_client = api_client
        self._request_timeout_seconds = request_timeout_seconds

    @classmethod
    async def create(cls, settings: Settings) -> KubernetesDeploymentGateway:
        configuration = client.Configuration()
        if settings.kubernetes_config_mode == "in-cluster":
            config.load_incluster_config(client_configuration=configuration)
        else:
            await config.load_kube_config(
                config_file=settings.kubernetes_kubeconfig,
                context=settings.kubernetes_context,
                client_configuration=configuration,
                persist_config=False,
            )
        api_client = client.ApiClient(configuration=configuration)
        return cls(
            client.CustomObjectsApi(api_client),
            api_client,
            settings.kubernetes_request_timeout_seconds,
        )

    async def check_ready(self) -> None:
        await self._execute(
            self._custom_objects.get_api_resources(
                GROUP,
                VERSION,
                _request_timeout=self._request_timeout_seconds,
            )
        )

    async def apply(
        self,
        namespace: str,
        name: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        value = await self._execute(
            self._custom_objects.patch_namespaced_custom_object(
                GROUP,
                VERSION,
                namespace,
                PLURAL,
                name,
                body,
                field_manager=FIELD_MANAGER,
                field_validation="Strict",
                force=False,
                _content_type="application/apply-patch+yaml",
                _request_timeout=self._request_timeout_seconds,
            )
        )
        if value is None:
            # The generated custom-object client omits HTTP 201 from its response
            # type map even though server-side apply may create the resource.
            return await self.get(namespace, name)
        return dict(value)

    async def get(self, namespace: str, name: str) -> dict[str, Any]:
        value = await self._execute(
            self._custom_objects.get_namespaced_custom_object(
                GROUP,
                VERSION,
                namespace,
                PLURAL,
                name,
                _request_timeout=self._request_timeout_seconds,
            )
        )
        return dict(value)

    async def delete(self, namespace: str, name: str) -> bool:
        try:
            await self._execute(
                self._custom_objects.delete_namespaced_custom_object(
                    GROUP,
                    VERSION,
                    namespace,
                    PLURAL,
                    name,
                    propagation_policy="Background",
                    _request_timeout=self._request_timeout_seconds,
                )
            )
            return True
        except DeploymentGatewayError as exc:
            if exc.status == 404:
                return False
            raise

    async def close(self) -> None:
        await self._api_client.close()

    async def _execute(self, operation: Any) -> Any:
        try:
            return await operation
        except ApiException as exc:
            raise DeploymentGatewayError(exc.status or 503, exc.reason or "request failed") from exc
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise DeploymentGatewayError(503, "Kubernetes API is unavailable") from exc
