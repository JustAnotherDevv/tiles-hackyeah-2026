"""ctl ACT-01 - Spend guard (purchases, subscriptions, top-ups) (action-guards). STUB: evaluate() returns None."""

from __future__ import annotations

from typing import ClassVar

from aegis.actions.base import ActionGuardBase
from aegis.actions.params import Act01Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext


class SpendGuard(ActionGuardBase):
    id: ClassVar[str] = "ACT-01"
    family: ClassVar[str] = "ACT"
    name: ClassVar[str] = "Spend guard (purchases, subscriptions, top-ups)"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces={"tool.input", "mcp.call", "egress.request"}, directions={"out"})
    owasp: ClassVar[list[str]] = ["LLM03:2026", "ASI02", "ASI09", "LLM06:2026"]
    priority: ClassVar[int] = 30
    params_model = Act01Params

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        return None


CONTROLS = [SpendGuard()]
