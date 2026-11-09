"""Audit logging and timing for LeaveDesk (FR-9)."""

import functools
import inspect
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from enum import Enum

logger = logging.getLogger("leavedesk")


class Timer:
    """Holds the elapsed time of a timed operation, in milliseconds."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        self.elapsed_ms: float = 0.0


@contextmanager
def timed(operation: str) -> Iterator[Timer]:
    """Time the code inside a with block, even if it raises an error.

    Example:
        with timed("load data") as timer:
            ...
        print(timer.elapsed_ms)
    """
    timer = Timer(operation)
    start = time.perf_counter()
    try:
        yield timer
    finally:
        timer.elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("TIMER %s took %.2f ms", operation, timer.elapsed_ms)


def _short(value) -> str:
    """Show enums and dates simply, such as ANNUAL and 2026-11-16."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    return repr(value)


# Free text can hold private details, such as a medical reason for sick leave,
# so it never goes into the logs.
REDACTED_ARGUMENTS = {"reason", "note", "password"}
# Not useful in a log line.
SKIPPED_ARGUMENTS = {"self", "outbox"}


def _describe_call(func, args, kwargs) -> str:
    try:
        arguments = inspect.signature(func).bind_partial(*args, **kwargs).arguments
    except TypeError:  # the call itself is wrong; Python will raise it next
        arguments = dict(enumerate(args)) | kwargs

    parts = []
    for name, value in arguments.items():
        if name in SKIPPED_ARGUMENTS:
            continue
        text = "<redacted>" if name in REDACTED_ARGUMENTS else _short(value)
        parts.append(f"{name}={text}" if name in kwargs else text)
    return f"{func.__qualname__}({', '.join(parts)})"


def audit(func):
    """Log every call: its arguments, whether it worked, and how long it took.

    Works on both normal and async functions.
    """
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            call = _describe_call(func, args, kwargs)
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
            except Exception as error:
                _log_failure(call, error, start)
                raise
            _log_success(call, start)
            return result

        return async_wrapper

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        call = _describe_call(func, args, kwargs)
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except Exception as error:
            _log_failure(call, error, start)
            raise
        _log_success(call, start)
        return result

    return wrapper


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _log_success(call: str, start: float) -> None:
    logger.info("AUDIT %s -> OK in %.2f ms", call, _elapsed_ms(start))


def _log_failure(call: str, error: Exception, start: float) -> None:
    logger.warning(
        "AUDIT %s -> FAILED in %.2f ms with %s: %s",
        call,
        _elapsed_ms(start),
        type(error).__name__,
        error,
    )
