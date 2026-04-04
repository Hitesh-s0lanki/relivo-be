from fastapi import FastAPI
from src.app_config import settings
from src.routes.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
    )
    app.include_router(health_router)
    return app


app = create_app()
