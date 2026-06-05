"""FastAPI application entrypoint."""

from fastapi import FastAPI

from src.routes.chat import router as chat_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI app."""
    app = FastAPI(title="Relivo BE Server")
    app.include_router(chat_router)
    return app


app = create_app()
