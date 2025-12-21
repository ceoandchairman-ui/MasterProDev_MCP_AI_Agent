"""Pytest configuration"""

import pytest
import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock
from mcp_host.state import state_manager

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(autouse=True)
def mock_redis():
    """Mock Redis for testing - runs before each test"""
    # Create mock Redis
    mock_redis_client = AsyncMock()
    mock_redis_client.setex = AsyncMock(return_value=True)
    mock_redis_client.get = AsyncMock(return_value=None)
    mock_redis_client.delete = AsyncMock(return_value=True)
    mock_redis_client.close = AsyncMock()
    mock_redis_client.ping = AsyncMock(return_value=True)
    
    # Inject into StateManager
    state_manager.redis = mock_redis_client
    state_manager.db_pool = None  # No PostgreSQL in tests
    
    yield
    
    # Cleanup
    state_manager.redis = None

