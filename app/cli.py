"""Small HTTP CLI for deployment operations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kernexysctl")
    parser.add_argument(
        "--api-url",
        default=os.getenv("KERNEXYS_API_URL", "http://127.0.0.1:8000"),
        help="Kernexys control API base URL",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout in seconds")
    commands = parser.add_subparsers(dest="command", required=True)

    deploy = commands.add_parser("deploy", help="create or update desired deployment state")
    _deployment_identity(deploy)
    deploy.add_argument("--model", required=True)
    deploy.add_argument("--version", required=True)
    deploy.add_argument("--replicas", type=int, default=1)
    deploy.add_argument("--port", type=int, default=8080)
    deploy.add_argument("--request", action="append", default=[], metavar="NAME=QUANTITY")
    deploy.add_argument("--limit", action="append", default=[], metavar="NAME=QUANTITY")

    status = commands.add_parser("status", help="read deployment desired and observed state")
    _deployment_identity(status)

    delete = commands.add_parser("delete", help="delete desired deployment state")
    _deployment_identity(delete)

    rollback = commands.add_parser("rollback", help="roll back to a registered model version")
    _deployment_identity(rollback)
    rollback.add_argument("--version", required=True)
    return parser


def run(
    argv: Sequence[str] | None = None,
    opener: Callable[..., Any] = urlopen,
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    path = _deployment_path(arguments.namespace, arguments.name)
    method = "GET"
    payload: dict[str, Any] | None = None
    if arguments.command == "deploy":
        method = "PUT"
        payload = {
            "model": arguments.model,
            "version": arguments.version,
            "replicas": arguments.replicas,
            "port": arguments.port,
            "resources": {
                "requests": _key_values(parser, arguments.request),
                "limits": _key_values(parser, arguments.limit),
            },
        }
    elif arguments.command == "delete":
        method = "DELETE"
    elif arguments.command == "rollback":
        method = "POST"
        path += "/rollback"
        payload = {"version": arguments.version}

    request = Request(
        arguments.api_url.rstrip("/") + path,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Request-ID": f"kernexysctl-{uuid4()}",
        },
        method=method,
    )
    try:
        with opener(request, timeout=arguments.timeout) as response:
            content = response.read()
    except HTTPError as exc:
        content = exc.read()
        _print_error(content, f"control API returned HTTP {exc.code}")
        return 1
    except URLError as exc:
        print(f"control API request failed: {exc.reason}", file=sys.stderr)
        return 1

    if content:
        print(json.dumps(json.loads(content), indent=2, sort_keys=True))
    else:
        print(
            json.dumps({"deleted": True, "name": arguments.name, "namespace": arguments.namespace})
        )
    return 0


def main() -> None:
    raise SystemExit(run())


def _deployment_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name")
    parser.add_argument("--namespace", default="default")


def _deployment_path(namespace: str, name: str) -> str:
    return f"/v1/deployments/{quote(namespace, safe='')}/{quote(name, safe='')}"


def _key_values(parser: argparse.ArgumentParser, values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        name, separator, quantity = value.partition("=")
        if not separator or not name or not quantity:
            parser.error(f"resource value must be NAME=QUANTITY: {value}")
        result[name] = quantity
    return result


def _print_error(content: bytes, fallback: str) -> None:
    try:
        parsed = json.loads(content)
        message = parsed.get("error", {}).get("message", fallback)
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        message = fallback
    print(message, file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    main()
