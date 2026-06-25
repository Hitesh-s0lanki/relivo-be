"""Helpers for consistent API error responses and logging."""

import logging
from typing import Any

from src.schemas.chat import ChatErrorResponse


def build_error_response(status: int, message: str, error_tag: str) -> ChatErrorResponse:
    """Build the standard client-facing error response."""
    return ChatErrorResponse(status=status, message=message, error_tag=error_tag)


def log_error_response(
    logger: logging.Logger,
    error: ChatErrorResponse,
    *,
    detail: Any | None = None,
    exc: BaseException | None = None,
) -> None:
    """Log each error property and an aggregate entry with status-aware severity."""
    logger.info("error.status=%s", error.status)
    logger.info("error.message=%s", error.message)
    logger.info("error.error_tag=%s", error.error_tag)
    if detail is not None:
        logger.info("error.detail=%s", detail)

    level = logging.ERROR if error.status >= 500 else logging.INFO
    exc_info = (type(exc), exc, exc.__traceback__) if exc is not None else None
    logger.log(
        level,
        "error response generated status=%s message=%s error_tag=%s detail=%s",
        error.status,
        error.message,
        error.error_tag,
        detail,
        exc_info=exc_info,
    )
