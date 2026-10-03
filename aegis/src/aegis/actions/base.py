"""Shared base class for the nine action-guard controls.

* ``enrich`` -> ``ensure_classified`` over the evaluated policy's ``actions:`` (idempotent).
* ``soft()``  -> the control's configured action (default ``require_approval`` + ApprovalDraft,
  judge-flippable to ``block``/``log``), with the shared anti-flooding check.
* ``hard()``  -> ``block`` regardless of ``cfg.action`` (hard caps, RESTRICTED data, prod DDL).
* ``note()``  -> an explained ``allow``/``log`` decision (e.g. "standing grant").
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from pydantic import BaseModel

from aegis.actions import drafts
from aegis.actions import runtime as art
from aegis.actions.classify import ensure_classified
from aegis.actions.explain import Explain, mask, reason_line
from aegis.actions.params import Gov04Params
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import Decision, Finding, Interaction, RequestContext

log = logging.getLogger(__name__)


class ActionGuardBase(BaseControl):
    params_model: ClassVar[type[BaseModel]] = BaseModel
    default_levers: ClassVar[list[str]] = []

    # ------------------------------------------------------------------ phases
    async def enrich(self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig) -> None:
        ensure_classified(interaction, art.action_rules(ctx))

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:  # pragma: no cover - overridden
        return None

    # ------------------------------------------------------------------ helpers
    def params(self, cfg: ControlConfig) -> Any:
        return art.params_for(cfg, self.params_model)

    def finding(self, detector: str, *, category: str = "governance", severity: str = "high",
                excerpt: str | None = None, data_class: str | None = None, entity: str | None = None,
                **meta: Any) -> Finding:
        return Finding(
            control_id=self.id, detector=detector, category=category, severity=severity,  # type: ignore[arg-type]
            excerpt=mask(excerpt, 120) if excerpt else None, data_class=data_class,  # type: ignore[arg-type]
            entity=entity, meta={k: v for k, v in meta.items() if v is not None},
        )

    def _meta(self, interaction: Interaction, action_type: str | None, explain: Explain | None,
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
        ex = explain or Explain()
        for lv in self.default_levers:
            ex.lever(lv)
        meta: dict[str, Any] = {
            "action_type": action_type or interaction.action_type,
            "capability": interaction.labels.get("capability"),
            "explain": ex.to_dict(),
        }
        if extra:
            meta.update(extra)
        return meta

    def hard(self, cfg: ControlConfig, interaction: Interaction, *, core: str,
             findings: list[Finding] | None = None, explain: Explain | None = None,
             action_type: str | None = None, suffix: str = "", **meta: Any) -> Decision:
        """Block that no approval can lift (hard cap, RESTRICTED, prod DDL)."""
        reason = reason_line("block", core, suffix=suffix)
        if explain is not None and not explain.summary:
            explain.summary = reason
        return self.decide(cfg, action="block", reason=reason, findings=findings,
                           meta=self._meta(interaction, action_type, explain, meta))

    def note(self, cfg: ControlConfig, interaction: Interaction, *, core: str, action: str = "allow",
             explain: Explain | None = None, findings: list[Finding] | None = None,
             action_type: str | None = None, **meta: Any) -> Decision:
        """Explained allow/log (shows up in the decision drawer, never changes the verdict)."""
        reason = reason_line(action, core)
        if explain is not None and not explain.summary:
            explain.summary = reason
        return self.decide(cfg, action=action, reason=reason, findings=findings,
                           meta=self._meta(interaction, action_type, explain, meta))

    async def soft(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        cfg: ControlConfig,
        *,
        core: str,
        action_type: str,
        title: str,
        findings: list[Finding] | None = None,
        explain: Explain | None = None,
        summary: str | None = None,
        amount_usd: float | None = None,
        resource: str | None = None,
        labels: dict[str, Any] | None = None,
        action: str | None = None,
        suffix: str = "",
        **meta: Any,
    ) -> Decision:
        """The control's configured action (default require_approval + draft)."""
        act = action or cfg.action
        explain = explain or Explain()
        if act == "redact":  # not meaningful for action guards
            act = "require_approval"
        if act == "require_approval":
            gov04 = art.control_params(ctx, "GOV-04", Gov04Params)
            if gov04.flood_check:
                flood = await drafts.flood_check(ctx, interaction, gov04.max_pending_per_agent)
                if flood:
                    explain.check("flood", "pending approvals for this agent", None,
                                  gov04.max_pending_per_agent, "fail",
                                  "controls[GOV-04].params.max_pending_per_agent")
                    fs = [*(findings or []), self.finding("act.flood", category="approval", severity="medium")]
                    return self.hard(cfg, interaction, core=flood, findings=fs, explain=explain,
                                     action_type=action_type, **meta)
        reason = reason_line(act, core, suffix=suffix if act == "block" else "")
        explain.summary = explain.summary or reason
        decision_meta = self._meta(interaction, action_type, explain, meta)
        if act != "require_approval":
            return self.decide(cfg, action=act, reason=reason, findings=findings, meta=decision_meta)
        draft = drafts.build_draft(
            control_id=self.id, interaction=interaction, action_type=action_type, title=title,
            summary=summary or reason, amount_usd=amount_usd, resource=resource, labels=labels,
            facts=explain.facts, checks=explain.checks, reason=reason, explain=explain.to_dict(),
        )
        return self.decide(cfg, action="require_approval", reason=reason, findings=findings,
                           approval=draft, meta=decision_meta)


__all__ = ["ActionGuardBase"]
