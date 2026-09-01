from __future__ import annotations

import pytest

from app.config import Settings


def test_kubernetes_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KERNEXYS_KUBERNETES_ENABLED", "true")
    monkeypatch.setenv("KERNEXYS_KUBERNETES_CONFIG_MODE", "kubeconfig")
    monkeypatch.setenv("KERNEXYS_KUBECONFIG", "test-kubeconfig")
    monkeypatch.setenv("KERNEXYS_KUBERNETES_CONTEXT", "kind-kernexys")
    monkeypatch.setenv("KERNEXYS_KUBERNETES_REQUEST_TIMEOUT_SECONDS", "9")

    settings = Settings.from_env()

    assert settings.kubernetes_enabled is True
    assert settings.kubernetes_config_mode == "kubeconfig"
    assert settings.kubernetes_kubeconfig == "test-kubeconfig"
    assert settings.kubernetes_context == "kind-kernexys"
    assert settings.kubernetes_request_timeout_seconds == 9


def test_invalid_kubernetes_boolean_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KERNEXYS_KUBERNETES_ENABLED", "sometimes")

    with pytest.raises(ValueError, match="must be a boolean"):
        Settings.from_env()


def test_invalid_kubernetes_config_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KERNEXYS_KUBERNETES_CONFIG_MODE", "anonymous")

    with pytest.raises(ValueError, match=r"in-cluster.*kubeconfig"):
        Settings.from_env()
