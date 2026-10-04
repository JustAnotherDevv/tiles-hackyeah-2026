"""MCP wire helpers for an intermediary: era detection, the 2026-07-28 routing headers, SSE codec,
and synthetic JSON-RPC results.

Two protocol eras arrive on the same Streamable HTTP endpoint:

    legacy  (<= 2025-11-25)  initialize handshake, Mcp-Session-Id, SSE responses, GET stream, DELETE
    modern  (2026-07-28)     stateless; every request carries params._meta envelope + mirrored headers
                             MCP-Protocol-Version, Mcp-Method, Mcp-Name, Mcp-Param-* (x-mcp-header);
                             a header/body disagreement is JSON-RPC -32020 HeaderMismatch (HTTP 400);
                             results carry resultType ("complete" | "input_required"), ttlMs, cacheScope

We route exactly like the SDK server does (header-first): an MCP-Protocol-Version header that is
not a handshake-era version means modern. We additionally treat a body `_meta` protocolVersion as
modern so a client that omits the header gets validated (and rejected) instead of slipping through.

The header codec/validators are reused from the official SDK (`mcp.shared.inbound`) so the proxy
and the servers agree byte-for-byte.
"""

from __future__ import annotations

import codecs
import json
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from mcp.shared.inbound import (
    MCP_PARAM_HEADER_PREFIX,
    NAME_BEARING_METHODS,
    InboundLadderRejection,
    classify_inbound_request,
    encode_header_value,
    find_duplicated_routing_header,
    mcp_param_headers,
    validate_mcp_param_headers,
    x_mcp_header_map,
)
from mcp_types import PROTOCOL_VERSION_META_KEY
from mcp_types.jsonrpc import HEADER_MISMATCH
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS

MODERN = "modern"
LEGACY = "legacy"


def detect_era(headers: Mapping[str, str], body: Any) -> str:
    version = headers.get("mcp-protocol-version")
    if version is not None and version not in HANDSHAKE_PROTOCOL_VERSIONS:
        return MODERN
    if isinstance(body, dict):
        meta = (body.get("params") or {}).get("_meta") if isinstance(body.get("params"), dict) else None
        if isinstance(meta, dict) and meta.get(PROTOCOL_VERSION_META_KEY) in MODERN_PROTOCOL_VERSIONS:
            return MODERN
    return LEGACY


def is_request(msg: Any) -> bool:
    return isinstance(msg, dict) and "method" in msg and "id" in msg


def is_notification(msg: Any) -> bool:
    return isinstance(msg, dict) and "method" in msg and "id" not in msg


def is_response(msg: Any) -> bool:
    return isinstance(msg, dict) and "method" not in msg and ("result" in msg or "error" in msg)


# ---------------------------------------------------------------------------------------------
# 2026-07-28 routing headers
# ---------------------------------------------------------------------------------------------


def check_modern_request(
    body: dict[str, Any],
    headers: Mapping[str, str],
    raw_headers: Iterable[tuple[str, str]],
    input_schema: dict[str, Any] | None,
) -> InboundLadderRejection | None:
    """Anti-smuggling: an intermediary must decide on the BODY and refuse requests whose mirrored
    headers disagree with it (otherwise a router/WAF keyed on headers sees a different call than
    the server executes). Only HeaderMismatch is enforced here; version support is the upstream's call."""
    if dup := find_duplicated_routing_header(raw_headers):
        return InboundLadderRejection(HEADER_MISMATCH, f"duplicated routing header {dup}")
    verdict = classify_inbound_request(body, headers=headers, supported_modern_versions=MODERN_PROTOCOL_VERSIONS)
    if isinstance(verdict, InboundLadderRejection) and verdict.code == HEADER_MISMATCH:
        return verdict
    if body.get("method") == "tools/call" and input_schema:
        args = (body.get("params") or {}).get("arguments") or {}
        return validate_mcp_param_headers(input_schema, args, headers)
    return None


def recompute_routing_headers(
    headers: dict[str, str], msg: dict[str, Any], input_schema: dict[str, Any] | None
) -> dict[str, str]:
    """After rewriting a request body, re-derive Mcp-Method / Mcp-Name / Mcp-Param-* from it.
    Skipping this turns every redaction of a header-mirrored argument into a -32020 at the server."""
    out = {k: v for k, v in headers.items() if not k.startswith(MCP_PARAM_HEADER_PREFIX.lower())}
    method = msg.get("method", "")
    params = msg.get("params") or {}
    out["mcp-method"] = method
    if (name_key := NAME_BEARING_METHODS.get(method)) and params.get(name_key) is not None:
        out["mcp-name"] = encode_header_value(str(params[name_key]))
    if method == "tools/call" and input_schema:
        for k, v in mcp_param_headers(x_mcp_header_map(input_schema), params.get("arguments") or {}).items():
            out[k.lower()] = v
    return out


# ---------------------------------------------------------------------------------------------
# Synthetic responses
# ---------------------------------------------------------------------------------------------


def _complete(result: dict[str, Any], era: str) -> dict[str, Any]:
    # 2026-07-28 requires resultType on every result; strict legacy clients may reject unknown keys.
    return {**result, "resultType": "complete"} if era == MODERN else result


def blocked_tool_result(req_id: Any, era: str, text: str, decision: dict[str, Any]) -> dict[str, Any]:
    """A tools/call refusal as a normal tool result with isError=true: the model reads the reason and
    the agent loop continues (a JSON-RPC error is often surfaced as a transport failure instead)."""
    result = {"content": [{"type": "text", "text": text}], "isError": True,
              "_meta": {"io.aegis/decision": decision}}
    return {"jsonrpc": "2.0", "id": req_id, "result": _complete(result, era)}


def jsonrpc_error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


# ---------------------------------------------------------------------------------------------
# Server-Sent Events codec (handles CRLF - the Python SDK emits "\r\n" line endings)
# ---------------------------------------------------------------------------------------------


@dataclass
class SSEEvent:
    data: str = ""
    event: str | None = None
    id: str | None = None
    retry: str | None = None
    comments: list[str] = field(default_factory=list)

    def json(self) -> Any:
        try:
            return json.loads(self.data) if self.data else None
        except json.JSONDecodeError:
            return None

    def encode(self) -> bytes:
        lines = [f":{c}" for c in self.comments]
        if self.event is not None:
            lines.append(f"event: {self.event}")
        if self.id is not None:
            lines.append(f"id: {self.id}")
        if self.retry is not None:
            lines.append(f"retry: {self.retry}")
        lines += [f"data: {line}" for line in self.data.split("\n")] if self.data else []
        return ("\n".join(lines) + "\n\n").encode("utf-8")


async def iter_sse(chunks: AsyncIterator[bytes]) -> AsyncIterator[SSEEvent]:
    decoder = codecs.getincrementaldecoder("utf-8")()  # a chunk may split a multi-byte character
    buf = ""
    ev = SSEEvent()
    data_lines: list[str] = []
    dirty = False
    async for chunk in chunks:
        buf += decoder.decode(chunk)
        if buf.endswith("\r"):  # a CRLF may straddle two chunks; wait for the next one
            continue
        buf = buf.replace("\r\n", "\n").replace("\r", "\n")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            if line == "":
                if dirty:
                    ev.data = "\n".join(data_lines)
                    yield ev
                ev, data_lines, dirty = SSEEvent(), [], False
                continue
            dirty = True
            if line.startswith(":"):
                ev.comments.append(line[1:])  # keep-alives must reach the client
                continue
            name, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if name == "data":
                data_lines.append(value)
            elif name == "event":
                ev.event = value
            elif name == "id":
                ev.id = value
            elif name == "retry":
                ev.retry = value
    if dirty:
        ev.data = "\n".join(data_lines)
        yield ev
