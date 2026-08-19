"""Test main application endpoints."""

import pytest
from fastapi.testclient import TestClient

from app import __version__


def test_root_endpoint(client: TestClient) -> None:
    """Test root endpoint returns service information."""
    response = client.get("/")
    assert response.status_code == 200
    
    data = response.json()
    assert data["service"] == "TGO-Tech AI Service"
    assert data["version"] == __version__
    assert "description" in data


def test_health_check(client: TestClient) -> None:
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "tgo-ai-service"
    assert data["version"] == __version__


def test_docs_endpoint(client: TestClient) -> None:
    """Test API documentation endpoint."""
    response = client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_openapi_schema(client: TestClient) -> None:
    """Test OpenAPI schema endpoint."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    
    schema = response.json()
    assert schema["info"]["title"] == "TGO-Tech AI Service"
    assert schema["info"]["version"] == __version__
