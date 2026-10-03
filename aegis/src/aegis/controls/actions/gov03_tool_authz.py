"""ctl GOV-03 - Tool authorization (RBAC + arg constraints) (action-guards). STUB: evaluate() returns None."""

from __future__ import annotations

from typing import ClassVar

from aegis.actions.base import ActionGuardBase
from aegis.actions.params import Gov03Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext


class ToolAuthorization(ActionGuardBase):
    id: ClassVar[str] = "GOV-03"
    family: ClassVar[str] = "GOV"
    name: ClassVar[str] = "Tool authorization (RBAC + arg constraints)"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces={"tool.input", "mcp.call"}, directions={"out"})
    owasp: ClassVar[list[str]] = ["LLM03:2026", "ASI02", "ASI03", "MCP02:2025"]
    priority: ClassVar[int] = 15
    params_model = Gov03Params

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        return None


CONTROLS = [ToolAuthorization()]
