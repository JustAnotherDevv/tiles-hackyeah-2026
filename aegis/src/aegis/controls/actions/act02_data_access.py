"""ctl ACT-02 - Data access guard (tables by sensitivity & environment) (action-guards). STUB: evaluate() returns None."""

from __future__ import annotations

from typing import ClassVar

from aegis.actions.base import ActionGuardBase
from aegis.actions.params import Act02Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext


class DataAccessGuard(ActionGuardBase):
    id: ClassVar[str] = "ACT-02"
    family: ClassVar[str] = "ACT"
    name: ClassVar[str] = "Data access guard (tables by sensitivity & environment)"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces={"tool.input", "mcp.call"}, directions={"out"})
    owasp: ClassVar[list[str]] = ["LLM02:2026", "LLM03:2026", "ASI02", "ASI03", "MCP02:2025"]
    priority: ClassVar[int] = 31
    params_model = Act02Params

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        return None


CONTROLS = [DataAccessGuard()]
