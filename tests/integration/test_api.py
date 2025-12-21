"""Integration tests for API endpoints"""

import pytest
from fastapi.testclient import TestClient
from mcp_host.main import app

client = TestClient(app)


def test_health_check():
    """Test health endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "services" in data


def test_login():
    """Test login endpoint"""
    response = client.post("/login", json={
        "email": "test@example.com",
        "password": "test_password_123"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_chat_without_auth():
    """Test chat endpoint without authentication"""
    response = client.post("/chat", json={
        "message": "Hello"
    })
    assert response.status_code == 401


def test_profile_without_auth():
    """Test profile endpoint without authentication"""
    response = client.get("/user/profile")
    assert response.status_code == 401


def test_conversations_without_auth():
    """Test conversations endpoint without authentication"""
    response = client.get("/conversations")
    assert response.status_code == 401
