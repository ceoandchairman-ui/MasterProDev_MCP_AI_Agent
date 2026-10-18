import pytest
from fastapi.testclient import TestClient

from services._common.mcp_common.base_server import BaseMCPServer
from services._common.mcp_common.user_token import current_user_token


class Probe(BaseMCPServer):
    def __init__(self):
        super().__init__("Probe", "test")
        self.seen = []

    async def execute_tool(self, tool_name, params):
        self.seen.append(current_user_token())
        return {"ok": True}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MCP_SERVICE_KEY", "svc")
    monkeypatch.delenv("MCP_ALLOW_UNAUTHENTICATED", raising=False)
    probe = Probe()
    return TestClient(probe.app), probe


def test_user_token_is_visible_only_during_its_call(client):
    c, probe = client
    headers = {"Authorization": "Bearer svc", "X-Google-Access-Token": "USER-A"}
    assert c.post("/call", params={"tool_name": "t"}, json={}, headers=headers).status_code == 200
    assert c.post("/call", params={"tool_name": "t"}, json={}, headers={"Authorization": "Bearer svc"}).status_code == 200
    assert probe.seen == ["USER-A", None]  # a call without a token never inherits the previous user's token
    assert current_user_token() is None
