"""ctl EXE-02 - Filesystem & network scope (SSRF) (action-guards). STUB: evaluate() returns None."""

from __future__ import annotations

from typing import ClassVar

from aegis.actions.base import ActionGuardBase
from aegis.actions.params import Exe02Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext


class ScopeGuard(ActionGuardBase):
    id: ClassVar[str] = "EXE-02"
    family: ClassVar[str] = "EXE"
    name: ClassVar[str] = "Filesystem & network scope (SSRF)"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces={"tool.input", "mcp.call", "egress.request"}, directions={"out"})
    owasp: ClassVar[list[str]] = ["ASI02", "MCP05:2025", "MCP10:2025", "LLM03:2026"]
    priority: ClassVar[int] = 21
    params_model = Exe02Params

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        return None


CONTROLS = [ScopeGuard()]
