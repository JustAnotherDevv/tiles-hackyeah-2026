"""ctl GOV-04 - Human approval gate for other high-impact tools (action-guards).

``params.approve_tools`` (globs) -> soft ``require_approval`` with
``action_type = interaction.action_type or "tool:<tool_name>"`` (A-26). Also owns
``max_pending_per_agent`` / ``flood_check``, read by every action-guard soft decision
(``aegis.actions.drafts.flood_check``) to stop approval flooding.
"""

from __future__ import annotations

from typing import ClassVar

from aegis.actions.base import ActionGuardBase
from aegis.actions.classify import normalize_tool_name
from aegis.actions.commands import matches_any
from aegis.actions.explain import Explain
from aegis.actions.params import Gov04Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext

P = "controls[GOV-04].params"


class ApprovalGate(ActionGuardBase):
    id: ClassVar[str] = "GOV-04"
    family: ClassVar[str] = "GOV"
    name: ClassVar[str] = "Human approval gate for other high-impact tools"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"tool.input", "mcp.call", "egress.request"}, directions={"out"}
    )
    owasp: ClassVar[list[str]] = ["ASI09", "ASI02", "LLM03:2026"]
    priority: ClassVar[int] = 40
    params_model = Gov04Params
    default_levers: ClassVar[list[str]] = [f"{P}.approve_tools", "approvals.rules[tool-approve]"]

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        tool = normalize_tool_name(interaction.tool_name)
        if not tool:
            return None
        p: Gov04Params = self.params(cfg)
        hit = next((pat for pat in p.approve_tools if matches_any(tool, [pat])), None)
        if hit is None:
            return None
        at = interaction.action_type or f"tool:{tool}"
        agent = ctx.identity.agent_id or ctx.identity.member_id or "someone"
        ex = Explain(facts={"tool": tool, "pattern": hit})
        ex.check("approve_tools", "high-impact tool", tool, hit, "fail", f"{P}.approve_tools")
        return await self.soft(
            ctx,
            interaction,
            cfg,
            core=f"{tool} is a high-impact tool",
            action_type=at,
            title=f"{agent} wants to call {tool}",
            explain=ex,
            resource=interaction.resource,
            findings=[self.finding("gov.approval_gate", severity="medium", excerpt=tool)],
        )


CONTROLS = [ApprovalGate()]
