"""Environment-backed model runtime configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

_MODEL_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    model_name: str = "sentiment"
    model_version: str = "v1"
    baked_model_version: str = "v1"
    max_request_bytes: int = 16_384
    server_host: str = "0.0.0.0"
    server_port: int = 8080
    server_limit_concurrency: int = 32
    server_timeout_keep_alive_seconds: int = 5
    server_timeout_graceful_shutdown_seconds: int = 20

    def __post_init__(self) -> None:
        if not _MODEL_NAME_PATTERN.fullmatch(self.model_name) or len(self.model_name) > 63:
            raise ValueError("KERNEXYS_MODEL_NAME must be a valid lowercase Kubernetes name")
        if self.baked_model_version not in {"v1", "v2"}:
            raise ValueError("KERNEXYS_BAKED_MODEL_VERSION must be v1 or v2")
        if self.model_version != self.baked_model_version:
            raise ValueError(
                "KERNEXYS_MODEL_VERSION does not match the version baked into this image"
            )
        for name, value in {
            "max_request_bytes": self.max_request_bytes,
            "server_port": self.server_port,
            "server_limit_concurrency": self.server_limit_concurrency,
            "server_timeout_keep_alive_seconds": self.server_timeout_keep_alive_seconds,
            "server_timeout_graceful_shutdown_seconds": (
                self.server_timeout_graceful_shutdown_seconds
            ),
        }.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")
        if self.server_port > 65535:
            raise ValueError("server_port must not exceed 65535")

    @classmethod
    def from_env(cls) -> Settings:
        baked_version = os.getenv("KERNEXYS_BAKED_MODEL_VERSION", "v1")
        return cls(
            model_name=os.getenv("KERNEXYS_MODEL_NAME", "sentiment"),
            model_version=os.getenv("KERNEXYS_MODEL_VERSION", baked_version),
            baked_model_version=baked_version,
            max_request_bytes=_positive_int("KERNEXYS_MAX_REQUEST_BYTES", 16_384),
            server_host=os.getenv("KERNEXYS_RUNTIME_HOST", "0.0.0.0"),
            server_port=_positive_int("KERNEXYS_RUNTIME_PORT", 8080),
            server_limit_concurrency=_positive_int("KERNEXYS_RUNTIME_LIMIT_CONCURRENCY", 32),
            server_timeout_keep_alive_seconds=_positive_int(
                "KERNEXYS_RUNTIME_TIMEOUT_KEEP_ALIVE_SECONDS", 5
            ),
            server_timeout_graceful_shutdown_seconds=_positive_int(
                "KERNEXYS_RUNTIME_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS", 20
            ),
        )
