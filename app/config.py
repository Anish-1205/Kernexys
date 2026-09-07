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


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


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
    kubernetes_enabled: bool = False
    kubernetes_config_mode: str = "in-cluster"
    kubernetes_kubeconfig: str | None = None
    kubernetes_context: str | None = None
    kubernetes_request_timeout_seconds: int = 5
    async_inference_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    async_queue_capacity: int = 1_000
    async_job_ttl_seconds: int = 3_600
    redis_socket_timeout_seconds: int = 5
    async_worker_concurrency: int = 4
    async_inference_timeout_seconds: int = 30
    metrics_enabled: bool = True
    metrics_port: int = 8001
    logging_format: str = "json"
    logging_correlation_id_enabled: bool = True

    def __post_init__(self) -> None:
        if self.kubernetes_config_mode not in {"in-cluster", "kubeconfig"}:
            raise ValueError("kubernetes_config_mode must be 'in-cluster' or 'kubeconfig'")

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
            kubernetes_enabled=_boolean("KERNEXYS_KUBERNETES_ENABLED", False),
            kubernetes_config_mode=os.getenv(
                "KERNEXYS_KUBERNETES_CONFIG_MODE", "in-cluster"
            ).lower(),
            kubernetes_kubeconfig=os.getenv("KERNEXYS_KUBECONFIG"),
            kubernetes_context=os.getenv("KERNEXYS_KUBERNETES_CONTEXT"),
            kubernetes_request_timeout_seconds=_positive_int(
                "KERNEXYS_KUBERNETES_REQUEST_TIMEOUT_SECONDS", 5
            ),
            async_inference_enabled=_boolean("KERNEXYS_ASYNC_INFERENCE_ENABLED", False),
            redis_url=os.getenv("KERNEXYS_REDIS_URL", "redis://localhost:6379/0"),
            async_queue_capacity=_positive_int("KERNEXYS_ASYNC_QUEUE_CAPACITY", 1_000),
            async_job_ttl_seconds=_positive_int("KERNEXYS_ASYNC_JOB_TTL_SECONDS", 3_600),
            redis_socket_timeout_seconds=_positive_int("KERNEXYS_REDIS_SOCKET_TIMEOUT_SECONDS", 5),
            async_worker_concurrency=_positive_int("KERNEXYS_ASYNC_WORKER_CONCURRENCY", 4),
            async_inference_timeout_seconds=_positive_int(
                "KERNEXYS_ASYNC_INFERENCE_TIMEOUT_SECONDS", 30
            ),
            metrics_enabled=_boolean("KERNEXYS_METRICS_ENABLED", True),
            metrics_port=_positive_int("KERNEXYS_METRICS_PORT", 8001),
            logging_format=os.getenv("KERNEXYS_LOGGING_FORMAT", "json").lower(),
            logging_correlation_id_enabled=_boolean(
                "KERNEXYS_LOGGING_CORRELATION_ID_ENABLED", True
            ),
        )
