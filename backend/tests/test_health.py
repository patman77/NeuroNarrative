import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint():
    app = create_app()
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "timestamp" in data
    assert "summarizer_enabled" in data
    assert "gpu_available" in data
