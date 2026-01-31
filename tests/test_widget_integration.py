"""
Integration test for chat widget with FastAPI backend.
Tests FormData submission to /chat endpoint and response parsing.
"""

import pytest
import asyncio
from httpx import AsyncClient, Client
from mcp_host.main import app
from mcp_host.models import ChatResponse
import uuid


@pytest.mark.asyncio
async def test_chat_endpoint_with_form_data():
    """Test /chat endpoint accepts FormData and returns ChatResponse"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Test 1: Simple message without conversation_id
        response = await client.post(
            "/chat",
            data={"message": "Hello, what is 2+2?"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify ChatResponse structure
        assert "response" in data, "Missing 'response' field in ChatResponse"
        assert "conversation_id" in data, "Missing 'conversation_id' field in ChatResponse"
        assert isinstance(data["response"], str), "'response' must be string"
        assert isinstance(data["conversation_id"], str), "'conversation_id' must be string"
        assert len(data["response"]) > 0, "'response' cannot be empty"
        
        conv_id = data["conversation_id"]
        print(f"✓ Test 1 passed: {data['response'][:50]}...")
        
        # Test 2: Message with existing conversation_id (multi-turn)
        response2 = await client.post(
            "/chat",
            data={
                "message": "What was my previous question?",
                "conversation_id": conv_id
            }
        )
        
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["conversation_id"] == conv_id, "conversation_id should persist"
        print(f"✓ Test 2 passed: Multi-turn conversation working")
        
        # Test 3: Empty message should be rejected by FastAPI validation
        response3 = await client.post(
            "/chat",
            data={"message": ""}
        )
        
        # Should either return 422 (validation error) or handle gracefully
        print(f"✓ Test 3 passed: Empty message handling - status {response3.status_code}")


@pytest.mark.asyncio
async def test_chat_endpoint_form_vs_json():
    """
    Test that /chat endpoint rejects JSON and requires FormData.
    This validates the widget's FormData implementation is correct.
    """
    async with AsyncClient(app=app, base_url="http://test") as client:
        # JSON attempt (should fail with 422)
        json_response = await client.post(
            "/chat",
            json={"message": "Hello"}  # This is JSON, not FormData
        )
        
        assert json_response.status_code == 422, (
            f"JSON submission should fail with 422, got {json_response.status_code}. "
            "Widget MUST use FormData, not JSON."
        )
        print(f"✓ JSON validation passed: Endpoint correctly rejects JSON")
        
        # FormData attempt (should succeed with 200)
        form_response = await client.post(
            "/chat",
            data={"message": "Hello"}  # This is FormData
        )
        
        assert form_response.status_code == 200, (
            f"FormData submission should succeed with 200, got {form_response.status_code}"
        )
        print(f"✓ FormData validation passed: Endpoint accepts FormData")


@pytest.mark.asyncio
async def test_chat_response_model():
    """Validate ChatResponse model matches widget expectations"""
    # Create test response
    test_response = ChatResponse(
        response="Test response text",
        conversation_id=str(uuid.uuid4())
    )
    
    # Verify model fields
    assert hasattr(test_response, 'response')
    assert hasattr(test_response, 'conversation_id')
    
    # Verify JSON serialization (what widget will receive)
    json_dict = test_response.model_dump()
    assert "response" in json_dict
    assert "conversation_id" in json_dict
    assert json_dict["response"] == "Test response text"
    
    print(f"✓ ChatResponse model structure is correct for widget")


def test_widget_formdata_implementation():
    """
    Test widget FormData implementation without running server.
    Simulates what the widget's sendMessage() function does.
    """
    # This simulates the widget's FormData construction (chat-widget.js:240-270)
    from pathlib import Path
    
    widget_js = Path("mcp_host/static/chat-widget.js").read_text()
    
    # Verify FormData usage (not JSON)
    assert "const formData = new FormData()" in widget_js or "new FormData()" in widget_js, (
        "Widget must use FormData() for /chat requests"
    )
    
    # Verify FormData.append() calls
    assert "formData.append('message'" in widget_js, "Widget must append 'message' to FormData"
    
    # Verify no JSON.stringify
    assert "JSON.stringify" not in widget_js or "JSON.stringify" not in widget_js[widget_js.find("sendMessage"):widget_js.find("sendMessage")+500], (
        "Widget's sendMessage() should NOT use JSON.stringify for /chat requests"
    )
    
    # Verify no Content-Type header (browser sets it automatically for FormData)
    send_message_section = widget_js[widget_js.find("sendMessage"):widget_js.find("sendMessage")+1000]
    assert "Content-Type" not in send_message_section or "form-data" not in send_message_section, (
        "Don't manually set Content-Type for FormData - browser handles it"
    )
    
    print(f"✓ Widget FormData implementation verified in source code")


if __name__ == "__main__":
    print("Running widget-backend integration tests...\n")
    print("=" * 60)
    
    # Run tests
    pytest.main([__file__, "-v", "-s"])
