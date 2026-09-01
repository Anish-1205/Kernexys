from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from urllib.error import HTTPError

from app.cli import run


class FakeResponse:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.content = b"" if payload is None else json.dumps(payload).encode()

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.content


def test_deploy_command_builds_bounded_resource_request(capsys: Any) -> None:
    captured: dict[str, Any] = {}

    def opener(request: Any, timeout: float) -> FakeResponse:
        captured.update(request=request, timeout=timeout)
        return FakeResponse({"name": "sentiment", "namespace": "demo"})

    result = run(
        [
            "--api-url",
            "http://api.example",
            "--timeout",
            "4",
            "deploy",
            "sentiment",
            "--namespace",
            "demo",
            "--model",
            "sentiment",
            "--version",
            "v2",
            "--replicas",
            "3",
            "--request",
            "cpu=100m",
        ],
        opener=opener,
    )

    request = captured["request"]
    assert result == 0
    assert request.full_url == "http://api.example/v1/deployments/demo/sentiment"
    assert request.method == "PUT"
    assert captured["timeout"] == 4
    assert json.loads(request.data) == {
        "model": "sentiment",
        "version": "v2",
        "replicas": 3,
        "port": 8080,
        "resources": {"requests": {"cpu": "100m"}, "limits": {}},
    }
    assert '"namespace": "demo"' in capsys.readouterr().out


def test_delete_command_handles_empty_204_response(capsys: Any) -> None:
    result = run(["delete", "demo"], opener=lambda *_args, **_kwargs: FakeResponse())

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "deleted": True,
        "name": "demo",
        "namespace": "default",
    }


def test_cli_prints_structured_api_error_without_traceback(capsys: Any) -> None:
    content = json.dumps({"error": {"message": "Model version was not found."}}).encode()

    def failing_opener(*_args: Any, **_kwargs: Any) -> FakeResponse:
        raise HTTPError("http://api", 404, "Not Found", {}, BytesIO(content))

    result = run(["status", "missing"], opener=failing_opener)

    assert result == 1
    assert capsys.readouterr().err.strip() == "Model version was not found."
