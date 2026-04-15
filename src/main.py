import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.app_config import settings
from src.routes.chat import router as chat_router
from src.routes.conversation import router as conversation_router
from src.routes.health import router as health_router
from src.utils.logger import setup_logger

setup_logger()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s (%s)", settings.app_name, settings.version, settings.environment)
    yield
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(conversation_router)
    return app


app = create_app()
