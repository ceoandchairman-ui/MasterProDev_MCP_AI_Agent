"""Base MCP Server template"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import Any, Dict, List
import os
import json


class BaseMCPServer:
    """Base class for MCP servers"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.app = FastAPI(title=name, description=description)
        
        # Parse allowed origins from env or default to permissive for local dev
        allowed_origins_env = os.environ.get("ALLOWED_ORIGINS", '["*"]')
        try:
            allowed_origins = json.loads(allowed_origins_env)
        except json.JSONDecodeError:
            allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        self._setup_routes()

    def _setup_routes(self):
        """Setup base routes"""
        @self.app.get("/health")
        async def health():
            return {"status": "healthy", "service": self.name}

        @self.app.post("/tools")
        async def get_tools():
            """List available tools"""
            return {"tools": self.get_available_tools()}

        @self.app.post("/call")
        async def call_tool(tool_name: str, params: Dict[str, Any]):
            """Call a tool"""
            return await self.execute_tool(tool_name, params)

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Override to return available tools"""
        return []

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """Override to implement tool execution"""
        raise NotImplementedError(f"Tool {tool_name} not implemented")
