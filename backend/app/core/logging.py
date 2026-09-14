"""Structured logging setup.

Events are emitted as JSON with a stable ``event`` name and a ``request_id`` bound for
the lifetime of a request, so a single chat turn can be traced end to end.

Secrets are never logged: providers log only their name, model and latency, and the
config redaction helper below is the single place allowed to summarise credentials.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_configured = False


def configure_logging(level: str = "INFO", log_format: str = "json") -> None:
    global _configured
    if _configured:
        return

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=getattr(logging, level.upper(), logging.INFO))
    # uvicorn's own access log duplicates our request events.
    logging.getLogger("uvicorn.access").disabled = True

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer() if log_format == "json" else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def describe_secret(value: str | None) -> str:
    """Report whether a credential is configured without revealing any of it."""
    return "configured" if value else "missing"
