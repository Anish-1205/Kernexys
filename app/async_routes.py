"""Bounded asynchronous inference HTTP resources."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Header, Request, Response

from app.async_queue import AsyncQueueError, RedisInferenceQueue
from app.deployment_routes import Gateway, NamespacedResourceName, _deployment_error
from app.errors import ApiError
from app.kubernetes import DeploymentGatewayError
from app.schemas import AsyncInferenceJob, AsyncInferenceRequest

async_router = APIRouter(prefix="/v1/async-inference", tags=["async inference"])


def _queue(request: Request) -> RedisInferenceQueue:
    queue = request.app.state.async_queue
    if queue is None:
        raise ApiError(503, "async_inference_disabled", "Asynchronous inference is not enabled.")
    return queue


@async_router.post("/{namespace}/{name}/jobs", response_model=AsyncInferenceJob)
async def enqueue_job(
    namespace: NamespacedResourceName,
    name: NamespacedResourceName,
    body: AsyncInferenceRequest,
    request: Request,
    response: Response,
    gateway: Gateway,
    idempotency_key: Annotated[str | None, Header(max_length=128)] = None,
) -> AsyncInferenceJob:
    try:
        deployment = await gateway.get(namespace, name)
    except DeploymentGatewayError as exc:
        raise _deployment_error(exc, namespace, name) from exc
    status = deployment.get("status", {})
    endpoint = status.get("endpoint")
    available = any(
        condition.get("type") == "Available" and condition.get("status") == "True"
        for condition in status.get("conditions", [])
    )
    if not available or not isinstance(endpoint, str) or not endpoint:
        raise ApiError(409, "deployment_not_ready", "The model deployment is not ready.")

    job_id = str(uuid4())
    if idempotency_key:
        identity = f"{namespace}/{name}/{idempotency_key}".encode()
        job_id = hashlib.sha256(identity).hexdigest()
    try:
        result = await _queue(request).enqueue(
            job_id,
            {"deployment": f"{namespace}/{name}", "endpoint": endpoint, "text": body.text},
        )
    except AsyncQueueError as exc:
        raise ApiError(503, "redis_unavailable", "The asynchronous queue is unavailable.") from exc
    if result.full:
        raise ApiError(429, "queue_full", "The asynchronous inference queue is full.")
    if result.conflict:
        raise ApiError(
            409,
            "idempotency_conflict",
            "The idempotency key was already used for a different inference request.",
        )
    response.status_code = 202 if result.created else 200
    return AsyncInferenceJob(job_id=job_id, status="queued")


@async_router.get("/jobs/{job_id}", response_model=AsyncInferenceJob)
async def get_job(job_id: str, request: Request) -> AsyncInferenceJob:
    if len(job_id) > 64 or not job_id.replace("-", "").isalnum():
        raise ApiError(404, "job_not_found", "The inference job was not found.")
    try:
        value = await _queue(request).get(job_id)
    except AsyncQueueError as exc:
        raise ApiError(503, "redis_unavailable", "The asynchronous queue is unavailable.") from exc
    if value is None:
        raise ApiError(404, "job_not_found", "The inference job was not found.")
    result = json.loads(value["result"]) if "result" in value else None
    return AsyncInferenceJob(
        job_id=job_id,
        status=value["status"],
        result=result,
        error=value.get("error"),
    )
