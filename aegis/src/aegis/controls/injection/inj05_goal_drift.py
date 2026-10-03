"""Control INJ-05 - goal-drift / grounding check (stretch; registered, monitor mode)."""

from __future__ import annotations

from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Interaction, RequestContext


class GoalDrift(BaseControl):
    id = "INJ-05"
    family = "INJ"
    name = "Goal-drift / grounding check"
    kind = "hybrid"
    applies_to = AppliesTo(surfaces={"tool.input", "mcp.call"})
    owasp = ["ASI01", "ASI10"]
    priority = 80

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        return None


CONTROLS = [GoalDrift()]
