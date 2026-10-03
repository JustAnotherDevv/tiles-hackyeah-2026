"""Aegis MCP governance proxy (spike).

Layering, so the gateway can reuse pieces independently:

    detectors   pure functions: tool-definition poisoning scan, argument DLP, result injection scan
    pins        trust-on-first-use pin store for tool definitions (rug-pull defense)
    events      decision events and sinks (JSONL to stdout/stderr, in-memory, callback)
    policy      catalog of upstream servers and per-surface actions
    governor    transport-agnostic JSON-RPC governance (one message in, verdict or rewritten message out)
    protocol    MCP wire helpers: era detection, SSE codec, header recomputation, synthetic results
    http_router FastAPI APIRouter: Streamable HTTP reverse proxy at /mcp/{server}
    stdio_wrapper  `python -m aegis_mcp.stdio_wrapper --server NAME -- <real server command>`
"""

from .events import Decision, EventSink, JsonlSink, MemorySink
from .governor import Governor
from .pins import PinStore
from .policy import Policy, ServerEntry

__all__ = ["Decision", "EventSink", "Governor", "JsonlSink", "MemorySink", "PinStore", "Policy", "ServerEntry"]
