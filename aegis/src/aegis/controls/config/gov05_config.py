"""GOV-05 · Config-change governance (who may change what).

Evaluates `config.change` interactions built by `rt.policy.propose()` (`interaction.meta.changes`
= list of PolicyChange, `meta.proposal` = {yaml|patch, base_version, ...}) and routes them through
`approvals.config_rules` via `rt.approvals.route`:

* deny route                                 -> block
* auto route                                 -> allow ("auto: rule protect-more")
* human proposer already satisfies the level -> allow ("authorized: admin ≥ admin (rule …)")
  (not for two-person routes: the proposer co-signs and a second admin must confirm)
* agent proposer                             -> params.agent_proposals (require_approval | block)
* otherwise                                  -> require_approval + ApprovalDraft(kind=config_change)

No `meta.changes` (e.g. Claude Code ConfigChange hook events) -> None (not applicable).
GOV-05 never fails open: an exception surfaces to the pipeline (fail_mode closed -> block).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from aegis.core.policy_schema import ControlConfig, PolicyChange
from aegis.core.protocols import BaseControl
from aegis.core.types import (
    APPROVER_RANK,
    AppliesTo,
    ApprovalDraft,
    ApprovalRoute,
    Decision,
    Finding,
    Identity,
    Interaction,
    RequestContext,
)

log = logging.getLogger(__name__)


class Gov05Params(BaseModel):
    model_config = ConfigDict(extra="allow")

    allow_if_proposer_satisfies: bool = True
    agent_proposals: Literal["require_approval", "block"] = "require_approval"
    title_template: str = "{actor} wants to {summary}"


def _fmt_num(v: Any) -> str:
    if isinstance(v, bool) or v is None:
        return str(v)
    if isinstance(v, (int, float)):
        return f"{v:g}"
    return str(v)


def change_summary(change: PolicyChange) -> str:
    """Human summary, e.g. 'raise team:trading day usd 60 → 75 (+25%)'."""
    if change.summary:
        return change.summary
    kind = change.kind
    if kind.startswith("budget.") and change.scope:
        window = ""
        path = change.path or ""
        if "window=" in path:
            window = " " + path.split("window=", 1)[1].split("]", 1)[0].split(",", 1)[0]
        dim = f" {change.dimension}" if change.dimension else ""
        pct = f" ({change.increase_pct:+g}%)" if change.increase_pct is not None else ""
        verb = kind.split(".", 1)[1]
        return (
            f"{verb} {change.scope}{window}{dim} "
            f"{_fmt_num(change.before)} → {_fmt_num(change.after)}{pct}"
        )
    if change.control_id:
        verb = {"control.disable": "disable", "control.enable": "enable",
                "control.remove": "remove", "control.add": "add"}.get(kind, kind)
        return f"{verb} {change.control_id}"
    if kind.startswith("killswitch"):
        return f"{'engage' if kind.endswith('on') else 'release'} kill switch on {change.scope or 'global'}"
    if change.after is not None and not isinstance(change.after, (dict, list)):
        return f"{kind} {change.path}: {_fmt_num(change.before)} → {_fmt_num(change.after)}"
    return f"{kind} {change.path}"


def _parse_changes(raw: Any) -> tuple[list[Any], list[PolicyChange]]:
    """(raw list kept for routing incl. precomputed `facts`, parsed PolicyChange list)."""
    keep: list[Any] = []
    parsed: list[PolicyChange] = []
    for item in raw or []:
        try:
            if isinstance(item, PolicyChange):
                pc = item
            else:
                pc = PolicyChange.model_validate({k: v for k, v in dict(item).items() if k != "facts"})
        except Exception:
            log.warning("GOV-05 ignored an invalid change entry")
            continue
        keep.append(item)
        parsed.append(pc)
    return keep, parsed


def _actor_name(rt: Any, identity: Identity) -> str:
    svc = getattr(rt, "approvals", None)
    org = getattr(svc, "org", None)
    if identity.agent_id:
        return identity.agent_id
    if org is not None:
        try:
            return org.name(identity.member_id)
        except Exception:
            pass
    return identity.display_name or identity.member_id or "someone"


def _severity(level: str) -> str:
    return {"deny": "high", "owner": "high", "admin": "medium"}.get(level, "low")


class ConfigChangeGovernance(BaseControl):
    id = "GOV-05"
    family = "GOV"
    name = "Config-change governance (who may change what)"
    kind = "deterministic"
    applies_to = AppliesTo(kinds={"config_change"}, surfaces={"config.change"})
    owasp = ["ASI03", "ASI09"]
    priority = 50

    def _rt(self) -> Any:
        from aegis.core.runtime import get_runtime  # type: ignore[import-not-found]

        return get_runtime()

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        raw_changes = interaction.meta.get("changes")
        if not isinstance(raw_changes, list):
            return None
        return self.decide_change(self._rt(), ctx, interaction, cfg, raw_changes)

    def decide_change(
        self,
        rt: Any,
        ctx: RequestContext,
        interaction: Interaction,
        cfg: ControlConfig,
        raw_changes: list[Any],
    ) -> Decision | None:
        params = Gov05Params.model_validate(cfg.params or {})
        keep, changes = _parse_changes(raw_changes)
        identity = ctx.identity
        svc = rt.approvals
        action_type = interaction.action_type or (changes[0].kind if changes else "other")
        info = None
        if hasattr(svc, "route_info"):
            info = svc.route_info(
                kind="config_change", action_type=action_type, requester=identity,
                changes=keep or None, snap=ctx.policy,
            )
            route: ApprovalRoute = info.route
            deciding = info.deciding_index
        else:  # TODO(integration): foreign ApprovalService implementation
            route = svc.route(kind="config_change", action_type=action_type, requester=identity,
                              changes=changes or None)
            deciding = 0
        level = route.required_role
        rule = route.rule_id or "default"
        top_kind = changes[min(deciding, len(changes) - 1)].kind if changes else action_type
        findings = [
            Finding(
                control_id=self.id,
                detector=f"gov.config.{top_kind}",
                category="governance",
                severity=_severity(level),  # type: ignore[arg-type]
                meta={"rule_id": route.rule_id, "required_role": level,
                      "two_person": route.two_person, "changes": len(changes)},
            )
        ]
        if level == "deny":
            d = self.decide(cfg, action="block", reason=f"config change denied by rule {rule}",
                            findings=findings)
            d.severity = "high"
            return d
        if level == "auto":
            return self.decide(cfg, action="allow", reason=f"auto: rule {rule}", findings=findings)
        human = bool(identity.member_id) and not identity.agent_id
        if identity.agent_id:
            if params.agent_proposals == "block":
                return self.decide(cfg, action="block",
                                   reason=f"agents may not change policy (needs {level}, rule {rule})",
                                   findings=findings)
        elif human and params.allow_if_proposer_satisfies and not route.two_person:
            if info is not None and hasattr(svc, "proposer_authorized"):
                authorized = svc.proposer_authorized(identity, info, keep or None)
                role = svc.org.role_of(identity)
            else:
                role = identity.role
                authorized = level != "self" and APPROVER_RANK.get(level, 99) <= {
                    "owner": 3, "admin": 2}.get(role, 0)
            if authorized:
                return self.decide(
                    cfg, action="allow",
                    reason=f"authorized: {role} ≥ {level} (rule {rule})", findings=findings,
                )
        summaries = [change_summary(c) for c in changes] or [action_type]
        top = summaries[min(deciding, len(summaries) - 1)]
        title = params.title_template.format(actor=_actor_name(rt, identity), summary=top)
        scopes = sorted({c.scope for c in changes if c.scope})
        labels = {"change_kinds": ",".join(sorted({c.kind for c in changes})) or action_type}
        if scopes:
            labels["scope"] = ",".join(scopes)
        draft = ApprovalDraft(
            kind="config_change",
            action_type=top_kind,
            title=title,
            summary="; ".join(summaries),
            resource=interaction.resource,
            labels=labels,
            payload={
                "changes": [c if isinstance(c, dict) else c.model_dump(mode="json") for c in keep],
                "proposal": interaction.meta.get("proposal"),
            },
        )
        two = " + a second admin" if route.two_person else ""
        d = self.decide(
            cfg,
            action="require_approval",
            reason=f"needs {level}{two} approval (rule {rule})",
            findings=findings,
            approval=draft,
        )
        d.severity = _severity(level)  # type: ignore[assignment]
        return d


CONTROLS = [ConfigChangeGovernance()]

__all__ = ["CONTROLS", "ConfigChangeGovernance", "Gov05Params", "change_summary"]
