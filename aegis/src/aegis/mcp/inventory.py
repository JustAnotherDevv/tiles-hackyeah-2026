"""MCP inventory views for the dashboard (`/security/mcp`).

Pydantic mirrors of `McpServerView` / `McpToolView` (web/src/api/types.ts, CONTRACTS section 5.5;
field names and enums exactly as the frozen TS types).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from aegis.mcp.detect import snippet
from aegis.mcp.pins import PinStore, diff_summary, diff_tools


class McpToolView(BaseModel):
    name: str
    description_preview: str
    hash: str
    status: Literal["approved", "pending", "quarantined", "changed"]
    reasons: list[str]
    first_seen: str
    last_seen: str


class McpServerView(BaseModel):
    name: str
    transport: Literal["http", "stdio"]
    url: str | None
    destination: Literal["local", "remote", "third_party"]
    status: Literal["registered", "unknown", "blocked", "unreachable"]
    tools: list[McpToolView]


@dataclass
class InventoryState:
    """Transport-side facts not stored in pins."""

    last_error: dict[str, tuple[str, float]] = field(default_factory=dict)  # server -> (msg, ts)
    last_ok: dict[str, float] = field(default_factory=dict)
    unknown_attempts: dict[str, float] = field(default_factory=dict)  # server -> ts

    def unreachable(self, server: str) -> bool:
        err = self.last_error.get(server)
        return bool(err and err[1] >= self.last_ok.get(server, 0.0))


def _iso(ts: str | None) -> str:
    return ts or datetime.now(UTC).isoformat()


def _preview(text: str, mask: Any = None) -> str:
    if mask is not None:
        try:
            return str(mask(text, 160))
        except Exception:
            pass
    return snippet(text, 160)


def tool_view(pins: PinStore, server: str, name: str, mask: Any = None) -> McpToolView:
    pin, cand = pins.get(server, name)
    definition = (cand.definition if cand and cand.reason != "manual" else None) or \
        pins.display_definition(server, name)
    desc = str(definition.get("description") or definition.get("title") or "")
    return McpToolView(
        name=name,
        description_preview=_preview(desc, mask),
        hash=pins.display_hash(server, name),
        status=pins.view_status(server, name),  # type: ignore[arg-type]
        reasons=pins.reasons(server, name),
        first_seen=_iso(pins.first_seen.get((server, name))),
        last_seen=_iso(pins.last_seen.get((server, name))),
    )


def build_inventory(snap: Any, pins: PinStore, state: InventoryState, mask: Any = None
                    ) -> list[McpServerView]:
    """registered (policy) ∪ seen (pins) ∪ attempted-unknown servers."""
    servers_cfg = dict(getattr(getattr(getattr(snap, "doc", None), "mcp", None), "servers", {}) or {})
    names: list[str] = list(servers_cfg)
    for s in sorted(pins.known_servers() | set(state.unknown_attempts)):
        if s not in names:
            names.append(s)
    out: list[McpServerView] = []
    for name in names:
        cfg = servers_cfg.get(name)
        if cfg is not None:
            status = "unreachable" if state.unreachable(name) else "registered"
            transport, url, dest = cfg.transport, cfg.url, cfg.destination
        else:
            status = "blocked" if name in state.unknown_attempts else "unknown"
            transport, url, dest = "http", None, "third_party"
        tools = [tool_view(pins, name, t, mask) for t in pins.tool_names(name)]
        out.append(McpServerView(name=name, transport=transport, url=url, destination=dest,
                                 status=status, tools=tools))  # type: ignore[arg-type]
    return out


def tool_detail(pins: PinStore, server: str, name: str, mask: Any = None) -> dict[str, Any] | None:
    """`GET /api/mcp/servers/{s}/tools/{t}`: pinned + candidate definitions, diff, findings."""
    pin, cand = pins.get(server, name)
    if pin is None and cand is None:
        return None
    diff = None
    if cand is not None:
        diff = cand.diff or (diff_tools(pin.definition, cand.definition) if pin else None)
    return {
        "tool": tool_view(pins, server, name, mask).model_dump(),
        "pinned": None if pin is None else {"hash": pin.hash, "definition": pin.definition,
                                            "approved_by": pin.approved_by},
        "candidate": None if cand is None else {"hash": cand.hash, "definition": cand.definition,
                                                "reason": cand.reason,
                                                "detected_at": cand.detected_at},
        "diff": diff,
        "diff_summary": diff_summary(diff) if diff else None,
        "findings": list(cand.findings) if cand else [],
        "approval_id": cand.approval_id if cand else None,
        "generated_at": time.time(),
    }


__all__ = ["InventoryState", "McpServerView", "McpToolView", "build_inventory", "tool_detail", "tool_view"]
