import uuid
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.dependencies import get_current_user
from app.models.models import User

client = TestClient(app)

mock_user = User(
    id=uuid.uuid4(),
    email="test@omnipost.io",
    full_name="Tester",
    is_active=True,
)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "version" in data


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_templates_categories():
    app.dependency_overrides[get_current_user] = lambda: mock_user
    try:
        response = client.get("/api/v1/templates/categories")
        assert response.status_code == 200
        categories = response.json()
        assert "promotional" in categories
        assert "educational" in categories
        assert "engagement" in categories
        assert "seasonal" in categories
    finally:
        app.dependency_overrides.clear()


def test_templates_unauthorized():
    response = client.get("/api/v1/templates/categories")
    assert response.status_code in [401, 403]
