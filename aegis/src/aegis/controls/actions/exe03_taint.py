"""ctl EXE-03 - Taint-flow breaker (lethal trifecta) (action-guards). STUB: evaluate() returns None."""

from __future__ import annotations

from typing import ClassVar

from aegis.actions.base import ActionGuardBase
from aegis.actions.params import Exe03Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext


class TaintFlowBreaker(ActionGuardBase):
    id: ClassVar[str] = "EXE-03"
    family: ClassVar[str] = "EXE"
    name: ClassVar[str] = "Taint-flow breaker (lethal trifecta)"
    kind: ClassVar[ControlKind] = "stateful"
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces={"tool.input", "mcp.call", "egress.request"}, directions={"out"})
    owasp: ClassVar[list[str]] = ["ASI01", "ASI02", "MCP06:2025", "MCP10:2025", "LLM02:2026"]
    priority: ClassVar[int] = 34
    params_model = Exe03Params

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        return None


CONTROLS = [TaintFlowBreaker()]
