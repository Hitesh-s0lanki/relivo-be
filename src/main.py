"""FastAPI application entrypoint."""

import inspect
import logging
import os
import sys
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

if __name__ == "__main__" and __package__ is None:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

warnings.filterwarnings(
    "ignore",
    message="The default value of `allowed_objects` will change in a future version.*",
)

load_dotenv()

from src.agents import warm_orchestrator_agent  # noqa: E402
from src.controllers.chat_controller import router as chat_router  # noqa: E402
from src.controllers.conversation_controller import router as conversation_router  # noqa: E402
from src.controllers.health_controller import router as health_router  # noqa: E402
from src.controllers.user_file_controller import router as user_file_router  # noqa: E402
from src.utils.error_response import build_error_response, log_error_response  # noqa: E402

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure application logging for direct script startup."""
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s:%(name)s:%(message)s",
    )


def _error_detail_to_response(
    status: int,
    detail: Any,
    *,
    fallback_message: str,
    fallback_error_tag: str,
) -> dict[str, Any]:
    if isinstance(detail, dict) and {"status", "message", "error_tag"} <= detail.keys():
        return detail

    error = build_error_response(
        status=status,
        message=str(detail or fallback_message),
        error_tag=fallback_error_tag,
    )
    return error.model_dump()


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Return the standard error shape for HTTP exceptions."""
    content = _error_detail_to_response(
        exc.status_code,
        exc.detail,
        fallback_message="request failed",
        fallback_error_tag="http_error",
    )
    error = build_error_response(**content)
    log_error_response(logger, error, detail={"path": request.url.path})
    return JSONResponse(status_code=exc.status_code, content=content)


async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Return the standard error shape for request validation errors."""
    error = build_error_response(
        status=422,
        message="request validation failed",
        error_tag="request_validation_error",
    )
    log_error_response(logger, error, detail={"path": request.url.path, "errors": exc.errors()})
    return JSONResponse(status_code=422, content=error.model_dump())


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Warm reusable application resources at server startup."""
    logger.info("Application startup started")
    agent = warm_orchestrator_agent()
    if inspect.isawaitable(agent):
        agent = await agent
    logger.info(
        "Orchestrator agent warmed name=%s model=%s tools=%s",
        agent.config.name,
        _agent_model_name(agent.config.model),
        len(agent.tools),
    )
    logger.info("Application startup complete")
    yield
    logger.info("Application shutdown complete")


def _agent_model_name(model: Any) -> str:
    """Return a log-safe model name."""
    return str(getattr(model, "model_name", model.__class__.__name__))


def create_app() -> FastAPI:
    """Create and configure the FastAPI app."""
    app = FastAPI(title="Relivo BE Server", lifespan=lifespan)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(conversation_router)
    app.include_router(user_file_router)
    return app


def is_development() -> bool:
    """Return whether the app should run in development mode."""
    environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    return environment in {"dev", "development", "local"}


def run() -> None:
    """Run the FastAPI app through Uvicorn."""
    import uvicorn

    configure_logging()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", str(is_development())).strip().lower() == "true"
    logger.info(
        "Starting Relivo server environment=%s host=%s port=%s reload=%s",
        os.getenv("ENVIRONMENT", "development"),
        host,
        port,
        reload,
    )

    uvicorn.run("src.main:app", host=host, port=port, reload=reload)


app = create_app()


if __name__ == "__main__":
    run()
