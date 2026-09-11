"""Modern-era MCP client: the AlphaForge side of the wire.

The client's job is distrust, done mechanically:

1. Every request carries _meta (protocolVersion, clientInfo, clientCaps).
2. Server-sent JSON-RPC errors become structured MCPServerError exceptions.
3. The advertised tool listing is validated against a local Pydantic
   contract BEFORE any call: MCP gives you the listing; Pydantic gives
   you the law (Ch 4 discipline, applied to a foreign server).
4. Tool descriptions are treated as untrusted text: the server's
   description never reaches a prompt. The planner sees only the local
   contract's docstring, via trusted_description() (see §7.4, Ch 12).
5. An explicit allowlist bounds which tools may be invoked at all — and
   an allowlisted tool with no local contract still fails closed.

Transport: a child process running mcp_server.py over stdio.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from mcp_protocol import (
    MCPError,
    client_meta,
    discover_request,
    dumps,
    loads,
    tools_call_request,
    tools_list_request,
)

# --------------------------------------------------------------------------
# The contract. This is local, versioned, reviewed code. The server's
# inputSchema is a claim about the world; this is the check against it.
# --------------------------------------------------------------------------


class GetQuoteArgs(BaseModel):
    """Return the latest synthetic paper quote for a symbol in the approved universe."""
    model_config = ConfigDict(extra="forbid")
    symbol: Literal["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]


class GetQuoteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    price: float
    currency: Literal["USD"]
    as_of: str
    provenance: Literal["SYNTHETIC"]  # the fixture must never pass as real


CONTRACTS: dict[str, type[BaseModel]] = {"get_quote": GetQuoteArgs}


class ContractViolation(Exception):
    """The advertised tool listing does not satisfy the local contract."""


class UnknownToolError(Exception):
    """Refused: tool is not on the client's allowlist."""


class MCPServerError(Exception):
    """The server answered with a JSON-RPC error envelope."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data


class ToolExecutionError(Exception):
    """The tool ran and reported failure (isError: true).

    This is a rejected trade, not a protocol crash: the wire worked, the
    server answered, and the answer was no. Retry logic must treat this
    differently from MCPServerError — retrying a rejected trade as if the
    transport had failed is how duplicates get minted."""

    def __init__(self, tool: str, detail: str = ""):
        message = f"tool {tool!r} failed" + (f": {detail}" if detail else "")
        super().__init__(message)
        self.tool = tool
        self.detail = detail


# --------------------------------------------------------------------------
# Schema compatibility: advertised listing vs local contract.
# --------------------------------------------------------------------------

_JSON_TYPE_OF = {
    "str": "string", "int": "integer", "float": "number", "bool": "boolean",
    "list": "array", "dict": "object",
}


def _contract_schema(model: type[BaseModel]) -> dict:
    return model.model_json_schema()


def _leaf_type(prop_schema: dict) -> str | None:
    """Best-effort JSON type of a schema node (handles anyOf from Optional)."""
    if "type" in prop_schema:
        return prop_schema["type"]
    for branch in prop_schema.get("anyOf", []):
        t = branch.get("type")
        if t and t != "null":
            return t
    const = prop_schema.get("const")
    if const is not None:
        return _JSON_TYPE_OF.get(type(const).__name__)
    if "enum" in prop_schema:
        vals = prop_schema["enum"]
        if vals:
            return _JSON_TYPE_OF.get(type(vals[0]).__name__)
    return None


def check_tool_against_contract(tool: dict, model: type[BaseModel]) -> None:
    """Raise ContractViolation unless the advertised inputSchema is
    compatible with the local Pydantic contract: same required fields, and
    every advertised property type matches the contract's."""
    name = tool.get("name", "<unnamed>")
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict):
        raise ContractViolation(
            f"tool {name!r}: missing or malformed inputSchema")
    if schema.get("type") != "object" or not isinstance(
            schema.get("properties"), dict):
        raise ContractViolation(
            f"tool {name!r}: inputSchema must be an object schema")

    contract = _contract_schema(model)
    want_required = set(contract.get("required", []))
    got_required = set(schema.get("required", []))
    if got_required != want_required:
        raise ContractViolation(
            f"tool {name!r}: required fields {sorted(got_required)} != "
            f"contract {sorted(want_required)}")

    want_props = contract.get("properties", {})
    for field, want_prop in want_props.items():
        got_prop = schema["properties"].get(field)
        if not isinstance(got_prop, dict):
            raise ContractViolation(
                f"tool {name!r}: contract field {field!r} missing from "
                f"advertised schema")
        want_type, got_type = _leaf_type(want_prop), _leaf_type(got_prop)
        if want_type and got_type and want_type != got_type:
            raise ContractViolation(
                f"tool {name!r}: field {field!r} advertised as {got_type!r}, "
                f"contract requires {want_type!r}")


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------


class MCPClient:
    def __init__(self, proc: subprocess.Popen, allowed_tools: list[str],
                 client_name: str = "alphaforge-mcp"):
        self.proc = proc
        self.allowed_tools = set(allowed_tools)
        self.meta = client_meta(name=client_name)

    # -- transport ------------------------------------------------------
    def _roundtrip(self, envelope: dict) -> dict:
        envelope.setdefault("params", {}).setdefault("_meta", self.meta)
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(dumps(envelope) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise MCPServerError(-1, "server closed the stdio transport")
        try:
            msg = loads(line)
        except MCPError as exc:
            raise MCPServerError(exc.code, exc.message, exc.data) from exc
        if "error" in msg:
            err = msg["error"]
            raise MCPServerError(err.get("code", -1),
                                 err.get("message", "unknown error"),
                                 err.get("data"))
        return msg.get("result", {})

    # -- protocol -------------------------------------------------------
    def discover(self) -> dict:
        return self._roundtrip(discover_request(self.meta))

    def list_tools(self) -> list[dict]:
        result = self._roundtrip(tools_list_request(self.meta))
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise ContractViolation("tools/list returned no tool array")
        return tools

    def validated_tools(self) -> dict[str, dict]:
        """List, then validate every advertised tool against its contract.
        Returns {name: listing} for tools that survive validation.

        WARNING: the returned listings are the server's words — names and
        descriptions inside them are untrusted text. Never interpolate
        them into a prompt; the planner-safe surface is
        planner_tool_card()."""
        out = {}
        for tool in self.list_tools():
            name = tool.get("name")
            contract = CONTRACTS.get(name)  # type: ignore[arg-type]
            if contract is None:
                # No local contract for this tool: not validated, not
                # callable through the typed path. Explicit, not silent.
                continue
            check_tool_against_contract(tool, contract)
            out[name] = tool
        return out

    def trusted_description(self, name: str) -> str:
        """The description the planner is allowed to see for `name`.

        Sourced ONLY from the local Pydantic contract's docstring —
        reviewed, versioned, ours. The server's advertised description is
        untrusted input and is discarded here, at the boundary, before
        any prompt is built (§7.4). Client-side override is the defense:
        the planner learns tool semantics from our words, never the
        server's."""
        contract = CONTRACTS.get(name)
        if contract is None:
            raise ContractViolation(
                f"tool {name!r} has no local contract: "
                "no trusted description exists")
        first_line = ((contract.__doc__ or "").strip().splitlines() or [""])[0]
        if not first_line:
            raise ContractViolation(
                f"tool {name!r}: local contract has no docstring to trust")
        return first_line

    def planner_tool_card(self, name: str) -> dict:
        """The ONLY tool metadata that may enter a prompt.

        Every field in this card was written by us, in this file, under
        review: the tool name, the trusted description from the local
        contract's docstring, and the local input schema. The server's
        advertised listing — including any injection payload hiding in
        its description — never appears here."""
        if name not in self.allowed_tools:
            raise UnknownToolError(
                f"tool {name!r} is not on the allowlist {sorted(self.allowed_tools)}")
        return {
            "name": name,
            "description": self.trusted_description(name),
            "inputSchema": _contract_schema(CONTRACTS[name]),
        }

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Invoke a tool. Refuses anything not on the allowlist before any
        bytes hit the wire; fails closed on an allowlisted tool with no
        local contract; validates arguments against the contract; and
        turns a tool-level failure (isError: true) into ToolExecutionError
        so retry logic never mistakes a rejected trade for a protocol
        crash."""
        if name not in self.allowed_tools:
            raise UnknownToolError(
                f"tool {name!r} is not on the allowlist {sorted(self.allowed_tools)}")
        contract = CONTRACTS.get(name)
        if contract is None:
            # Fail closed: an allowlist entry without a local contract is
            # a hole, not a permission. Unvalidated arguments must never
            # reach the wire.
            raise ContractViolation(
                f"tool {name!r} is on the allowlist but has no local "
                "contract: refusing to send unvalidated arguments")
        try:
            arguments = contract(**arguments).model_dump()
        except ValidationError as exc:
            raise ContractViolation(
                f"arguments for {name!r} violate the contract: {exc}"
            ) from exc
        result = self._roundtrip(tools_call_request(name, arguments, self.meta))
        if isinstance(result, dict) and result.get("isError") is True:
            detail = ""
            content = result.get("content")
            if (isinstance(content, list) and content
                    and isinstance(content[0], dict)):
                detail = str(content[0].get("text", ""))
            raise ToolExecutionError(name, detail)
        if result.get("resultType") == "input_required":
            raise NotImplementedError(
                "server requested multi-round-trip input (MRTR); "
                "out of scope for this chapter")
        return result

    def get_quote(self, symbol: str) -> GetQuoteResult:
        """Typed convenience wrapper: the only tool AlphaForge may call."""
        result = self.call_tool("get_quote", {"symbol": symbol})
        content = result.get("content", [])
        if not content or content[0].get("type") != "text":
            raise ContractViolation("get_quote returned no text content")
        try:
            return GetQuoteResult(**json.loads(content[0]["text"]))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ContractViolation(
                f"get_quote result violates the contract: {exc}") from exc


def spawn_server(server_path: str) -> MCPClient:
    """Launch mcp_server.py as a child process and wrap it in a client."""
    proc = subprocess.Popen(
        [sys.executable, server_path],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True, bufsize=1,
    )
    return MCPClient(proc, allowed_tools=["get_quote"])
