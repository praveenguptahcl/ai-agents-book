"""MCP 2026-07-28 wire primitives: JSON-RPC 2.0 envelopes, per-request _meta,
discovery, and the spec's reserved error codes.

Modern era only (single era, stateless). A legacy client speaking the
2025-11-25 `initialize` handshake gets -32022, not a session.

Spec references (checked 2026-09-11):
  - Base: JSON-RPC 2.0, stateless self-contained requests,
    per-request capability negotiation.
  - Discovery: `server/discover` (server MUST implement), response carries
    resultType / supportedVersions / capabilities / serverInfo / instructions.
  - Reserved error range: -32020..-32099 (custom codes must not live here).
"""

from __future__ import annotations

import itertools
import json
from typing import Any

PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_VERSIONS = ["2026-07-28"]

# Per-request metadata keys, namespaced per the spec.
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPS = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

# JSON-RPC 2.0 standard errors.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

# MCP-reserved errors (2026-07-28).
HEADER_MISMATCH = -32020          # transport header / _meta mismatch
MISSING_CLIENT_CAPABILITY = -32021  # required per-request capability absent
UNSUPPORTED_VERSION = -32022      # protocol version not supported

_id_counter = itertools.count(1)


class MCPError(Exception):
    """A protocol-level failure that must become a JSON-RPC error envelope."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def new_id() -> str:
    return f"req-{next(_id_counter)}"


def client_meta(name: str = "alphaforge-mcp", version: str = "0.1.0") -> dict:
    """The _meta every modern-era request must carry."""
    return {
        META_VERSION: PROTOCOL_VERSION,
        META_CLIENT_INFO: {"name": name, "version": version},
        META_CLIENT_CAPS: {},
    }


def request_envelope(method: str, params: dict | None = None,
                     req_id: str | None = None) -> dict:
    env: dict = {"jsonrpc": "2.0", "method": method}
    env["id"] = req_id if req_id is not None else new_id()
    if params is not None:
        env["params"] = params
    return env


def discover_request(meta: dict | None = None) -> dict:
    return request_envelope("server/discover",
                            {"_meta": meta or client_meta()})


def tools_list_request(meta: dict | None = None) -> dict:
    return request_envelope("tools/list", {"_meta": meta or client_meta()})


def tools_call_request(name: str, arguments: dict,
                       meta: dict | None = None) -> dict:
    return request_envelope("tools/call", {
        "_meta": meta or client_meta(),
        "name": name,
        "arguments": arguments,
    })


def ok_response(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def error_response(req_id: Any, code: int, message: str,
                   data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def require_meta(params: Any) -> dict:
    """Enforce the modern-era contract: every request carries _meta with a
    supported protocol version. Returns the _meta dict."""
    if not isinstance(params, dict):
        raise MCPError(INVALID_PARAMS, "params must be an object")
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        raise MCPError(INVALID_PARAMS,
                       "missing required params._meta (modern era is stateless)")
    version = meta.get(META_VERSION)
    if version not in SUPPORTED_VERSIONS:
        raise MCPError(
            UNSUPPORTED_VERSION,
            f"unsupported protocol version: {version!r}",
            {"requested": version, "supported": SUPPORTED_VERSIONS},
        )
    return meta


def dumps(msg: dict) -> str:
    return json.dumps(msg, separators=(",", ":"))


def loads(line: str) -> dict:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError as exc:
        raise MCPError(PARSE_ERROR, f"invalid JSON: {exc}") from exc
    if not isinstance(msg, dict):
        raise MCPError(INVALID_REQUEST, "message must be a JSON object")
    return msg
