"""Base MCP server: one implementation shared by every tool service."""

import json
import os
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .service_auth import check_startup_config, require_service_auth
from .user_token import HEADER, reset_user_token, set_user_token


def parse_origins(raw: str) -> List[str]:
    try:
        value = json.loads(raw)
        return [str(v) for v in value] if isinstance(value, list) else []
    except json.JSONDecodeError:
        return [o.strip() for o in raw.split(",") if o.strip()]


class BaseMCPServer:
    """Tool server skeleton. Everything except /health requires the service key."""

    def __init__(self, name: str, description: str):
        check_startup_config()
        self.name = name
        self.description = description
        self.app = FastAPI(title=name, description=description)

        # Tool servers are called server-to-server, so browsers get no cross-origin access by default.
        origins = parse_origins(os.environ.get("MCP_ALLOWED_ORIGINS", "[]"))
        if origins:
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=[o for o in origins if o != "*"],
                allow_credentials=False,
                allow_methods=["GET", "POST"],
                allow_headers=["Authorization", "Content-Type", "X-Trace-Id", "X-Session-Id"],
            )
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.app.get("/health")
        async def health():
            return {"status": "healthy", "service": self.name}

        @self.app.post("/tools", dependencies=[Depends(require_service_auth)])
        async def get_tools():
            return {"tools": self.get_available_tools()}

        @self.app.post("/call", dependencies=[Depends(require_service_auth)])
        async def call_tool(tool_name: str, params: Dict[str, Any], request: Request):
            marker = set_user_token(request.headers.get(HEADER) or None)
            try:
                return await self.execute_tool(tool_name, params)
            finally:
                reset_user_token(marker)

    def get_available_tools(self) -> List[Dict[str, Any]]:
        return []

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        raise NotImplementedError(f"Tool {tool_name} not implemented")
