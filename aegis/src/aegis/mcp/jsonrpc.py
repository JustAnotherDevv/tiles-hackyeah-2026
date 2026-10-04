"""MCP wire helpers: era detection, 2026-07-28 routing headers, SSE codec, synthetic results.

Ported from staging/spikes/mcp/aegis_mcp/protocol.py (verified against mcp 2.3.0 + Claude Code).

Two protocol eras arrive on the same Streamable HTTP endpoint:

    legacy  (<= 2025-11-25)  initialize handshake, Mcp-Session-Id, SSE responses, GET stream, DELETE
    modern  (2026-07-28)     stateless; params._meta envelope + mirrored headers MCP-Protocol-Version,
                             Mcp-Method, Mcp-Name, Mcp-Param-* (x-mcp-header); a header/body
                             disagreement is JSON-RPC -32020 HeaderMismatch (HTTP 400)

SDK imports are guarded: without `mcp>=2.3` the modern header checks are skipped
(MODERN_HEADERS_SUPPORTED=False) and the proxy still works for legacy traffic.
"""

from __future__ import annotations

import codecs
import json
import logging
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

MODERN = "modern"
LEGACY = "legacy"
MODERN_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
INTERNAL_ERROR = -32603
UNKNOWN_SERVER = -32001  # [Aegis] unknown MCP server (MCP-01)
UPSTREAM_UNREACHABLE = -32002  # [Aegis] upstream MCP server unreachable
HEADER_MISMATCH = -32020

PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
MCP_PARAM_HEADER_PREFIX = "Mcp-Param-"
NAME_BEARING_METHODS: Mapping[str, str] = {
    "tools/call": "name",
    "prompts/get": "name",
    "resources/read": "uri",
}
HANDSHAKE_PROTOCOL_VERSIONS: tuple[str, ...] = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
)
MODERN_PROTOCOL_VERSIONS: tuple[str, ...] = (MODERN_VERSION,)

try:  # guarded: the header codec/validators come from the official SDK (mcp>=2.3)
    from mcp.shared.inbound import (
        InboundLadderRejection,
        classify_inbound_request,
        encode_header_value,
        find_duplicated_routing_header,
        mcp_param_headers,
        validate_mcp_param_headers,
        x_mcp_header_map,
    )
    from mcp_types import PROTOCOL_VERSION_META_KEY as _PV_KEY
    from mcp_types.jsonrpc import HEADER_MISMATCH as _HM
    from mcp_types.version import (
        HANDSHAKE_PROTOCOL_VERSIONS as _HANDSHAKE,
    )
    from mcp_types.version import (
        MODERN_PROTOCOL_VERSIONS as _MODERN,
    )

    PROTOCOL_VERSION_META_KEY = _PV_KEY
    HEADER_MISMATCH = _HM
    HANDSHAKE_PROTOCOL_VERSIONS = tuple(_HANDSHAKE)
    MODERN_PROTOCOL_VERSIONS = tuple(_MODERN)
    MODERN_HEADERS_SUPPORTED = True
except ImportError:  # pragma: no cover - only without mcp 2.x
    MODERN_HEADERS_SUPPORTED = False
    InboundLadderRejection = None  # type: ignore[assignment,misc]

    def encode_header_value(value: str) -> str:  # type: ignore[misc]
        return value


@dataclass
class Rejection:
    """Transport-level rejection (JSON-RPC error code + message)."""

    code: int
    message: str


def detect_era(headers: Mapping[str, str], body: Any) -> str:
    """Header-first, like the SDK; a body `_meta` protocolVersion also counts as modern so a
    client that omits the header gets validated instead of slipping through."""
    version = headers.get("mcp-protocol-version")
    if version is not None and version not in HANDSHAKE_PROTOCOL_VERSIONS:
        return MODERN
    if isinstance(body, dict):
        params = body.get("params")
        meta = params.get("_meta") if isinstance(params, dict) else None
        if (
            isinstance(meta, dict)
            and meta.get(PROTOCOL_VERSION_META_KEY) in MODERN_PROTOCOL_VERSIONS
        ):
            return MODERN
    return LEGACY


def is_request(msg: Any) -> bool:
    return isinstance(msg, dict) and "method" in msg and "id" in msg


def is_notification(msg: Any) -> bool:
    return isinstance(msg, dict) and "method" in msg and "id" not in msg


def is_response(msg: Any) -> bool:
    return isinstance(msg, dict) and "method" not in msg and ("result" in msg or "error" in msg)


# ------------------------------------------------------------------ 2026-07-28 routing headers
def check_modern_request(
    body: dict[str, Any],
    headers: Mapping[str, str],
    raw_headers: Iterable[tuple[str, str]],
    input_schema: dict[str, Any] | None,
) -> Rejection | None:
    """Anti-smuggling: decide on the BODY and refuse requests whose mirrored headers disagree
    with it. Only HeaderMismatch is enforced (version support is the upstream's call). A missing
    `Mcp-Param-*` header is tolerated because the proxy recomputes them before forwarding."""
    if not MODERN_HEADERS_SUPPORTED:
        return None
    if dup := find_duplicated_routing_header(raw_headers):
        return Rejection(HEADER_MISMATCH, f"duplicated routing header {dup}")
    verdict = classify_inbound_request(
        body, headers=headers, supported_modern_versions=MODERN_PROTOCOL_VERSIONS
    )
    if isinstance(verdict, InboundLadderRejection) and verdict.code == HEADER_MISMATCH:
        return Rejection(verdict.code, verdict.message)
    if body.get("method") == "tools/call" and input_schema:
        args = (body.get("params") or {}).get("arguments") or {}
        rej = validate_mcp_param_headers(input_schema, args, headers)
        if rej is not None and "is missing" not in rej.message:
            return Rejection(rej.code, rej.message)
    return None


def recompute_routing_headers(
    headers: dict[str, str], msg: dict[str, Any], input_schema: dict[str, Any] | None
) -> dict[str, str]:
    """Re-derive Mcp-Method / Mcp-Name / Mcp-Param-* from the (possibly rewritten) body. Skipping
    this turns every redaction of a header-mirrored argument into a -32020 at the server."""
    prefix = MCP_PARAM_HEADER_PREFIX.lower()
    out = {k: v for k, v in headers.items() if not k.lower().startswith(prefix)}
    method = msg.get("method", "")
    params = msg.get("params") or {}
    out["mcp-method"] = method
    if (name_key := NAME_BEARING_METHODS.get(method)) and params.get(name_key) is not None:
        out["mcp-name"] = encode_header_value(str(params[name_key]))
    if method == "tools/call" and input_schema and MODERN_HEADERS_SUPPORTED:
        hmap = x_mcp_header_map(input_schema)
        for k, v in mcp_param_headers(hmap, params.get("arguments") or {}).items():
            out[k.lower()] = v
    return out


def param_headers_for(
    input_schema: dict[str, Any] | None, arguments: dict[str, Any]
) -> dict[str, str]:
    """`Mcp-Param-*` headers a modern client mirrors for these arguments (client side)."""
    if not input_schema or not MODERN_HEADERS_SUPPORTED:
        return {}
    return mcp_param_headers(x_mcp_header_map(input_schema), arguments)


def modern_meta(client_name: str = "aegis", version: str = "0.1") -> dict[str, Any]:
    """The per-request `_meta` envelope of the 2026-07-28 era."""
    return {
        PROTOCOL_VERSION_META_KEY: MODERN_VERSION,
        CLIENT_CAPABILITIES_META_KEY: {},
        CLIENT_INFO_META_KEY: {"name": client_name, "version": version},
    }


# ------------------------------------------------------------------ synthetic responses
def complete_result(result: dict[str, Any], era: str) -> dict[str, Any]:
    """2026-07-28 requires resultType on every result; strict legacy clients may reject it."""
    return {**result, "resultType": "complete"} if era == MODERN else result


def blocked_result(
    req_id: Any, era: str, text: str, meta: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A tools/call refusal as a normal tool result with isError=true: the model reads the reason
    and the agent loop continues (a JSON-RPC error often surfaces as a transport failure)."""
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": True}
    if meta:
        result["_meta"] = {"io.aegis/decision": meta}
    return {"jsonrpc": "2.0", "id": req_id, "result": complete_result(result, era)}


def approval_pending_result(
    req_id: Any,
    era: str,
    *,
    control_id: str,
    title: str,
    required_role: str,
    approval_id: str,
    link: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """isError result telling the agent an approval is pending and how to retry."""
    text = (
        f"[Aegis] Approval required ({control_id}): {title}. Needs {required_role} approval. "
        f"Approval {approval_id} is pending - approve at {link}, then retry the same call "
        f"(optionally with header X-Aegis-Approval: {approval_id})."
    )
    return blocked_result(req_id, era, text, meta)


def jsonrpc_error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


# ------------------------------------------------------------------ SSE codec (CRLF-safe)
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
    """Parse an SSE byte stream (split UTF-8, CRLF straddling chunks, keep-alive comments)."""
    decoder = codecs.getincrementaldecoder("utf-8")()
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
                ev.comments.append(line[1:])
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
    buf += decoder.decode(b"", final=True)
    if buf.strip():
        for line in buf.replace("\r\n", "\n").split("\n"):
            if line.startswith("data"):
                data_lines.append(line.partition(":")[2].lstrip(" "))
                dirty = True
    if dirty:
        ev.data = "\n".join(data_lines)
        yield ev


def parse_sse_text(text: str) -> list[SSEEvent]:
    """Synchronous helper: parse a complete SSE body (tests, clients)."""
    out: list[SSEEvent] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        ev = SSEEvent()
        data: list[str] = []
        for line in block.split("\n"):
            if not line:
                continue
            if line.startswith(":"):
                ev.comments.append(line[1:])
                continue
            name, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if name == "data":
                data.append(value)
            elif name == "event":
                ev.event = value
            elif name == "id":
                ev.id = value
        if data or ev.event or ev.comments:
            ev.data = "\n".join(data)
            out.append(ev)
    return out


__all__ = [
    "HEADER_MISMATCH",
    "INTERNAL_ERROR",
    "INVALID_REQUEST",
    "LEGACY",
    "LEGACY_VERSION",
    "MODERN",
    "MODERN_HEADERS_SUPPORTED",
    "MODERN_VERSION",
    "PARSE_ERROR",
    "UNKNOWN_SERVER",
    "UPSTREAM_UNREACHABLE",
    "Rejection",
    "SSEEvent",
    "approval_pending_result",
    "blocked_result",
    "check_modern_request",
    "complete_result",
    "detect_era",
    "is_notification",
    "is_request",
    "is_response",
    "iter_sse",
    "jsonrpc_error",
    "modern_meta",
    "param_headers_for",
    "parse_sse_text",
    "recompute_routing_headers",
]
