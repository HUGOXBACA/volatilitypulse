# ─────────────────────────────────────────────────────────────────────────────
# Structured logging for VolPulse.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import sys
import threading
import types
from collections.abc import MutableMapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Self, cast

import structlog
from structlog.types import Processor

logger = logging.getLogger(__name__)

__all__ = [
    "LogContext",
    "LogContextManager",
    "bind_context",
    "clear_context",
    "get_context",
    "get_logger",
    "setup_logging",
]

# Context variable for request-scoped logging context
_context_var: ContextVar[dict[str, Any]] = ContextVar("_log_context")
_context_var.set({})


@dataclass(frozen=True, slots=True)
class LogContext:
    """Immutable log context that can be bound to log entries."""

    service: str | None = None
    operation: str | None = None
    request_id: str | None = None
    user_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in self.__dict__.items() if v is not None}

    def merge(self, other: LogContext) -> LogContext:
        """Merge with another context, other takes precedence."""
        return LogContext(
            service=other.service or self.service,
            operation=other.operation or self.operation,
            request_id=other.request_id or self.request_id,
            user_id=other.user_id or self.user_id,
            trace_id=other.trace_id or self.trace_id,
            span_id=other.span_id or self.span_id,
            extra={**self.extra, **other.extra},
        )


# Thread-local storage for contexts that need thread isolation
_thread_contexts: dict[int, LogContext] = {}
_thread_lock = threading.Lock()


def setup_logging(
    level: int = logging.INFO,
    json_format: bool = False,
    add_thread_name: bool = True,
    add_process_info: bool = False,
) -> None:
    """Configure structlog for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        json_format: Whether to output JSON lines
        add_thread_name: Include thread name in logs (deprecated, no-op)
        add_process_info: Include process ID in logs
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    renderer: Any = (
        structlog.processors.JSONRenderer() if json_format else structlog.dev.ConsoleRenderer(colors=True)
    )

    handler.setFormatter(logging.Formatter("%(message)s"))

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level)

    # Configure structlog
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]

    # add_thread_name is deprecated - structlog no longer has ThreadLocal processor

    if add_process_info:
        processors.append(_add_process_info)

    processors.append(renderer)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    log = structlog.get_logger()
    log.info("Logging configured", level=level, json_format=json_format)


def _add_process_info(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Add process info to log entries."""
    import os
    event_dict["pid"] = os.getpid()
    return event_dict


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Structured logger with context binding support
    """
    return cast(structlog.BoundLogger, structlog.get_logger(name))


def bind_context(**kwargs: Any) -> None:
    """Bind key-value pairs to the current logging context.

    Args:
        **kwargs: Key-value pairs to bind to the current context
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear the current logging context."""
    structlog.contextvars.clear_contextvars()


def get_context() -> dict[str, Any]:
    """Get the current logging context."""
    return structlog.contextvars.get_contextvars().copy()


@dataclass(slots=True)
class LogContextManager:
    """Context manager for temporarily binding logging context.

    Usage:
        with LogContextManager(request_id="abc123", user_id="user1"):
            logger.info("Processing request")
    """

    context: LogContext
    _previous: dict[str, Any] = field(default_factory=dict, init=False)

    def __enter__(self) -> Self:
        self._previous = structlog.contextvars.get_contextvars().copy()
        new_context = self.context
        bind_context(**new_context.to_dict())
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        clear_context()
        if self._previous:
            bind_context(**self._previous)