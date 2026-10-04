"""ctl GOV-03 - Tool authorization (RBAC + arg constraints) (action-guards).

* global ``params.deny_tools`` -> block;
* per agent (``rt.org.get_agent``, cached 5 s): ``denied_tools`` match -> block; non-empty
  ``allowed_tools`` without a match -> block (``mcp__srv__tool`` / ``name:qualifier`` normalized);
  the classified action's approval category must be in ``Agent.meta.action_types``;
* ``params.arg_rules {<tool glob>: {<arg path>: <deny RE2>}}`` -> block.
Human members and unknown agents get only the global rules (GOV-01 owns identity).
"""

from __future__ import annotations

from typing import ClassVar

from aegis.actions import runtime as art
from aegis.actions.argpath import get_arg
from aegis.actions.base import ActionGuardBase
from aegis.actions.classify import approval_category, normalize_tool_name, tool_matches
from aegis.actions.commands import matches_any
from aegis.actions.explain import Explain
from aegis.actions.params import Gov03Params
from aegis.actions.rx import rx_search
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext

P = "controls[GOV-03].params"


class ToolAuthorization(ActionGuardBase):
    id: ClassVar[str] = "GOV-03"
    family: ClassVar[str] = "GOV"
    name: ClassVar[str] = "Tool authorization (RBAC + arg constraints)"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"tool.input", "mcp.call"}, directions={"out"}
    )
    owasp: ClassVar[list[str]] = ["LLM03:2026", "ASI02", "ASI03", "MCP02:2025"]
    priority: ClassVar[int] = 15
    params_model = Gov03Params
    default_levers: ClassVar[list[str]] = [
        "org agents[].tools.allow|deny",
        f"{P}.deny_tools",
        f"{P}.arg_rules",
    ]

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        tool = normalize_tool_name(interaction.tool_name)
        if not tool:
            return None
        p: Gov03Params = self.params(cfg)
        ex = Explain(facts={"tool": tool, "agent": ctx.identity.agent_id})
        at = interaction.action_type or f"tool:{tool}"

        def deny(core: str, detector: str, check: str, param: str) -> Decision:
            ex.check(check, core, tool, None, "fail", param)
            return self.hard(
                cfg,
                interaction,
                core=core,
                explain=ex,
                action_type=at,
                findings=[self.finding(f"gov.authz.{detector}", excerpt=tool)],
            )

        if matches_any(tool, p.deny_tools):
            return deny(
                f"{tool} is globally denied by policy",
                "global_deny",
                "deny_tools",
                f"{P}.deny_tools",
            )
        for pat, rules in p.arg_rules.items():
            if not matches_any(tool, [pat]):
                continue
            for path, rx in (rules or {}).items():
                if rx_search(rx, get_arg(interaction, path)):
                    return deny(
                        f"argument {path} of {tool} matches a denied value",
                        "arg_rule",
                        "arg_rules",
                        f"{P}.arg_rules",
                    )
        if not p.enforce_agent_allowlists or not ctx.identity.agent_id:
            return None
        agent = await art.agent_for(ctx)
        if agent is None:
            return None
        name = agent.id
        if any(tool_matches(d, interaction) for d in agent.denied_tools):
            return deny(
                f"{name} is not allowed to call {tool} (denied tool)",
                "agent_deny",
                "denied_tools",
                "org agents[].tools.deny",
            )
        allowed = list(agent.allowed_tools or [])
        if allowed and not any(tool_matches(a, interaction) for a in allowed):
            return deny(
                f"{name} is not allowed to call {tool} (not on its tool allowlist)",
                "agent_allowlist",
                "allowed_tools",
                "org agents[].tools.allow",
            )
        if p.check_action_types:
            cat = approval_category(interaction.action_type)
            types = (agent.meta or {}).get("action_types")
            if cat and isinstance(types, list) and cat not in [str(t) for t in types]:
                return deny(
                    f"{name} may not request {cat} actions",
                    "action_type",
                    "action_types",
                    "org agents[].action_types",
                )
        return None


CONTROLS = [ToolAuthorization()]
