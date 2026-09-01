"""Run the control API with bounded Uvicorn defaults."""

from __future__ import annotations

import uvicorn

from app.config import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        log_config=None,
        limit_concurrency=settings.server_limit_concurrency,
        timeout_keep_alive=settings.server_timeout_keep_alive_seconds,
        timeout_graceful_shutdown=settings.server_timeout_graceful_shutdown_seconds,
    )


if __name__ == "__main__":
    main()
