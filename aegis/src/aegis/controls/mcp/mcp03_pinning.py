"""Control MCP-03: tool pinning (rug pull) & shadowing.

Pure: reads the pin state the MCP transport publishes in `Interaction.meta["mcp.pin"]`
(missing → no opinion, which is what policy self-tests see).

On `mcp.list` (`meta["mcp.pin"]` = {status: new|match|changed|quarantined, hash, pinned_hash,
baseline, reason, approval_id}):
* changed & `mcp.on_tool_change` ∈ {block, require_approval, redact} → block (the transport files
  the `mcp_pin` re-approval); ∈ {log, allow} → log (old pin kept, tool stays callable)
* new after baseline & `params.new_tool_after_baseline == "quarantine"` → block
* manual quarantine → block
* collision (shadowing): same/near name pinned on another server → `params.collision_action`
On `mcp.call` (`meta["mcp.pin"]` = callable status {status: pinned|changed|quarantined|pending|unvetted}):
* changed → block naming the pending `apr_…` (unless on_tool_change is log/allow)
* quarantined → block; pending → block; unvetted → `params.unvetted_call` (scan ran already → block;
  allow → no opinion)
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from aegis.controls.mcp.mcp01_registry import mcp_section, server_of
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding, Interaction, RequestContext

log = logging.getLogger(__name__)


class _Params(BaseModel):
    model_config = ConfigDict(extra="ignore")

    unvetted_call: Literal["scan", "block", "allow"] = "scan"
    new_tool_after_baseline: Literal["quarantine", "pin"] = "quarantine"
    collision_distance: int = 2
    collision_action: Literal["allow", "log", "redact", "require_approval", "block"] = "log"
    scan_on_startup: bool = False


def _levenshtein(a: str, b: str) -> int:
    try:
        from rapidfuzz.distance import Levenshtein

        return int(Levenshtein.distance(a, b))
    except Exception:  # pragma: no cover - rapidfuzz is a dependency; tiny fallback
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
            prev = cur
        return prev[-1]


def _act(cfg: ControlConfig) -> str:
    """MCP-03 either blocks or (permissive profile) logs; re-approval goes through mcp_pin."""
    return "log" if cfg.action in ("log", "allow") else "block"


class McpPinning(BaseControl):
    id = "MCP-03"
    family = "MCP"
    name = "Tool pinning (rug pull) & shadowing"
    kind = "stateful"
    applies_to = AppliesTo(surfaces={"mcp.list", "mcp.call"})
    owasp = ["MCP03:2025", "MCP04:2025", "ASI02", "ASI04"]
    priority = 30

    def _params(self, cfg: ControlConfig) -> _Params:
        unknown = set(cfg.params) - set(_Params.model_fields)
        if unknown:
            log.warning("MCP-03 unknown params ignored: %s", sorted(unknown))
        try:
            return _Params.model_validate(cfg.params)
        except Exception:
            log.warning("MCP-03 invalid params; using defaults", exc_info=True)
            return _Params()

    def _finding(self, detector: str, pin: dict[str, Any], **meta: Any) -> Finding:
        return Finding(control_id=self.id, detector=detector, category="mcp", severity="high",
                       meta={"pinned_hash": pin.get("pinned_hash"), "hash": pin.get("hash"), **meta})

    async def evaluate(self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
                       ) -> Decision | None:
        pin = interaction.meta.get("mcp.pin")
        if not isinstance(pin, dict):
            return None
        p = self._params(cfg)
        mcp = mcp_section(ctx)
        on_change = str(getattr(mcp, "on_tool_change", "block") or "block")
        server, tool = server_of(interaction)
        status = pin.get("status")
        if interaction.surface == "mcp.list":
            return self._on_list(cfg, p, pin, status, on_change, server, tool, interaction)
        if interaction.meta.get("mcp.pinned") is False:
            return None
        return self._on_call(cfg, p, pin, status, on_change, server, tool)

    def _on_list(self, cfg: ControlConfig, p: _Params, pin: dict[str, Any], status: Any,
                 on_change: str, server: str, tool: str, interaction: Interaction) -> Decision | None:
        if status == "changed":
            if on_change in ("log", "allow"):
                return self.decide(cfg, action="log", findings=[self._finding("mcp.definition_changed", pin)],
                                   reason="definition changed since pinned (on_tool_change=log: old pin kept)")
            return self.decide(
                cfg, action=_act(cfg),
                reason="definition changed since pinned (possible rug pull); re-approval required",
                findings=[self._finding("mcp.definition_changed", pin, diff=pin.get("diff"))])
        if status == "new" and pin.get("baseline") and p.new_tool_after_baseline == "quarantine":
            return self.decide(cfg, action=_act(cfg),
                               reason="tool appeared after the server's tool set was pinned; approval required",
                               findings=[self._finding("mcp.new_after_baseline", pin)])
        if status == "quarantined" and pin.get("reason") == "manual":
            return self.decide(cfg, action=_act(cfg), reason="tool quarantined by admin",
                               findings=[self._finding("mcp.quarantined", pin)])
        if status == "new" and p.collision_action != "allow":
            return self._collision(cfg, p, server, tool)
        return None

    def _collision(self, cfg: ControlConfig, p: _Params, server: str, tool: str) -> Decision | None:
        if not tool:
            return None
        try:
            from aegis.mcp.service import get_service

            svc = get_service()
            pinned = svc.pins.pinned_tools() if svc is not None else {}
        except Exception:
            pinned = {}
        for other, tools in pinned.items():
            if other == server:
                continue
            for name in tools:
                exact = name == tool
                near = len(tool) >= 5 and len(name) >= 5 and _levenshtein(name, tool) <= p.collision_distance
                if exact or near:
                    return self.decide(
                        cfg, action=p.collision_action if p.collision_action in ("log", "block") else "block",
                        reason=f"tool name collides with pinned {other}.{name} (possible shadowing)",
                        findings=[Finding(control_id=self.id, detector="mcp.tool_collision",
                                          category="mcp", severity="medium",
                                          meta={"other": f"{other}.{name}", "exact": exact})])
        return None

    def _on_call(self, cfg: ControlConfig, p: _Params, pin: dict[str, Any], status: Any,
                 on_change: str, server: str, tool: str) -> Decision | None:
        apr = pin.get("approval_id")
        if status == "changed":
            if on_change in ("log", "allow"):
                return self.decide(cfg, action="log",
                                   reason="definition changed since pinned (on_tool_change=log)",
                                   findings=[self._finding("mcp.definition_changed", pin)])
            pending = f"; approval {apr} pending (admin)" if apr else "; re-approval required (admin)"
            return self.decide(cfg, action=_act(cfg),
                               reason=f"tool definition changed since pinned (possible rug pull){pending}",
                               findings=[self._finding("mcp.definition_changed", pin)],
                               meta={"approval_id": apr})
        if status == "quarantined":
            why = "admin" if pin.get("reason") == "manual" else "MCP-02 poisoning scan"
            return self.decide(cfg, action=_act(cfg), reason=f"tool quarantined ({why})",
                               findings=[self._finding("mcp.quarantined", pin)])
        if status == "pending":
            pending = f"; approval {apr} pending (admin)" if apr else ""
            return self.decide(cfg, action=_act(cfg),
                               reason=f"tool appeared after the server's tool set was pinned{pending}",
                               findings=[self._finding("mcp.new_after_baseline", pin)])
        if status == "unvetted":
            if p.unvetted_call == "allow":
                return None
            return self.decide(cfg, action=_act(cfg),
                               reason=f"tool '{server}.{tool}' was never vetted in a tools/list through Aegis",
                               findings=[self._finding("mcp.unvetted", pin)])
        return None


CONTROLS = [McpPinning()]
