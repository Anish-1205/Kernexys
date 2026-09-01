"""Bound request bodies and correlate runtime requests."""

from __future__ import annotations

import re
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from runtime_app.metrics import RuntimeMetrics

request_id_context: ContextVar[str] = ContextVar("runtime_request_id", default="")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, metrics: RuntimeMetrics) -> None:
        super().__init__(app)
        self.metrics = metrics

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if _REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid4())
        token = request_id_context.set(request_id)
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        finally:
            if request.url.path == "/v1/infer":
                outcome = "success" if status_code < 400 else "error"
                self.metrics.observe_inference(outcome, perf_counter() - started)
            request_id_context.reset(token)


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = _header(scope, b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                pass

        buffered: list[Message] = []
        total = 0
        more_body = True
        while more_body:
            message = await receive()
            buffered.append(message)
            if message["type"] == "http.disconnect":
                await self.app(scope, _replay(buffered), send)
                return
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                await self._reject(scope, _replay(buffered), send)
                return
            more_body = message.get("more_body", False)

        await self.app(scope, _replay(buffered), send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "request_too_large",
                    "message": f"Request bodies are limited to {self.max_bytes} bytes.",
                    "request_id": request_id_context.get(),
                }
            },
        )
        await response(scope, receive, send)


def _header(scope: Scope, name: bytes) -> str | None:
    for header_name, value in scope.get("headers", []):
        if header_name == name:
            return value.decode("latin-1")
    return None


def _replay(messages: list[Message]) -> Receive:
    iterator = iter(messages)

    async def receive() -> Message:
        try:
            return next(iterator)
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    return receive
