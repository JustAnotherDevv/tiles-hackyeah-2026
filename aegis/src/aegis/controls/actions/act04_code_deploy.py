"""ctl ACT-04 - Code execution & deploy guard (action-guards). STUB: evaluate() returns None."""

from __future__ import annotations

from typing import ClassVar

from aegis.actions.base import ActionGuardBase
from aegis.actions.params import Act04Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext


class CodeDeployGuard(ActionGuardBase):
    id: ClassVar[str] = "ACT-04"
    family: ClassVar[str] = "ACT"
    name: ClassVar[str] = "Code execution & deploy guard"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces={"tool.input", "mcp.call"}, directions={"out"})
    owasp: ClassVar[list[str]] = ["ASI05", "LLM10:2026", "MCP05:2025"]
    priority: ClassVar[int] = 33
    params_model = Act04Params

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        return None


CONTROLS = [CodeDeployGuard()]
