"""Runtime process entrypoint."""

from __future__ import annotations

import uvicorn

from runtime_app.config import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "runtime_app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        limit_concurrency=settings.server_limit_concurrency,
        timeout_keep_alive=settings.server_timeout_keep_alive_seconds,
        timeout_graceful_shutdown=settings.server_timeout_graceful_shutdown_seconds,
        access_log=False,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
