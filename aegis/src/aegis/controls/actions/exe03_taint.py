"""ctl EXE-03 - Taint-flow breaker (lethal trifecta) (action-guards).

Session state ``rt.sessions.get(sid).data["taint"]`` (``aegis.actions.taint``):
* ``on_complete`` (executed, non-dry-run calls only) marks **private** (``private_sources`` such as
  ``acme-crm.*``, a ``db.read`` with sensitivity >= ``private_min_sensitivity``, a ``file.sensitive``
  read) and **untrusted** (``untrusted_sources`` such as ``web.*``/``WebFetch``, or a request to a
  destination class in ``untrusted_destinations``).
* ``enrich`` ticks the turn and, when both flags are live and the call is an exfil sink
  (``exfil_actions`` / ``exfil_tools``), adds ``lethal_trifecta`` to label ``signals`` (A-27) so
  the primary draft (e.g. ACT-03's) routes on it (rule ``send-tainted``).
* ``evaluate`` returns the configured action (balanced: require_approval) with a masked timeline.
"""

from __future__ import annotations

from typing import ClassVar

from aegis.actions import taint
from aegis.actions.base import ActionGuardBase
from aegis.actions.catalog import SENSITIVITY_RANK
from aegis.actions.classify import normalize_tool_name
from aegis.actions.commands import matches_any
from aegis.actions.explain import Explain
from aegis.actions.params import Exe03Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import (
    AppliesTo,
    ControlKind,
    Decision,
    Interaction,
    Outcome,
    RequestContext,
    Verdict,
)

P = "controls[EXE-03].params"
SIGNAL = "lethal_trifecta"


def _add_signal(interaction: Interaction, sig: str) -> None:
    cur = [s for s in (interaction.labels.get("signals") or "").split(",") if s]
    if sig not in cur:
        cur.append(sig)
    interaction.labels["signals"] = ",".join(cur)


class TaintFlowBreaker(ActionGuardBase):
    id: ClassVar[str] = "EXE-03"
    family: ClassVar[str] = "EXE"
    name: ClassVar[str] = "Taint-flow breaker (lethal trifecta)"
    kind: ClassVar[ControlKind] = "stateful"
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"tool.input", "mcp.call", "egress.request"}, directions={"out"}
    )
    owasp: ClassVar[list[str]] = ["ASI01", "ASI02", "MCP06:2025", "MCP10:2025", "LLM02:2026"]
    priority: ClassVar[int] = 34
    params_model = Exe03Params
    default_levers: ClassVar[list[str]] = [
        "controls[EXE-03].action",
        f"{P}.taint_ttl_turns",
        f"{P}.exfil_actions",
    ]

    def _sink(self, i: Interaction, p: Exe03Params) -> bool:
        return (i.action_type or "") in p.exfil_actions or matches_any(i.tool_name, p.exfil_tools)

    async def enrich(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> None:
        await super().enrich(ctx, interaction, cfg)
        if ctx.dry_run or ctx.source == "selftest":
            return
        p: Exe03Params = self.params(cfg)
        taint.tick(ctx.session_id)
        if self._sink(interaction, p) and taint.active(
            ctx.session_id, p.taint_ttl_turns, p.taint_ttl_s
        ):
            _add_signal(interaction, SIGNAL)

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        if SIGNAL not in (interaction.labels.get("signals") or ""):
            return None
        p: Exe03Params = self.params(cfg)
        st = taint.active(ctx.session_id, p.taint_ttl_turns, p.taint_ttl_s) or {}
        timeline = [
            {
                "flag": e.get("flag"),
                "source": e.get("source"),
                "turn": e.get("turn"),
                "ts": e.get("ts"),
            }
            for e in st.get("timeline", [])
        ]
        priv = (st.get("private") or {}).get("source", "private data")
        untr = (st.get("untrusted") or {}).get("source", "untrusted content")
        ex = Explain(
            facts={"timeline": timeline, "sink": interaction.action_type or interaction.tool_name}
        )
        ex.check("private", "session read private data", priv, None, "fail", f"{P}.private_sources")
        ex.check(
            "untrusted",
            "session saw untrusted content",
            untr,
            None,
            "fail",
            f"{P}.untrusted_sources",
        )
        ex.check(
            "sink",
            "call can exfiltrate",
            interaction.action_type or interaction.tool_name,
            None,
            "fail",
            f"{P}.exfil_actions",
        )
        at = interaction.action_type or f"tool:{normalize_tool_name(interaction.tool_name)}"
        core = (
            f"lethal trifecta — this session read private data ({priv}) and untrusted content ({untr}); "
            f"{at} could exfiltrate it"
        )
        agent = ctx.identity.agent_id or ctx.identity.member_id or "someone"
        return await self.soft(
            ctx,
            interaction,
            cfg,
            core=core,
            explain=ex,
            action_type=at,
            title=f"{agent}: send after reading private + untrusted data",
            resource=interaction.resource,
            labels={"signals": interaction.labels.get("signals")},
            findings=[
                self.finding(
                    "exe.taint.lethal_trifecta",
                    category="taint",
                    severity="high",
                    excerpt=f"{priv} + {untr} -> {at}",
                )
            ],
        )

    async def on_complete(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        verdict: Verdict,
        outcome: Outcome,
        cfg: ControlConfig,
    ) -> None:
        if ctx.dry_run or ctx.source == "selftest" or outcome.status_code >= 400:
            return
        if getattr(verdict, "action", "allow") == "block":
            return
        p: Exe03Params = self.params(cfg)
        tool = normalize_tool_name(interaction.tool_name) or interaction.action_type or "?"
        at = interaction.action_type or ""
        sens = (interaction.labels.get("sensitivity") or "").upper()
        private = (
            matches_any(tool, p.private_sources)
            or at == "file.sensitive"
            or (
                at == "db.read"
                and SENSITIVITY_RANK.get(sens, -1)
                >= SENSITIVITY_RANK.get(p.private_min_sensitivity, 2)
            )
        )
        if private:
            taint.mark(ctx.session_id, "private", tool)
        dest = getattr(interaction.destination, "dest_class", None)
        untrusted = matches_any(tool, p.untrusted_sources) or (
            interaction.surface == "egress.request" and dest in p.untrusted_destinations
        )
        if untrusted:
            taint.mark(ctx.session_id, "untrusted", tool)


CONTROLS = [TaintFlowBreaker()]
