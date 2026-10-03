"""ctl EXE-01 - Dangerous command guard (action-guards). STUB: evaluate() returns None."""

from __future__ import annotations

from typing import ClassVar

from aegis.actions.base import ActionGuardBase
from aegis.actions.params import Exe01Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext


class DangerousCommandGuard(ActionGuardBase):
    id: ClassVar[str] = "EXE-01"
    family: ClassVar[str] = "EXE"
    name: ClassVar[str] = "Dangerous command guard"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces={"tool.input", "mcp.call", "mcp.init"}, directions={"out"})
    owasp: ClassVar[list[str]] = ["ASI05", "MCP05:2025", "LLM10:2026"]
    priority: ClassVar[int] = 20
    params_model = Exe01Params

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        return None


CONTROLS = [DangerousCommandGuard()]
