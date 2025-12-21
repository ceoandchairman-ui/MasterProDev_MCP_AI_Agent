"""Basic unit tests for auth module"""

import pytest
from mcp_host.auth import hash_password, verify_password, create_access_token, decode_token


def test_hash_password():
    """Test password hashing"""
    password = "test_password_123"
    hashed = hash_password(password)
    assert hashed != password
    assert len(hashed) > 0


def test_verify_password():
    """Test password verification"""
    password = "test_password_123"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True
    assert verify_password("wrong_password", hashed) is False


def test_create_and_decode_token():
    """Test JWT token creation and decoding"""
    data = {"sub": "user_123", "email": "test@example.com"}
    token = create_access_token(data)
    
    assert token is not None
    decoded = decode_token(token)
    assert decoded is not None
    assert decoded["sub"] == "user_123"
    assert decoded["email"] == "test@example.com"


def test_decode_invalid_token():
    """Test decoding invalid token"""
    decoded = decode_token("invalid_token")
    assert decoded is None
