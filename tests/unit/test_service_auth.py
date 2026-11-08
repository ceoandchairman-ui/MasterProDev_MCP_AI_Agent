import pytest
from fastapi.testclient import TestClient

from services._common.mcp_common.base_server import BaseMCPServer, parse_origins
from services._common.mcp_common.service_auth import keys_match


class EchoServer(BaseMCPServer):
    def __init__(self):
        super().__init__("Echo", "test server")

    async def execute_tool(self, tool_name, params):
        return {"tool": tool_name, "params": params}


@pytest.fixture
def keyed_client(monkeypatch):
    monkeypatch.setenv("MCP_SERVICE_KEY", "s3cret")
    monkeypatch.delenv("MCP_ALLOW_UNAUTHENTICATED", raising=False)
    return TestClient(EchoServer().app)


def test_server_refuses_to_start_without_key(monkeypatch):
    monkeypatch.delenv("MCP_SERVICE_KEY", raising=False)
    monkeypatch.delenv("MCP_ALLOW_UNAUTHENTICATED", raising=False)
    with pytest.raises(RuntimeError):
        EchoServer()


def test_health_is_open(keyed_client):
    assert keyed_client.get("/health").status_code == 200


def test_call_without_key_is_401(keyed_client):
    assert keyed_client.post("/call", params={"tool_name": "x"}, json={}).status_code == 401


def test_call_with_wrong_key_is_401(keyed_client):
    r = keyed_client.post("/call", params={"tool_name": "x"}, json={}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_call_with_key_succeeds(keyed_client):
    r = keyed_client.post("/call", params={"tool_name": "x"}, json={"a": 1}, headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    assert r.json() == {"tool": "x", "params": {"a": 1}}


def test_tools_listing_requires_key(keyed_client):
    assert keyed_client.post("/tools").status_code == 401


def test_explicit_opt_out_allows_local_dev(monkeypatch):
    monkeypatch.delenv("MCP_SERVICE_KEY", raising=False)
    monkeypatch.setenv("MCP_ALLOW_UNAUTHENTICATED", "true")
    client = TestClient(EchoServer().app)
    assert client.post("/tools").status_code == 200


def test_keys_match_is_exact():
    assert keys_match("abc", "abc")
    assert not keys_match("abd", "abc")
    assert not keys_match(None, "abc")
    assert not keys_match("", "abc")


def test_parse_origins_formats():
    assert parse_origins('["http://a","http://b"]') == ["http://a", "http://b"]
    assert parse_origins("http://a, http://b") == ["http://a", "http://b"]
    assert parse_origins("[]") == []
