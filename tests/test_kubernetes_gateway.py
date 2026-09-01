from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from kubernetes_asyncio.client.exceptions import ApiException

from app.kubernetes import (
    FIELD_MANAGER,
    GROUP,
    PLURAL,
    VERSION,
    DeploymentGatewayError,
    KubernetesDeploymentGateway,
)


@pytest.mark.anyio
async def test_gateway_uses_strict_server_side_apply() -> None:
    custom_objects = SimpleNamespace(
        patch_namespaced_custom_object=AsyncMock(return_value={"metadata": {"name": "demo"}})
    )
    api_client = SimpleNamespace(close=AsyncMock())
    gateway = KubernetesDeploymentGateway(custom_objects, api_client, 7)
    body = {"apiVersion": f"{GROUP}/{VERSION}", "kind": "ModelDeployment"}

    result = await gateway.apply("default", "demo", body)

    assert result == {"metadata": {"name": "demo"}}
    custom_objects.patch_namespaced_custom_object.assert_awaited_once_with(
        GROUP,
        VERSION,
        "default",
        PLURAL,
        "demo",
        body,
        field_manager=FIELD_MANAGER,
        field_validation="Strict",
        force=False,
        _content_type="application/apply-patch+yaml",
        _request_timeout=7,
    )


@pytest.mark.anyio
async def test_gateway_reads_back_server_side_apply_create_response() -> None:
    custom_objects = SimpleNamespace(
        patch_namespaced_custom_object=AsyncMock(return_value=None),
        get_namespaced_custom_object=AsyncMock(return_value={"metadata": {"name": "demo"}}),
    )
    gateway = KubernetesDeploymentGateway(
        custom_objects,
        SimpleNamespace(close=AsyncMock()),
        5,
    )

    result = await gateway.apply(
        "default",
        "demo",
        {"apiVersion": f"{GROUP}/{VERSION}", "kind": "ModelDeployment"},
    )

    assert result == {"metadata": {"name": "demo"}}
    custom_objects.get_namespaced_custom_object.assert_awaited_once_with(
        GROUP,
        VERSION,
        "default",
        PLURAL,
        "demo",
        _request_timeout=5,
    )


@pytest.mark.anyio
async def test_gateway_delete_is_idempotent_for_not_found() -> None:
    custom_objects = SimpleNamespace(
        delete_namespaced_custom_object=AsyncMock(
            side_effect=ApiException(status=404, reason="Not Found")
        )
    )
    gateway = KubernetesDeploymentGateway(
        custom_objects,
        SimpleNamespace(close=AsyncMock()),
        5,
    )

    deleted = await gateway.delete("default", "missing")

    assert deleted is False


@pytest.mark.anyio
async def test_gateway_preserves_api_status_without_response_body() -> None:
    custom_objects = SimpleNamespace(
        get_namespaced_custom_object=AsyncMock(
            side_effect=ApiException(status=409, reason="Conflict")
        )
    )
    gateway = KubernetesDeploymentGateway(
        custom_objects,
        SimpleNamespace(close=AsyncMock()),
        5,
    )

    with pytest.raises(DeploymentGatewayError) as caught:
        await gateway.get("default", "demo")

    assert caught.value.status == 409
    assert caught.value.reason == "Conflict"


@pytest.mark.anyio
async def test_gateway_readiness_checks_crd_discovery_and_closes() -> None:
    custom_objects = SimpleNamespace(get_api_resources=AsyncMock(return_value={"resources": []}))
    api_client = SimpleNamespace(close=AsyncMock())
    gateway = KubernetesDeploymentGateway(custom_objects, api_client, 3)

    await gateway.check_ready()
    await gateway.close()

    custom_objects.get_api_resources.assert_awaited_once_with(
        GROUP,
        VERSION,
        _request_timeout=3,
    )
    api_client.close.assert_awaited_once_with()
