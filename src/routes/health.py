from fastapi import APIRouter
from src.app_config import settings
from src.schema.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def get_health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.version,
        environment=settings.environment,
    )
