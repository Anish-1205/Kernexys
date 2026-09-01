"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app import __version__
from app.async_queue import RedisInferenceQueue
from app.async_routes import async_router
from app.config import Settings
from app.database import create_database_engine, create_session_factory
from app.deployment_routes import deployment_router
from app.errors import install_error_handlers
from app.kubernetes import DeploymentGateway, KubernetesDeploymentGateway
from app.logging_config import configure_logging
from app.middleware import RequestBodyLimitMiddleware, RequestContextMiddleware
from app.routes import health_router, registry_router


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    deployment_gateway: DeploymentGateway | None = None,
    async_queue: RedisInferenceQueue | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    configure_logging(resolved_settings.log_level)
    owns_engine = engine is None
    database_engine = engine or create_database_engine(resolved_settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = resolved_settings
        application.state.engine = database_engine
        application.state.session_factory = create_session_factory(database_engine)
        owns_gateway = deployment_gateway is None and resolved_settings.kubernetes_enabled
        gateway = deployment_gateway
        owns_queue = async_queue is None and resolved_settings.async_inference_enabled
        queue = async_queue
        try:
            if gateway is None and resolved_settings.kubernetes_enabled:
                gateway = await KubernetesDeploymentGateway.create(resolved_settings)
            application.state.deployment_gateway = gateway
            if queue is None and resolved_settings.async_inference_enabled:
                queue = RedisInferenceQueue.create(
                    resolved_settings.redis_url,
                    resolved_settings.async_queue_capacity,
                    resolved_settings.async_job_ttl_seconds,
                    resolved_settings.redis_socket_timeout_seconds,
                )
            application.state.async_queue = queue
            yield
        finally:
            try:
                try:
                    if owns_queue and queue is not None:
                        await queue.close()
                finally:
                    if owns_gateway and gateway is not None:
                        await gateway.close()
            finally:
                if owns_engine:
                    await database_engine.dispose()

    application = FastAPI(
        title="Kernexys Control API",
        summary="Local-first AI model registry and deployment control plane.",
        version=__version__,
        lifespan=lifespan,
    )
    application.add_middleware(
        RequestBodyLimitMiddleware, max_bytes=resolved_settings.max_request_bytes
    )
    application.add_middleware(RequestContextMiddleware)
    install_error_handlers(application)
    application.include_router(health_router)
    application.include_router(registry_router)
    application.include_router(deployment_router)
    application.include_router(async_router)
    return application


app = create_app()
