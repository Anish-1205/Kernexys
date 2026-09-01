"""Environment-backed control API configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


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
    """Validated process configuration.

    Values are deliberately read once at process startup so that configuration is
    stable for the lifetime of a running API instance.
    """

    database_url: str = "postgresql+asyncpg://kernexys:kernexys@localhost:5432/kernexys"
    log_level: str = "INFO"
    max_request_bytes: int = 1_048_576
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_command_timeout_seconds: int = 10
    readiness_timeout_seconds: int = 2
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    server_limit_concurrency: int = 100
    server_timeout_keep_alive_seconds: int = 5
    server_timeout_graceful_shutdown_seconds: int = 20

    @classmethod
    def from_env(cls) -> Settings:
        log_level = os.getenv("KERNEXYS_LOG_LEVEL", "INFO").upper()
        if log_level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("KERNEXYS_LOG_LEVEL is invalid")

        return cls(
            database_url=os.getenv(
                "KERNEXYS_DATABASE_URL",
                "postgresql+asyncpg://kernexys:kernexys@localhost:5432/kernexys",
            ),
            log_level=log_level,
            max_request_bytes=_positive_int("KERNEXYS_MAX_REQUEST_BYTES", 1_048_576),
            database_pool_size=_positive_int("KERNEXYS_DATABASE_POOL_SIZE", 5),
            database_max_overflow=_positive_int("KERNEXYS_DATABASE_MAX_OVERFLOW", 5),
            database_command_timeout_seconds=_positive_int(
                "KERNEXYS_DATABASE_COMMAND_TIMEOUT_SECONDS", 10
            ),
            readiness_timeout_seconds=_positive_int("KERNEXYS_READINESS_TIMEOUT_SECONDS", 2),
            server_host=os.getenv("KERNEXYS_SERVER_HOST", "0.0.0.0"),
            server_port=_positive_int("KERNEXYS_SERVER_PORT", 8000),
            server_limit_concurrency=_positive_int("KERNEXYS_SERVER_LIMIT_CONCURRENCY", 100),
            server_timeout_keep_alive_seconds=_positive_int(
                "KERNEXYS_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS", 5
            ),
            server_timeout_graceful_shutdown_seconds=_positive_int(
                "KERNEXYS_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS", 20
            ),
        )
