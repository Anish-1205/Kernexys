"""FastAPI application for the deterministic reference model runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, StringConstraints

from runtime_app import __version__
from runtime_app.classifier import SentimentClassifier
from runtime_app.config import Settings
from runtime_app.metrics import RuntimeMetrics
from runtime_app.middleware import (
    RequestBodyLimitMiddleware,
    RequestContextMiddleware,
    request_id_context,
)

BoundedText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
]


class InferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: BoundedText


class InferResponse(BaseModel):
    model: str
    version: str
    label: str
    confidence: float
    request_id: str


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    metrics = RuntimeMetrics(resolved_settings.model_name, resolved_settings.model_version)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.ready = False
        application.state.classifier = SentimentClassifier(resolved_settings.model_version)
        application.state.ready = True
        try:
            yield
        finally:
            application.state.ready = False

    application = FastAPI(
        title="Kernexys Reference Model Runtime",
        version=__version__,
        lifespan=lifespan,
    )
    application.state.ready = False
    application.state.settings = resolved_settings
    application.state.metrics = metrics
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=resolved_settings.max_request_bytes,
    )
    application.add_middleware(RequestContextMiddleware, metrics=metrics)

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The inference request did not satisfy the runtime schema.",
                    "request_id": request_id_context.get(),
                    "details": exc.errors(),
                }
            },
        )

    @application.get("/health/live")
    async def liveness() -> dict[str, str]:
        return {"status": "alive"}

    @application.get("/health/ready")
    async def readiness(request: Request) -> dict[str, str]:
        if not request.app.state.ready:
            raise HTTPException(status_code=503, detail="model runtime is not ready")
        return {
            "status": "ready",
            "model": resolved_settings.model_name,
            "version": resolved_settings.model_version,
        }

    @application.post("/v1/infer", response_model=InferResponse)
    async def infer(payload: InferRequest, request: Request) -> InferResponse:
        if not request.app.state.ready:
            raise HTTPException(status_code=503, detail="model runtime is not ready")
        prediction = request.app.state.classifier.predict(payload.text)
        return InferResponse(
            model=resolved_settings.model_name,
            version=resolved_settings.model_version,
            label=prediction.label,
            confidence=prediction.confidence,
            request_id=request_id_context.get(),
        )

    @application.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    return application


app = create_app()
