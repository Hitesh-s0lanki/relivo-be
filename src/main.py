from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.app_config import settings
from src.routes.health import router as health_router
from src.routes.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Future: add startup/shutdown logic here (e.g., DB connection pool warm-up)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(chat_router)
    return app


app = create_app()
