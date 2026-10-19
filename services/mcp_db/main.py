"""Company-data MCP server: read-only, allowlisted, parameterized queries. The model never writes SQL.

Every tool is a named query defined here. Parameters are validated and bound, results are tenant-scoped, the
transaction is read-only, and personal data (names, emails, phones, quote line items) is never returned.
Use a database role that only has SELECT on these tables.  Run: uvicorn --factory services.mcp_db.main:create --port 8004
"""

import os
import re
from typing import Any, Callable, Dict, List

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from services._common.mcp_common.base_server import BaseMCPServer

_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_ROWS = 50
DEFAULT_TENANT = "masterprodev"

QUERIES: Dict[str, Dict[str, Any]] = {
    "list_knowledge_sources": {
        "description": "Names of the company documents available as knowledge",
        "params": [],
        "sql": "SELECT DISTINCT dc.source AS source FROM document_chunks dc WHERE dc.tenant_id = :tenant ORDER BY dc.source LIMIT :limit",
    },
    "get_lead_stage": {
        "description": "Funnel stage, timeline and budget range for a user's lead",
        "params": ["user_id"],
        "sql": (
            "SELECT l.stage AS stage, l.timeline AS timeline, l.budget_range AS budget_range, l.updated_at AS updated_at "
            "FROM leads l WHERE l.tenant_id = :tenant AND l.user_id = :user_id LIMIT 1"
        ),
    },
    "list_quotes_for_user": {
        "description": "A user's quotes: reference, status, total and expiry (no line items)",
        "params": ["user_id"],
        "sql": (
            "SELECT upper(substr(q.id, 1, 8)) AS ref, q.status AS status, q.total_cents AS total_cents, q.currency AS currency, "
            "q.expires_at AS expires_at FROM quotes q JOIN leads l ON l.id = q.lead_id "
            "WHERE l.tenant_id = :tenant AND l.user_id = :user_id ORDER BY q.created_at DESC LIMIT :limit"
        ),
    },
    "funnel_counts": {
        "description": "Number of leads in each funnel stage",
        "params": [],
        "sql": "SELECT l.stage AS stage, COUNT(*) AS leads FROM leads l WHERE l.tenant_id = :tenant GROUP BY l.stage ORDER BY l.stage",
    },
}


def _plain(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


class DatabaseMCPServer(BaseMCPServer):
    def __init__(self, engine: Engine | None = None):
        super().__init__(name="Company Data Server", description="Read-only, allowlisted company data queries")
        if engine is None:
            url = os.environ.get("MCP_DB_URL")
            if not url:
                raise RuntimeError("MCP_DB_URL is not set (use a read-only database role)")
            engine = create_engine(url.replace("postgresql+asyncpg://", "postgresql://"), pool_pre_ping=True, pool_size=3, max_overflow=2)
        self._engine = engine
        self._tenant_name = os.environ.get("TENANT_NAME", DEFAULT_TENANT)
        self._tenant_id: str | None = None

    def get_available_tools(self) -> List[Dict[str, Any]]:
        return [{"name": n, "description": q["description"], "parameters": {p: "32-character id" for p in q["params"]}} for n, q in QUERIES.items()]

    def _tenant(self, conn) -> str:
        if self._tenant_id is None:
            row = conn.execute(text("SELECT id FROM tenants WHERE name = :name"), {"name": self._tenant_name}).first()
            if row is None:
                raise LookupError("tenant not found")
            self._tenant_id = row[0]
        return self._tenant_id

    def _run(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        spec = QUERIES[name]
        bound: Dict[str, Any] = {"limit": MAX_ROWS}
        for p in spec["params"]:
            value = params.get(p)
            if not isinstance(value, str) or not _ID.match(value):
                return {"error": f"invalid_{p}"}
            bound[p] = value
        with self._engine.connect() as conn:
            if self._engine.dialect.name == "postgresql":
                conn.execute(text("SET TRANSACTION READ ONLY"))
            bound["tenant"] = self._tenant(conn)
            sql = spec["sql"]
            used = {k: v for k, v in bound.items() if f":{k}" in sql}
            rows = conn.execute(text(sql), used).mappings().all()
        return {"rows": [{k: _plain(v) for k, v in dict(r).items()} for r in rows]}

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        if tool_name not in QUERIES:
            return {"error": "unknown_tool"}
        import asyncio

        runner: Callable[[], Dict[str, Any]] = lambda: self._run(tool_name, params)  # noqa: E731
        try:
            return await asyncio.to_thread(runner)
        except LookupError:
            return {"error": "tenant_not_found"}
        except Exception:
            return {"error": "query_failed"}  # no database error text reaches the model


def create():
    """ASGI factory: uvicorn --factory services.mcp_db.main:create"""
    return DatabaseMCPServer().app
