"""Control MCP-01: MCP server registry & launch check (shadow MCP servers, stdio launch commands).

* not in `mcp.servers` -> `mcp.unknown_server_action` (default block), finding `mcp.unknown_server`
* stdio launch: `meta["mcp.command"]` must equal `cfg.command` exactly (list compare)
* `cfg.transport` must match the transport the hop arrived on
* tools/call: the tool must match a glob in `cfg.allowed_tools`
"""

from __future__ import annotations

import fnmatch
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding, Interaction, RequestContext

log = logging.getLogger(__name__)


class _Params(BaseModel):
    model_config = ConfigDict(extra="allow")


def _glob(pattern: str, value: str) -> bool:
    try:
        from aegis.core.paths import glob_match

        return bool(glob_match(pattern, value))
    except Exception:  # TODO(integration): fallback until aegis.core.paths lands
        return pattern == "*" or fnmatch.fnmatchcase(value, pattern)


def mcp_section(ctx: RequestContext) -> Any:
    snap = ctx.policy
    if snap is None:
        try:
            from aegis.core.runtime import get_runtime

            snap = get_runtime().policy.snapshot()
        except Exception:
            return None
    return getattr(getattr(snap, "doc", None), "mcp", None)


def server_of(i: Interaction) -> tuple[str, str]:
    """(server, tool) from `mcp_server` / `tool_name` ("<server>.<tool>")."""
    name = i.tool_name or ""
    server = i.mcp_server or (name.split(".", 1)[0] if "." in name else name)
    tool = name.split(".", 1)[1] if "." in name else ""
    if i.mcp_server and name.startswith(i.mcp_server + "."):
        tool = name[len(i.mcp_server) + 1:]
    return server, tool


class McpRegistry(BaseControl):
    id = "MCP-01"
    family = "MCP"
    name = "MCP server registry & launch check"
    kind = "deterministic"
    applies_to = AppliesTo(surfaces={"mcp.init", "mcp.call"})
    owasp = ["MCP09:2025", "MCP04:2025", "ASI04"]
    priority = 20

    async def evaluate(self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
                       ) -> Decision | None:
        extra = set(cfg.params) - set(_Params.model_fields)
        if extra:
            log.debug("MCP-01 ignores params %s", sorted(extra))
        mcp = mcp_section(ctx)
        if mcp is None:
            return None
        server, tool = server_of(interaction)
        servers = dict(getattr(mcp, "servers", {}) or {})
        scfg = servers.get(server)
        if scfg is None:
            action = getattr(mcp, "unknown_server_action", "block") or "block"
            if action == "allow":
                return None
            return self.decide(
                cfg, action=action,
                reason=f"unknown MCP server '{server}' (shadow MCP; not in mcp.servers)",
                findings=[Finding(control_id=self.id, detector="mcp.unknown_server", category="mcp",
                                  severity="high", excerpt=server, meta={"server": server})])
        transport = interaction.meta.get("mcp.transport")
        if transport and transport != scfg.transport:
            return self.decide(
                cfg, reason=f"MCP server '{server}' is registered as {scfg.transport}, "
                            f"reached over {transport}",
                findings=[Finding(control_id=self.id, detector="mcp.transport_mismatch",
                                  category="mcp", severity="high")])
        if interaction.surface == "mcp.init" and "mcp.command" in interaction.meta:
            got = list(interaction.meta.get("mcp.command") or [])
            want = list(scfg.command or [])
            if got != want:
                return self.decide(
                    cfg, reason=f"launch command differs from registry for '{server}'",
                    findings=[Finding(control_id=self.id, detector="mcp.launch_mismatch",
                                      category="mcp", severity="high",
                                      excerpt=" ".join(got)[:160],
                                      meta={"expected": " ".join(want)[:160]})])
        if interaction.surface == "mcp.call" and tool:
            allowed = list(scfg.allowed_tools or ["*"])
            if not any(_glob(p, tool) or _glob(p, f"{server}.{tool}") for p in allowed):
                return self.decide(
                    cfg, reason=f"tool '{tool}' is not in mcp.servers.{server}.allowed_tools",
                    findings=[Finding(control_id=self.id, detector="mcp.tool_not_allowed",
                                      category="mcp", severity="high", excerpt=f"{server}.{tool}")])
        return None


CONTROLS = [McpRegistry()]
