from fastapi.testclient import TestClient
from src.main import create_app
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


def _make_client():
    return TestClient(create_app())


def test_get_health_returns_200():
    client = _make_client()
    response = client.get("/health")
    assert response.status_code == 200


def test_get_health_response_body():
    client = _make_client()
    response = client.get("/health")
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "environment" in body
