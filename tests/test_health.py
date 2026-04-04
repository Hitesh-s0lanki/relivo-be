from src.schema.health import HealthResponse


def test_health_response_shape():
    response = HealthResponse(status="ok", version="0.1.0", environment="development")
    assert response.status == "ok"
    assert response.version == "0.1.0"
    assert response.environment == "development"


def test_health_response_serializes_to_dict():
    response = HealthResponse(status="ok", version="0.1.0", environment="development")
    data = response.model_dump()
    assert data == {"status": "ok", "version": "0.1.0", "environment": "development"}
