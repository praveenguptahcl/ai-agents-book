"""Modern-era MCP server over stdio: the AlphaForge market-data tool server.

Speaks MCP 2026-07-28 (modern era, stateless) on stdin/stdout, one
newline-delimited JSON-RPC 2.0 message per line. Logs go to stderr so they
never corrupt the wire. Exposes a single tool, `get_quote`, backed by
deterministic SYNTHETIC data — this is a paper-broker fixture, not a market
feed. Every quote carries provenance "SYNTHETIC".

The dispatch core (`MCPServer.handle_message`) is pure in-process logic so
tests can drive failure modes without a subprocess; `main()` wraps it in the
real stdio transport.
"""

from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

from mcp_protocol import (
    HEADER_MISMATCH,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    META_SERVER_INFO,
    PROTOCOL_VERSION,
    SUPPORTED_VERSIONS,
    MCPError,
    UNSUPPORTED_VERSION,
    dumps,
    error_response,
    loads,
    ok_response,
    require_meta,
)

SERVER_INFO = {"name": "alphaforge-market-data", "version": "0.1.0"}

# Approved universe for the fixture. Quotes are synthetic constants with a
# deterministic per-symbol jitter — clearly labeled, never real prices.
UNIVERSE = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]
BASE_PRICES = {"AAPL": 230.0, "MSFT": 520.0, "NVDA": 180.0,
               "SPY": 640.0, "QQQ": 560.0}
AS_OF = "2026-09-11"  # fixture date; the data is synthetic regardless


def synthetic_quote(symbol: str) -> dict:
    """Deterministic fake quote. Same symbol always yields the same quote."""
    digest = hashlib.sha256(f"{symbol}:{AS_OF}".encode()).digest()
    jitter = (int.from_bytes(digest[:4], "big") % 2000 - 1000) / 10000.0  # ±10%
    price = round(BASE_PRICES[symbol] * (1 + jitter), 2)
    return {
        "symbol": symbol,
        "price": price,
        "currency": "USD",
        "as_of": AS_OF,
        "provenance": "SYNTHETIC",
    }


GET_QUOTE_TOOL = {
    "name": "get_quote",
    # NOTE: descriptions are attacker-controlled text in the general case
    # (see §7.4). Ours is ours; a foreign server's is not.
    "description": "Return the latest synthetic paper quote for a symbol.",
    "inputSchema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "symbol": {
                "type": "string",
                "enum": UNIVERSE,
                "description": "Ticker from the approved universe.",
            },
        },
        "required": ["symbol"],
    },
}


class MCPServer:
    """Modern-era MCP server. `tools` is the advertised registry; tests may
    inject poisoned registries to prove the client rejects them."""

    def __init__(self, tools: list[dict] | None = None):
        self.tools = tools if tools is not None else [GET_QUOTE_TOOL]

    # -- discovery ------------------------------------------------------
    def discover(self, _meta: dict) -> dict:
        return {
            "resultType": "complete",
            "supportedVersions": SUPPORTED_VERSIONS,
            "capabilities": {"tools": {}},
            "_meta": {META_SERVER_INFO: SERVER_INFO},
            "instructions": "Paper-broker fixture. get_quote returns "
                            "SYNTHETIC quotes for the approved universe.",
            "ttlMs": 0,
            "cacheScope": "private",
        }

    # -- tools ----------------------------------------------------------
    def tools_list(self, _meta: dict) -> dict:
        return {"resultType": "complete", "tools": self.tools}

    def tools_call(self, params: dict, _meta: dict) -> dict:
        name = params.get("name")
        arguments = params.get("arguments", {})
        tool = next((t for t in self.tools if t.get("name") == name), None)
        if tool is None:
            raise MCPError(INVALID_PARAMS, f"unknown tool: {name!r}")
        if not isinstance(arguments, dict):
            raise MCPError(INVALID_PARAMS, "arguments must be an object")
        if name == "get_quote":
            return self._call_get_quote(arguments)
        raise MCPError(INVALID_PARAMS, f"tool not implemented: {name!r}")

    def _call_get_quote(self, arguments: dict) -> dict:
        symbol = arguments.get("symbol")
        # Server-side contract enforcement: the schema is advisory text on
        # the wire; this check is the law (Ch 4 discipline, server side).
        if symbol not in UNIVERSE:
            raise MCPError(
                INVALID_PARAMS,
                f"symbol {symbol!r} not in approved universe {UNIVERSE}",
            )
        quote = synthetic_quote(symbol)
        return {
            "resultType": "complete",
            "content": [{"type": "text", "text": json.dumps(quote)}],
        }

    # -- dispatch -------------------------------------------------------
    def handle_message(self, msg: dict) -> dict | None:
        """Route one parsed JSON-RPC message. Returns the response envelope,
        or None for notifications (messages without an id)."""
        req_id = msg.get("id")
        method = msg.get("method")

        if msg.get("jsonrpc") != "2.0" or not isinstance(method, str):
            # Malformed envelope: per JSON-RPC 2.0 §5.1 this is
            # INVALID_REQUEST (-32600), not INVALID_PARAMS. Silence is
            # reserved for notification-shaped messages (no id, valid
            # method string); anything else gets an error — with an id-null
            # envelope when there is no id to route a targeted error to.
            if req_id is None and isinstance(method, str):
                return None
            return error_response(req_id, INVALID_REQUEST,
                                 "invalid JSON-RPC 2.0 request")

        # Notifications (no id): acknowledge by silence, per JSON-RPC.
        if req_id is None:
            return None

        try:
            params = msg.get("params", {})
            meta = require_meta(params)
            if method == "server/discover":
                result = self.discover(meta)
            elif method == "tools/list":
                result = self.tools_list(meta)
            elif method == "tools/call":
                result = self.tools_call(params, meta)
            elif method == "initialize":
                # Legacy-era selector. We are modern-only: say so, loudly.
                raise MCPError(
                    UNSUPPORTED_VERSION,
                    "this server implements the modern era only; "
                    "initialize is the legacy handshake",
                    {"supported": SUPPORTED_VERSIONS},
                )
            else:
                raise MCPError(METHOD_NOT_FOUND, f"unknown method: {method}")
            return ok_response(req_id, result)
        except MCPError as exc:
            return error_response(req_id, exc.code, exc.message, exc.data)


def main() -> None:
    server = MCPServer()
    # Line-buffered text IO; stderr carries logs, never the wire.
    stdin = sys.stdin
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = loads(line)
        except MCPError as exc:
            sys.stdout.write(dumps(error_response(None, exc.code,
                                                  exc.message, exc.data)) + "\n")
            sys.stdout.flush()
            continue
        response = server.handle_message(msg)
        if response is not None:
            sys.stdout.write(dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
