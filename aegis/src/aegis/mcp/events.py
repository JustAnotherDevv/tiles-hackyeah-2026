"""MCP tool events: SSE `mcp.tool`, audit `mcp.tool_changed`, throttled `system` warnings.

Decision events (allow/redact/block per hop) are NOT emitted here: they are pipeline verdicts
(audit `decision` + metrics + SSE `decision`, automatic). This module only covers pin-state
transitions and transport incidents. `JsonlSink` is kept for the stdio wrapper's debugging.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from typing import Any, TextIO

from aegis.core.types import AuditEvent, Identity, new_id

log = logging.getLogger(__name__)

_WARN_EVERY_S = 60.0
_last_warning: dict[str, float] = {}


def publish_tool_event(rt: Any, server: str, tool: str, status: str, reason: str) -> None:
    """SSE `mcp.tool` with exactly `{server, tool, status, reason}` (SseEventMap['mcp.tool'])."""
    try:
        rt.bus.publish("mcp.tool", {"server": server, "tool": tool, "status": status,
                                    "reason": reason})
    except Exception:
        log.warning("mcp.tool publish failed server=%s tool=%s", server, tool, exc_info=True)


async def audit_tool_change(
    rt: Any,
    *,
    server: str,
    tool: str,
    from_status: str | None,
    to_status: str,
    reason: str = "",
    pinned_hash: str | None = None,
    hash_: str | None = None,
    approval_id: str | None = None,
    actor: Identity | None = None,
    event: str = "status",
    extra: dict[str, Any] | None = None,
) -> None:
    """Audit `mcp.tool_changed` (data = {server, tool, from, to, pinned_hash, hash, approval_id, actor})."""
    data: dict[str, Any] = {
        "event": event, "server": server, "tool": tool, "from": from_status, "to": to_status,
        "reason": reason, "pinned_hash": pinned_hash, "hash": hash_, "approval_id": approval_id,
        "actor": actor.principal if actor else None,
    }
    if extra:
        data.update(extra)
    try:
        await rt.audit.record(AuditEvent(
            event_id=new_id("evt"), event_type="mcp.tool_changed", actor=actor,
            kind="mcp", tool_name=f"{server}.{tool}" if tool else None,
            resource=f"mcp:{server}.{tool}" if tool else f"mcp:{server}", reason=reason, data=data))
    except Exception:
        log.warning("mcp.tool_changed audit failed server=%s tool=%s", server, tool, exc_info=True)


async def tool_transition(
    rt: Any,
    *,
    server: str,
    tool: str,
    from_status: str | None,
    to_status: str,
    reason: str,
    pinned_hash: str | None = None,
    hash_: str | None = None,
    approval_id: str | None = None,
    actor: Identity | None = None,
) -> None:
    """Publish + audit one pin-state transition."""
    publish_tool_event(rt, server, tool, to_status, reason)
    await audit_tool_change(rt, server=server, tool=tool, from_status=from_status, to_status=to_status,
                            reason=reason, pinned_hash=pinned_hash, hash_=hash_,
                            approval_id=approval_id, actor=actor)


def system_warning(rt: Any, server: str, message: str, *, level: str = "warning") -> bool:
    """SSE `system` warning, throttled to 1 per minute per server. Returns True if sent."""
    now = time.monotonic()
    if now - _last_warning.get(server, -1e9) < _WARN_EVERY_S:
        return False
    _last_warning[server] = now
    try:
        rt.bus.publish("system", {"level": level, "message": message, "component": f"mcp:{server}"})
    except Exception:
        log.warning("system warning publish failed server=%s", server, exc_info=True)
    return True


class JsonlSink:
    """One JSON line per event (stdio wrapper `--events-file`; stdout must stay JSON-RPC only)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stderr
        self._lock = threading.Lock()

    def __call__(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str)
        with self._lock:
            self.stream.write(line + "\n")
            self.stream.flush()


__all__ = ["JsonlSink", "audit_tool_change", "publish_tool_event", "system_warning", "tool_transition"]
