"""FastAPI application entrypoint."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

if __name__ == "__main__" and __package__ is None:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from src.routes.chat import router as chat_router

load_dotenv()


def create_app() -> FastAPI:
    """Create and configure the FastAPI app."""
    app = FastAPI(title="Relivo BE Server")
    app.include_router(chat_router)
    return app


def is_development() -> bool:
    """Return whether the app should run in development mode."""
    environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    return environment in {"dev", "development", "local"}


def run() -> None:
    """Run the FastAPI app through Uvicorn."""
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", str(is_development())).strip().lower() == "true"

    uvicorn.run("src.main:app", host=host, port=port, reload=reload)


app = create_app()


if __name__ == "__main__":
    run()
