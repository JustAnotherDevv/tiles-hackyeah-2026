"""ctl ACT-03 - External send guard (email, webhooks, uploads) (action-guards). STUB: evaluate() returns None."""

from __future__ import annotations

from typing import ClassVar

from aegis.actions.base import ActionGuardBase
from aegis.actions.params import Act03Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext


class ExternalSendGuard(ActionGuardBase):
    id: ClassVar[str] = "ACT-03"
    family: ClassVar[str] = "ACT"
    name: ClassVar[str] = "External send guard (email, webhooks, uploads)"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces={"tool.input", "mcp.call", "egress.request"}, directions={"out"})
    owasp: ClassVar[list[str]] = ["LLM02:2026", "ASI01", "ASI02", "MCP10:2025"]
    priority: ClassVar[int] = 32
    params_model = Act03Params

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        return None


CONTROLS = [ExternalSendGuard()]
