"""Fact builders: the dict an approval rule is matched against.

`OrgCache` is a synchronous snapshot of `rt.org` (members, agents, resources) so routing stays a
pure sync function (`ApprovalService.route` is sync in the frozen protocol). It is loaded in
`start()`, refreshed on bus `org.updated` and every 30 s by the sweeper.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from aegis.approvals.compat import glob_match
from aegis.core.policy_schema import PolicyChange
from aegis.core.types import ROLE_RANK, Agent, Identity, Member

log = logging.getLogger(__name__)

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
#: catalog severities used only when the control is absent from the live snapshot
CATALOG_CRITICAL = frozenset({"DLP-02", "EXE-01", "SIG-01", "SIG-02"})


@dataclass
class OrgCache:
    members: dict[str, Member] = field(default_factory=dict)
    agents: dict[str, Agent] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    loaded: bool = False

    async def load(self, org: Any) -> None:
        if org is None:
            return
        try:
            members = await org.list_members()
            agents = await org.list_agents()
        except Exception:
            log.warning("org cache load failed; routing uses identity fields only", exc_info=True)
            return
        try:
            resources = await org.resources()
        except Exception:
            resources = {}
        self.members = {m.id: m for m in members or []}
        self.agents = {a.id: a for a in agents or []}
        self.resources = dict(resources or {})
        self.loaded = True

    def set(
        self,
        members: Iterable[Member] = (),
        agents: Iterable[Agent] = (),
        resources: Mapping[str, Any] | None = None,
    ) -> None:
        self.members = {m.id: m for m in members}
        self.agents = {a.id: a for a in agents}
        self.resources = dict(resources or {})
        self.loaded = True

    # -------------------------------------------------------------- lookups
    def member(self, member_id: str | None) -> Member | None:
        return self.members.get(member_id) if member_id else None

    def agent(self, agent_id: str | None) -> Agent | None:
        return self.agents.get(agent_id) if agent_id else None

    def name(self, member_id: str | None) -> str:
        m = self.member(member_id)
        return m.name if m else (member_id or "unknown")

    def sponsor_of(self, identity: Identity) -> str | None:
        """The human behind a principal: the member itself, or an agent's sponsor."""
        if identity.agent_id:
            agent = self.agent(identity.agent_id)
            if agent and agent.owner_member_id:
                return agent.owner_member_id
            return identity.member_id
        return identity.member_id

    def role_of(self, identity: Identity) -> str:
        """Effective role: agents are `agent`; members use the seed role (never escalated by a
        caller-supplied Identity), falling back to `identity.role` for unknown members."""
        if identity.agent_id or (identity.role == "agent" and not identity.member_id):
            return "agent"
        m = self.member(identity.member_id)
        if m is not None:
            return m.role
        return identity.role

    def team_of(self, identity: Identity) -> str | None:
        if identity.team_id:
            return identity.team_id
        if identity.agent_id:
            a = self.agent(identity.agent_id)
            if a and a.team_id:
                return a.team_id
        m = self.member(identity.member_id)
        return m.team_id if m else None

    def identity_for(self, principal_id: str | None) -> Identity:
        """Identity for a member id (`u_…`) or an agent id (`name@team`)."""
        if not principal_id:
            return Identity(role="member", member_id="anonymous")
        if principal_id in self.agents or "@" in principal_id:
            a = self.agent(principal_id)
            return Identity(
                org_id=a.org_id if a else "default",
                agent_id=principal_id,
                member_id=a.owner_member_id if a else None,
                team_id=a.team_id if a else None,
                role="agent",
                display_name=a.name if a else principal_id,
            )
        m = self.member(principal_id)
        return Identity(
            org_id=m.org_id if m else "default",
            member_id=principal_id,
            team_id=m.team_id if m else None,
            role=(m.role if m else "member"),  # type: ignore[arg-type]
            display_name=m.name if m else principal_id,
        )

    def members_with_min_role(self, min_role: str) -> list[Member]:
        need = ROLE_RANK.get(min_role, 99)
        return [
            m for m in self.members.values() if m.active and ROLE_RANK.get(m.role, 0) >= need
        ]

    # -------------------------------------------------------------- resources
    def db_table(self, resource: str | None) -> tuple[str | None, str | None]:
        """(sensitivity, env) for `db:<table>` / `db:<schema|db>.<table>`; prod databases first."""
        if not resource or not resource.startswith("db:"):
            return None, None
        name = resource[3:]
        prefix = None
        if "." in name:
            prefix, name = name.rsplit(".", 1)
        dbs = [d for d in (self.resources.get("databases") or []) if isinstance(d, Mapping)]
        dbs.sort(key=lambda d: 0 if str(d.get("environment")) == "prod" else 1)
        for db in dbs:
            if prefix and prefix not in {str(db.get("id")), str(db.get("schema"))}:
                continue
            for table in db.get("tables") or []:
                if isinstance(table, Mapping) and str(table.get("name")) == name:
                    sens = table.get("sensitivity")
                    return (str(sens) if sens else None), (
                        str(db.get("environment")) if db.get("environment") else None
                    )
        return None, None

    def vendor(self, resource: str | None) -> Mapping[str, Any] | None:
        if not resource or not resource.startswith("vendor:"):
            return None
        vid = resource[7:]
        for v in self.resources.get("vendors") or []:
            if isinstance(v, Mapping) and str(v.get("id")) == vid:
                return v
        return None


# ---------------------------------------------------------------- action facts
def requester_facts(identity: Identity, org: OrgCache) -> dict[str, Any]:
    return {
        "team": org.team_of(identity),
        "agent": identity.agent_id,
        "requester_kind": "agent" if identity.agent_id else "member",
        "requester_role": org.role_of(identity),
    }


def facts_for_action(
    *,
    kind: str,
    action_type: str | None,
    requester: Identity,
    amount_usd: float | None,
    resource: str | None,
    labels: Mapping[str, Any] | None,
    profile: str | None,
    org: OrgCache,
) -> dict[str, Any]:
    lab: dict[str, str] = {
        str(k): ("true" if v is True else "false" if v is False else str(v))
        for k, v in (labels or {}).items()
        if v is not None
    }
    # derived labels (producers' labels always win)
    if resource and resource.startswith("db:"):
        sens, env = org.db_table(resource)
        if sens and "sensitivity" not in lab:
            lab["sensitivity"] = sens
        if env and "env" not in lab:
            lab["env"] = env
    vendor = org.vendor(resource)
    if vendor is not None:
        if "vendor_approved" not in lab and vendor.get("approved") is not None:
            lab["vendor_approved"] = "true" if vendor.get("approved") else "false"
        if "recurring" not in lab:
            plans = [p for p in vendor.get("plans") or [] if isinstance(p, Mapping)]
            plan_id = lab.get("plan")
            chosen = next((p for p in plans if plan_id and str(p.get("id")) == plan_id), None)
            if chosen is None and amount_usd is not None:
                chosen = next(
                    (p for p in plans if abs(float(p.get("usd") or -1) - amount_usd) < 0.005), None
                )
            if chosen is not None and chosen.get("recurring"):
                lab["recurring"] = str(chosen.get("recurring"))
    if "dest" not in lab:
        for alias in ("destination", "dest_class"):
            if lab.get(alias):
                lab["dest"] = lab[alias]
                break
    facts = {
        "kind": kind,
        "action": action_type,
        "amount_usd": amount_usd,
        "resource": resource,
        "labels": lab,
        "profile": profile,
        "scope_type": lab.get("scope_type"),
        "increase_pct": _num(lab.get("increase_pct")),
    }
    facts.update(requester_facts(requester, org))
    return facts


# ---------------------------------------------------------------- config-change facts
def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def split_change(raw: Any) -> tuple[PolicyChange | None, dict[str, Any]]:
    """Accept PolicyChange or dict (with an optional precomputed `facts` key)."""
    if isinstance(raw, PolicyChange):
        return raw, {}
    if isinstance(raw, Mapping):
        given = raw.get("facts") if isinstance(raw.get("facts"), Mapping) else {}
        try:
            return PolicyChange.model_validate({k: v for k, v in raw.items() if k != "facts"}), dict(
                given
            )
        except Exception:
            log.warning("invalid policy change ignored for routing kind=%s", raw.get("kind"))
            return None, dict(given)
    return None, {}


def _control_severity(control_id: str | None, change: PolicyChange, snap: Any | None) -> str | None:
    if not control_id:
        return None
    sev: str | None = None
    if snap is not None:
        cfg = None
        try:
            cfg = snap.controls.get(control_id) if getattr(snap, "controls", None) else None
        except Exception:
            cfg = None
        if cfg is None:
            for c in getattr(getattr(snap, "doc", None), "controls", []) or []:
                if getattr(c, "id", None) == control_id:
                    cfg = c
                    break
        if cfg is not None:
            sev = str(getattr(cfg, "severity", None) or "") or None
    if sev is None and control_id in CATALOG_CRITICAL:
        sev = "critical"
    proposed = change.after if str(change.path).endswith("severity") else None
    if isinstance(proposed, str) and proposed in SEVERITY_RANK:
        if sev is None or SEVERITY_RANK[proposed] > SEVERITY_RANK.get(sev, 0):
            sev = proposed
    return sev


def _scope_of(change: PolicyChange) -> str | None:
    if change.scope:
        return change.scope
    path = str(change.path)
    if "kill_switch.global" in path or "kill_switch[global]" in path:
        return "global"
    return None


def _scope_type(scope: str | None) -> str | None:
    if not scope:
        return None
    if scope == "global":
        return "global"
    return scope.split(":", 1)[0] if ":" in scope else None


def _provider_for_model(pattern: str, snap: Any | None) -> str | None:
    doc = getattr(snap, "doc", None)
    if doc is None:
        return None
    for route in doc.models.routes:
        if glob_match(route.match, pattern) or route.match == pattern:
            return route.provider
    return None


def _model_facts(change: PolicyChange, snap: Any | None) -> dict[str, str]:
    out: dict[str, str] = {}
    doc = getattr(snap, "doc", None)
    after = change.after
    patterns = after if isinstance(after, list) else [after]
    before = change.before if isinstance(change.before, list) else []
    new_patterns = [str(p) for p in patterns if p is not None and p not in before]
    if not new_patterns or doc is None:
        return out
    pattern = new_patterns[0]
    provider = _provider_for_model(pattern, snap)
    if provider:
        cfg = doc.providers.get(provider)
        if cfg is not None:
            out["model_dest"] = cfg.destination
        existing = [str(p) for p in doc.models.allowed if p not in new_patterns and p != "*"]
        known = {_provider_for_model(p, snap) for p in existing}
        out["provider_new"] = "false" if provider in known else "true"
    return out


def _signature_severity(change: PolicyChange, feed: Any | None) -> str | None:
    if feed is None:
        return None
    sig_id = change.scope
    if not sig_id:
        path = str(change.path)
        if path.startswith("feeds.overrides."):
            sig_id = path.split(".")[2]
    if not sig_id:
        return None
    try:
        for sig in feed.signatures() or []:
            if str(sig.get("id")) == sig_id:
                sev = sig.get("severity")
                return str(sev) if sev else None
    except Exception:
        return None
    return None


def facts_for_change(
    raw_change: Any,
    *,
    requester: Identity,
    snap: Any | None,
    org: OrgCache,
    profile: str | None,
    feed: Any | None = None,
    action_type: str | None = None,
) -> dict[str, Any]:
    change, given = split_change(raw_change)
    labels: dict[str, str] = {}
    action = action_type
    increase_pct: float | None = None
    scope = None
    if change is not None:
        action = change.kind
        scope = _scope_of(change)
        labels["loosening"] = "true" if change.loosening else "false"
        if change.control_id:
            labels["control_id"] = change.control_id
            sev = _control_severity(change.control_id, change, snap)
            if sev:
                labels["control_severity"] = sev
        if scope:
            labels["scope"] = scope
        increase_pct = change.increase_pct
        if increase_pct is None and change.kind == "budget.raise":
            b, a = _num(change.before), _num(change.after)
            if b is not None and a is not None and b > 0:
                increase_pct = round((a - b) / b * 100.0, 4)
        if change.kind in ("model.allow",):
            for k, v in _model_facts(change, snap).items():
                labels.setdefault(k, v)
        if change.kind == "feed.override":
            sev = _signature_severity(change, feed)
            if sev:
                labels["signature_severity"] = sev
        if change.kind.startswith("killswitch") and scope and scope.startswith("agent:"):
            agent = org.agent(scope[6:])
            sponsor = agent.owner_member_id if agent else None
            labels["requester_is_sponsor"] = (
                "true" if sponsor and sponsor == requester.member_id and not requester.agent_id
                else "false"
            )
    for k, v in given.items():  # precomputed facts win (tests, policy-engine diff)
        labels[str(k)] = "true" if v is True else "false" if v is False else str(v)
    if "increase_pct" in given:
        increase_pct = _num(given["increase_pct"])
    facts: dict[str, Any] = {
        "kind": "config_change",
        "action": action,
        "amount_usd": None,
        "resource": None,
        "labels": labels,
        "profile": profile,
        "scope_type": given.get("scope_type") or _scope_type(scope),
        "increase_pct": increase_pct,
    }
    facts.update(requester_facts(requester, org))
    return facts


def self_members_for_changes(
    changes: Iterable[Any], requester: Identity, org: OrgCache
) -> list[str]:
    """Who counts as `self` for a config change: the sponsor of an agent-scoped change, the
    member of a member-scoped change, otherwise the proposer."""
    out: list[str] = []
    for raw in changes:
        change, _ = split_change(raw)
        scope = _scope_of(change) if change is not None else None
        if scope and scope.startswith("agent:"):
            a = org.agent(scope[6:])
            if a and a.owner_member_id:
                out.append(a.owner_member_id)
                continue
        if scope and scope.startswith("member:"):
            out.append(scope[7:])
            continue
        sponsor = org.sponsor_of(requester)
        if sponsor:
            out.append(sponsor)
    return sorted(set(out))


__all__ = [
    "CATALOG_CRITICAL", "SEVERITY_RANK", "OrgCache", "facts_for_action", "facts_for_change",
    "requester_facts", "self_members_for_changes", "split_change",
]
