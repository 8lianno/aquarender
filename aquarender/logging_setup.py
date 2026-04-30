"""Configure structlog. Console renderer in dev, JSON in prod."""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog


def configure_logging() -> None:
    level_name = os.environ.get("AQUARENDER_LOG_LEVEL", "info").upper()
    level = getattr(logging, level_name, logging.INFO)
    json_output = os.environ.get("AQUARENDER_LOG_JSON", "false").lower() == "true"

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Return a structlog logger. Type is `Any` because the structlog
    bound-logger type changes shape with the wrapper class we configure."""
    return structlog.get_logger(name)
