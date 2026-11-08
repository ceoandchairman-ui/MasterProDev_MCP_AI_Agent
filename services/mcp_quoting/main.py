"""Quoting MCP server: deterministic prices from the business-owned catalog. The model never supplies a price.

Stateless: it prices and verifies, it does not store. The application stores the quote it receives and later pays
from that stored record. Run:  uvicorn --factory services.mcp_quoting.main:create --port 8003
"""

import os
from datetime import UTC, datetime
from typing import Any, Dict, List

from mpd_assistant.business.catalog import load_catalog
from mpd_assistant.business.quoting import APPROVAL_THRESHOLD_CENTS, Quote, QuoteError, build_quote, quote_hash
from services._common.mcp_common.base_server import BaseMCPServer

MAX_LINES = 25


def serialize(quote: Quote) -> Dict[str, Any]:
    return {
        "lines": [
            {"sku": x.sku, "name": x.name, "quantity": str(x.quantity), "unit_price_cents": x.unit_price_cents, "total_cents": x.total_cents}
            for x in quote.lines
        ],
        "subtotal_cents": quote.subtotal_cents,
        "tax_cents": quote.tax_cents,
        "total_cents": quote.total_cents,
        "currency": quote.currency,
        "needs_approval": quote.needs_approval,
        "expires_at": quote.expires_at.isoformat(),
        "content_hash": quote.content_hash,
    }


class QuotingMCPServer(BaseMCPServer):
    def __init__(self):
        super().__init__(name="Quoting Server", description="Deterministic quote pricing from the service catalog")
        path = os.environ.get("CATALOG_PATH")
        if not path:
            raise RuntimeError("CATALOG_PATH is not set")
        self._catalog = load_catalog(path)

    def get_available_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "list_catalog", "description": "List the services that can be quoted, with units and unit prices", "parameters": {}},
            {
                "name": "price_quote",
                "description": "Price a quote from catalog selections",
                "parameters": {"selections": "list of {sku, quantity}"},
            },
            {
                "name": "verify_quote",
                "description": "Check a stored quote's lines still match its hash and total",
                "parameters": {"lines": "stored lines", "total_cents": "int", "currency": "str", "content_hash": "str"},
            },
        ]

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        if tool_name == "list_catalog":
            return {
                "items": [
                    {"sku": i.sku, "name": i.name, "unit": i.unit, "unit_price_cents": i.unit_price_cents} for i in self._catalog.values()
                ],
                "approval_threshold_cents": APPROVAL_THRESHOLD_CENTS,
            }
        if tool_name == "price_quote":
            selections = params.get("selections")
            if not isinstance(selections, list) or len(selections) > MAX_LINES or not all(isinstance(s, dict) for s in selections):
                return {"error": "invalid_selections"}
            try:
                return serialize(build_quote(self._catalog, selections))
            except QuoteError as exc:
                return {"error": str(exc)}
        if tool_name == "verify_quote":
            return self._verify(params)
        return {"error": "unknown_tool"}

    @staticmethod
    def _verify(params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            lines = [[x["sku"], str(x["quantity"]), int(x["unit_price_cents"]), int(x["total_cents"])] for x in params["lines"]]
            total, currency = int(params["total_cents"]), str(params["currency"])
            expected = quote_hash(lines, total, currency)
        except (KeyError, TypeError, ValueError):
            return {"valid": False, "reason": "malformed"}
        if expected != params.get("content_hash"):
            return {"valid": False, "reason": "hash_mismatch"}
        expires = params.get("expires_at")
        if expires and datetime.fromisoformat(str(expires)) < datetime.now(UTC):
            return {"valid": False, "reason": "expired"}
        return {"valid": True}


def create():
    """ASGI factory: uvicorn --factory services.mcp_quoting.main:create"""
    return QuotingMCPServer().app
