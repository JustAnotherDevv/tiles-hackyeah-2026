"""ctl GOV-04 - Human approval gate for other high-impact tools (action-guards). STUB: evaluate() returns None."""

from __future__ import annotations

from typing import ClassVar

from aegis.actions.base import ActionGuardBase
from aegis.actions.params import Gov04Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext


class ApprovalGate(ActionGuardBase):
    id: ClassVar[str] = "GOV-04"
    family: ClassVar[str] = "GOV"
    name: ClassVar[str] = "Human approval gate for other high-impact tools"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces={"tool.input", "mcp.call", "egress.request"}, directions={"out"})
    owasp: ClassVar[list[str]] = ["ASI09", "ASI02", "LLM03:2026"]
    priority: ClassVar[int] = 40
    params_model = Gov04Params

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        return None


CONTROLS = [ApprovalGate()]
