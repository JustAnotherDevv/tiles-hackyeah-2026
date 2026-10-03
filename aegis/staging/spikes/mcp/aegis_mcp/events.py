"""Decision events: one JSON object per governed MCP message.

Schema (stable keys, safe to log - never raw secrets/PII; DLP evidence is masked):

    {"type": "aegis.mcp.decision", "id": "mcp_…", "ts": "2026-10-03T15:21:27.123Z",
     "server": "crm", "transport": "http|stdio", "era": "legacy|modern", "session": "…|null",
     "direction": "client->server|server->client", "method": "tools/call", "tool": "create_ticket",
     "decision": "allow|redact|block|hide|sanitize|alert|observe",
     "controls": ["DLP-04"], "reasons": ["…"], "findings": [{rule, category, severity, where, evidence}],
     "detail": {...}, "latency_us": 412}

In the gateway, swap JsonlSink for a sink that appends to the hash-chained audit log and
publishes to the SSE bus that feeds the dashboard.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, TextIO


@dataclass
class Decision:
    server: str
    method: str
    decision: str
    direction: str = "client->server"
    tool: str | None = None
    controls: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    findings: list[dict[str, str]] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    transport: str = "http"
    era: str = "legacy"
    session: str | None = None
    latency_us: int | None = None
    id: str = field(default_factory=lambda: "mcp_" + uuid.uuid4().hex[:12])
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
    type: str = "aegis.mcp.decision"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not d["detail"]:
            d.pop("detail")
        head = {k: d.pop(k) for k in ("type", "id", "ts")}
        return {**head, **d}


class EventSink(Protocol):
    def __call__(self, decision: Decision) -> None: ...


class JsonlSink:
    """Writes one JSON line per decision. Use stream=sys.stderr inside the stdio wrapper:
    stdout there carries JSON-RPC and must never see anything else."""

    def __init__(self, stream: TextIO | None = None, *, only_notable: bool = False) -> None:
        self.stream = stream or sys.stdout
        self.only_notable = only_notable
        self._lock = threading.Lock()

    def __call__(self, decision: Decision) -> None:
        if self.only_notable and decision.decision in ("allow", "observe"):
            return
        line = json.dumps(decision.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.stream.write(line + "\n")
            self.stream.flush()


class MemorySink:
    """Keeps the last N decisions (tests, /aegis/mcp/events admin endpoint)."""

    def __init__(self, limit: int = 500) -> None:
        self.limit = limit
        self.events: list[dict[str, Any]] = []

    def __call__(self, decision: Decision) -> None:
        self.events.append(decision.to_dict())
        del self.events[: -self.limit]


class FanoutSink:
    def __init__(self, *sinks: Callable[[Decision], None]) -> None:
        self.sinks = list(sinks)

    def __call__(self, decision: Decision) -> None:
        for sink in self.sinks:
            sink(decision)


def now_us() -> int:
    return time.perf_counter_ns() // 1000
