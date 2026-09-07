"""Structured logging for Kernexys with correlation IDs."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default=str(uuid.uuid4()))


def get_correlation_id() -> str:
    """Get the current request correlation ID."""
    return correlation_id_var.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID for the current context."""
    correlation_id_var.set(correlation_id)


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_obj: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }

        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        # Add any extra fields from the record
        if hasattr(record, "extra_fields"):
            log_obj.update(record.extra_fields)

        return json.dumps(log_obj)


class ContextAwareLogger(logging.Logger):
    """Logger that automatically includes correlation ID in messages."""

    def _log(
        self,
        level: int,
        msg: str,
        args: tuple[Any, ...],
        exc_info: Any = None,
        extra: dict[str, Any] | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
    ) -> None:
        """Override _log to add correlation ID without dropping caller extras."""
        fields: dict[str, Any] = {"correlation_id": get_correlation_id()}
        if extra:
            fields.update(extra.get("extra_fields", {}))
            fields.update({key: value for key, value in extra.items() if key != "extra_fields"})

        super()._log(
            level,
            msg,
            args,
            exc_info=exc_info,
            extra={"extra_fields": fields},
            stack_info=stack_info,
            stacklevel=stacklevel + 1,
        )


def configure_logging(log_level: str, json_format: bool = True) -> None:
    """Configure structured logging for the application."""
    # Create root logger
    logging.setLoggerClass(ContextAwareLogger)
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create stderr handler
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(getattr(logging, log_level.upper()))

    if json_format:
        formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] - %(message)s"
        )

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)
