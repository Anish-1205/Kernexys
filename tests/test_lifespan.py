from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings


def test_gateway_startup_failure_disposes_owned_database_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = AsyncMock()
    monkeypatch.setattr(main_module, "create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(main_module, "create_session_factory", lambda _engine: object())
    create_gateway = AsyncMock(side_effect=RuntimeError("Kubernetes configuration failed"))
    monkeypatch.setattr(main_module.KubernetesDeploymentGateway, "create", create_gateway)
    application = main_module.create_app(Settings(kubernetes_enabled=True))

    with pytest.raises(RuntimeError, match="Kubernetes configuration failed"):
        with TestClient(application):
            pass

    engine.dispose.assert_awaited_once()


def test_gateway_close_failure_still_disposes_owned_database_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = AsyncMock()
    gateway = AsyncMock()
    gateway.close.side_effect = RuntimeError("Kubernetes client close failed")
    monkeypatch.setattr(main_module, "create_database_engine", lambda _settings: engine)
    monkeypatch.setattr(main_module, "create_session_factory", lambda _engine: object())
    monkeypatch.setattr(
        main_module.KubernetesDeploymentGateway,
        "create",
        AsyncMock(return_value=gateway),
    )
    application = main_module.create_app(Settings(kubernetes_enabled=True))

    with pytest.raises(RuntimeError, match="Kubernetes client close failed"):
        with TestClient(application):
            pass

    engine.dispose.assert_awaited_once()
