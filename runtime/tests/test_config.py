from __future__ import annotations

import pytest

from runtime_app.config import Settings


def test_runtime_rejects_declared_and_baked_version_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match"):
        Settings(model_version="v2", baked_model_version="v1")


@pytest.mark.parametrize("name", ["Bad_Name", "-sentiment", "sentiment-"])
def test_runtime_rejects_invalid_model_name(name: str) -> None:
    with pytest.raises(ValueError, match="Kubernetes name"):
        Settings(model_name=name)


def test_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KERNEXYS_BAKED_MODEL_VERSION", "v2")
    monkeypatch.setenv("KERNEXYS_MODEL_VERSION", "v2")
    monkeypatch.setenv("KERNEXYS_RUNTIME_PORT", "9090")

    settings = Settings.from_env()

    assert settings.model_version == "v2"
    assert settings.server_port == 9090
