"""Permission matrix, org-op authorization and `whoami` permissions (plan 08 section 2.6).

Levels come from `rt.approvals.route(...)` over the live policy (so a judge editing an approval
rule changes the matrix), floored by hard-coded minimums policy can never lower.
"""

from __future__ import annotations

import logging
from typing import Any

from aegis.core.policy_schema import PolicyChange, PolicySnapshot
from aegis.core.types import APPROVER_RANK, ROLE_RANK, Identity, Member
from aegis.org.models import Authz, OrgCache

log = logging.getLogger(__name__)

ROLES_ALL = ["owner", "admin", "member", "agent"]
MEMBER_ROLES = ("owner", "admin", "member")
DEST_RANK = {"local": 0, "remote": 1, "third_party": 2}

#: action_type -> (default level when no org rule matches, hard floor policy cannot lower)
ORG_OPS: dict[str, tuple[str, str]] = {
    "org.member.create": ("admin", "admin"),
    "org.member.create_admin": ("owner", "admin"),
    "org.member.create_owner": ("owner", "owner"),
    "org.member.update": ("admin", "admin"),
    "org.role.promote_admin": ("owner", "admin"),
    "org.role.promote_owner": ("owner", "owner"),
    "org.role.demote_admin": ("owner", "admin"),
    "org.role.demote_owner": ("owner", "owner"),
    "org.member.deactivate": ("admin", "admin"),
    "org.member.deactivate_privileged": ("owner", "owner"),
    "org.agent.update": ("admin", "admin"),
    "org.agent.widen_destination": ("owner", "admin"),
    "org.agent.key": ("admin", "admin"),
    "org.agent.create": ("admin", "admin"),
}

#: config-change fallbacks (contract section 4.3 config_rules) when rt.approvals.route fails
_STATIC_CONFIG = {
    "control.threshold.tighten": "admin",
    "control.disable": "owner",
    "budget.raise.small": "admin",
    "budget.raise.large": "owner",
    "killswitch.on": "admin",
    "killswitch.off": "admin",
    "model.allow": "admin",
}


# ---------------------------------------------------------------- level helpers


def level_max(a: str, b: str) -> str:
    return a if APPROVER_RANK.get(a, 0) >= APPROVER_RANK.get(b, 0) else b


def satisfies(role: str | None, level: str) -> bool:
    """Does a human with `role` satisfy approver `level` on their own? (agents never do)."""
    if level == "auto":
        return True
    if level == "deny" or not role or role == "agent":
        return False
    return ROLE_RANK.get(role, 0) >= APPROVER_RANK.get(level, 99)


def roles_satisfying(level: str) -> list[str]:
    return [r for r in MEMBER_ROLES if satisfies(r, level)] + (["agent"] if level == "auto" else [])


def viewer_member(cache: OrgCache, viewer: Identity) -> Member | None:
    return cache.members.get(viewer.member_id) if viewer.member_id else None


def viewer_active_role(cache: OrgCache, viewer: Identity) -> str:
    """Role used for permissions: 'agent' for agents/unknown, 'none' for inactive members."""
    if viewer.agent_id or viewer.role == "agent":
        return "agent"
    m = viewer_member(cache, viewer)
    if m is None:
        return viewer.role if viewer.member_id is None and viewer.role == "member" else "none"
    return m.role if m.active else "none"


def _route(rt: Any, **kw: Any) -> Any | None:
    approvals = getattr(rt, "approvals", None)
    if approvals is None or not hasattr(approvals, "route"):
        return None
    try:
        return approvals.route(**kw)
    except Exception:
        log.debug("approvals.route failed kw=%s", kw.get("action_type"), exc_info=True)
        return None


def org_op_level(
    rt: Any,
    viewer: Identity,
    action_type: str,
    *,
    resource: str | None = None,
    labels: dict[str, str] | None = None,
) -> Authz:
    """Required level for one org op: max(policy rule or default, hard floor)."""
    default, floor = ORG_OPS.get(action_type, ("owner", "admin"))
    route = _route(
        rt,
        kind="action",
        action_type=action_type,
        requester=viewer,
        resource=resource,
        labels={"category": "org", **(labels or {})},
    )
    rule_id = getattr(route, "rule_id", None) if route is not None else None
    if route is not None and rule_id is not None:
        level = str(route.required_role)
        two_person = bool(getattr(route, "two_person", False))
        ttl = getattr(route, "ttl_s", None)
    else:
        level, two_person, ttl = default, False, None
    if level != "deny":
        level = level_max(level, floor)
    return Authz(
        decision="approval",
        required=level,
        action_type=action_type,  # type: ignore[arg-type]
        op=action_type.removeprefix("org."),
        rule_id=rule_id,
        two_person=two_person,
        ttl_s=ttl,
        floor=floor,
    )  # type: ignore[arg-type]


def _decide(viewer_role: str, parts: list[Authz]) -> Authz:
    """Combine per-op levels: highest wins; deny -> forbidden; satisfied -> direct."""
    top = parts[0]
    for p in parts[1:]:
        if APPROVER_RANK.get(p.required, 0) > APPROVER_RANK.get(top.required, 0):
            top = p
    if any(p.required == "deny" for p in parts):
        denied = next(p for p in parts if p.required == "deny")
        return denied.model_copy(
            update={
                "decision": "forbidden",
                "reason": f"denied by rule {denied.rule_id or 'policy'}",
            }
        )
    two = any(p.two_person for p in parts)
    if satisfies(viewer_role, top.required) and not two:
        return top.model_copy(
            update={
                "decision": "direct",
                "two_person": two,
                "reason": f"authorized: {viewer_role} >= {top.required}",
            }
        )
    return top.model_copy(
        update={
            "decision": "approval",
            "two_person": two,
            "reason": f"needs {top.required} approval" + (" (two-person)" if two else ""),
        }
    )


def _forbidden(reason: str, required: str = "admin") -> Authz:
    return Authz(decision="forbidden", required=required, reason=reason)  # type: ignore[arg-type]


# ---------------------------------------------------------------- member / agent ops


def member_patch_ops(cache: OrgCache, target: Member, changes: dict[str, Any]) -> list[str]:
    ops: list[str] = []
    new_role = changes.get("role", target.role)
    if "role" in changes:
        if new_role == "owner":
            ops.append("org.role.promote_owner")
        elif target.role == "owner":
            ops.append("org.role.demote_owner")
        elif new_role == "admin":
            ops.append("org.role.promote_admin")
        else:
            ops.append("org.role.demote_admin")
    if "active" in changes:
        privileged = target.role in ("owner", "admin") or new_role in ("owner", "admin")
        ops.append("org.member.deactivate_privileged" if privileged else "org.member.deactivate")
    if any(k in changes for k in ("team_id", "title", "name", "email")):
        ops.append("org.member.update")
    return ops


def effective_changes(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in patch.items() if current.get(k) != v}


def authorize_member_patch(
    rt: Any, cache: OrgCache, viewer: Identity, target: Member, patch: dict[str, Any]
) -> tuple[Authz, dict[str, Any]]:
    """-> (Authz, effective changes). Invariants first, then policy levels."""
    role = viewer_active_role(cache, viewer)
    if role not in ("owner", "admin"):
        return _forbidden("managing members requires admin or owner"), {}
    if "role" in patch and patch["role"] not in MEMBER_ROLES:
        return Authz(decision="invalid", reason=f"unknown role {patch['role']!r}"), {}
    if "team_id" in patch and patch["team_id"] is not None and patch["team_id"] not in cache.teams:
        return Authz(decision="invalid", reason=f"unknown team {patch['team_id']!r}"), {}
    changes = effective_changes(target.model_dump(), patch)
    if not changes:
        return Authz(decision="noop", reason="nothing to change"), {}
    losing_owner = (
        target.role == "owner"
        and target.active
        and (("role" in changes and changes["role"] != "owner") or changes.get("active") is False)
    )
    if losing_owner and cache.active_owner_ids() == [target.id]:
        return Authz(
            decision="conflict", required="owner", reason=f"{target.name} is the last active owner"
        ), changes
    if viewer.member_id == target.id and ("role" in changes or changes.get("active") is False):
        return _forbidden("you cannot change your own role or deactivate yourself"), changes
    labels = {"to_role": str(changes.get("role", target.role))}
    parts = [
        org_op_level(rt, viewer, op, resource=f"member:{target.id}", labels=labels)
        for op in member_patch_ops(cache, target, changes)
    ]
    return _decide(role, parts), changes


def create_member_op(role: str) -> str:
    return {"owner": "org.member.create_owner", "admin": "org.member.create_admin"}.get(
        role, "org.member.create"
    )


def authorize_member_create(
    rt: Any, cache: OrgCache, viewer: Identity, body: dict[str, Any]
) -> Authz:
    role = viewer_active_role(cache, viewer)
    if role not in ("owner", "admin"):
        return _forbidden("adding members requires admin or owner")
    new_role = body.get("role", "member")
    if new_role not in MEMBER_ROLES:
        return Authz(decision="invalid", reason=f"unknown role {new_role!r}")
    if body.get("team_id") and body["team_id"] not in cache.teams:
        return Authz(decision="invalid", reason=f"unknown team {body['team_id']!r}")
    op = create_member_op(new_role)
    return _decide(role, [org_op_level(rt, viewer, op, labels={"to_role": new_role})])


def agent_patch_ops(agent: Any, changes: dict[str, Any]) -> list[str]:
    ops: list[str] = []
    if "max_destination" in changes:
        old, new = agent.max_destination, changes["max_destination"]
        old_rank = DEST_RANK.get(old, 99) if old else 99
        new_rank = DEST_RANK.get(new, 99) if new else 99
        if new_rank > old_rank:
            ops.append("org.agent.widen_destination")
    if any(k != "max_destination" for k in changes) or not ops:
        ops.append("org.agent.update")
    return ops


def authorize_agent_patch(
    rt: Any, cache: OrgCache, viewer: Identity, agent: Any, patch: dict[str, Any]
) -> tuple[Authz, dict[str, Any]]:
    role = viewer_active_role(cache, viewer)
    if role not in ("owner", "admin"):
        return _forbidden("managing agents requires admin or owner"), {}
    if "max_destination" in patch and patch["max_destination"] not in (None, *DEST_RANK):
        return Authz(
            decision="invalid", reason=f"unknown destination {patch['max_destination']!r}"
        ), {}
    if patch.get("owner_member_id") and patch["owner_member_id"] not in cache.members:
        return Authz(decision="invalid", reason=f"unknown member {patch['owner_member_id']!r}"), {}
    changes = effective_changes(agent.model_dump(), patch)
    if not changes:
        return Authz(decision="noop", reason="nothing to change"), {}
    parts = [
        org_op_level(rt, viewer, op, resource=f"agent:{agent.id}")
        for op in agent_patch_ops(agent, changes)
    ]
    return _decide(role, parts), changes


def authorize_simple(
    rt: Any, cache: OrgCache, viewer: Identity, action_type: str, resource: str | None = None
) -> Authz:
    """Key issue/revoke, agent create: admin+ only, routed level (no approval workflow)."""
    role = viewer_active_role(cache, viewer)
    if role not in ("owner", "admin"):
        return _forbidden("requires admin or owner")
    return _decide(role, [org_op_level(rt, viewer, action_type, resource=resource)])


# ---------------------------------------------------------------- config-change levels


def _config_level(rt: Any, role: str, key: str, change: PolicyChange) -> str:
    requester = Identity(org_id="acme-capital", member_id=None, role=role)  # type: ignore[arg-type]
    route = _route(
        rt, kind="config_change", action_type=change.kind, requester=requester, changes=[change]
    )
    if route is None:
        return _STATIC_CONFIG.get(key, "owner")
    return str(route.required_role)


def _representative_changes() -> dict[str, list[tuple[str, PolicyChange]]]:
    return {
        "policy.edit": [
            (
                "control.threshold.tighten",
                PolicyChange(
                    kind="control.threshold.tighten",
                    path="controls[id=INJ-02].threshold",
                    before=0.9,
                    after=0.8,
                    control_id="INJ-02",
                    summary="tighten INJ-02 0.90 -> 0.80",
                ),
            ),
            (
                "model.allow",
                PolicyChange(
                    kind="model.allow",
                    path="models.allowed",
                    before=None,
                    after="gpt-4.1",
                    loosening=True,
                    summary="allow gpt-4.1",
                ),
            ),
            (
                "control.disable",
                PolicyChange(
                    kind="control.disable",
                    path="controls[id=DLP-02].enabled",
                    before=True,
                    after=False,
                    control_id="DLP-02",
                    loosening=True,
                    summary="disable DLP-02",
                ),
            ),
        ],
        "budgets.raise": [
            (
                "budget.raise.small",
                PolicyChange(
                    kind="budget.raise",
                    path="budgets.limits[scope=team:trading,window=day].usd",
                    before=60,
                    after=75,
                    scope="team:trading",
                    dimension="usd",
                    increase_pct=25.0,
                    loosening=True,
                    summary="team:trading daily usd 60 -> 75 (+25%)",
                ),
            ),
            (
                "budget.raise.large",
                PolicyChange(
                    kind="budget.raise",
                    path="budgets.limits[scope=team:trading,window=day].usd",
                    before=60,
                    after=150,
                    scope="team:trading",
                    dimension="usd",
                    increase_pct=150.0,
                    loosening=True,
                    summary="team:trading daily usd 60 -> 150 (+150%)",
                ),
            ),
        ],
        "killswitch.engage": [
            (
                "killswitch.on",
                PolicyChange(
                    kind="killswitch.on",
                    path="budgets.kill_switch.agents",
                    before=[],
                    after=["chaos-agent@platform"],
                    summary="kill chaos-agent@platform",
                ),
            )
        ],
        "killswitch.release": [
            (
                "killswitch.off",
                PolicyChange(
                    kind="killswitch.off",
                    path="budgets.kill_switch.agents",
                    before=["chaos-agent@platform"],
                    after=[],
                    loosening=True,
                    summary="release chaos-agent@platform",
                ),
            )
        ],
    }


def _cell_from_levels(role: str, levels: list[str]) -> dict[str, Any]:
    if role == "agent":
        return {"value": "no", "approver": None, "note": "agents never change config"}
    usable = [lv for lv in levels if lv != "deny"]
    if not usable:
        return {"value": "no", "approver": "deny", "note": "denied by policy"}
    ok = [lv for lv in usable if satisfies(role, lv)]
    top = max(usable, key=lambda lv: APPROVER_RANK.get(lv, 0))
    if len(ok) == len(usable):
        return {"value": "yes", "approver": None, "note": None}
    if ok:
        return {
            "value": "partial",
            "approver": top,
            "note": f"larger / loosening changes need {top} approval",
        }
    return {"value": "approval", "approver": top, "note": f"routed to {top} for approval"}


# ---------------------------------------------------------------- whoami + matrix


def highest_config_level(snap: PolicySnapshot | None) -> str:
    if snap is None:
        return "owner"
    approvals = snap.doc.approvals
    levels = [r.approver for r in approvals.config_rules if r.approver != "deny"]
    levels.append(approvals.defaults.default_config_approver)
    best = "auto"
    for lv in levels:
        if lv != "deny":
            best = level_max(best, lv)
    return best


def whoami_permissions(
    rt: Any, cache: OrgCache, viewer: Identity, snap: PolicySnapshot | None
) -> dict[str, Any]:
    """Frozen TS `Permissions` shape."""
    role = viewer_active_role(cache, viewer)
    if role in ("agent", "none"):
        return {
            "can_apply_policy": "no",
            "can_manage_members": False,
            "can_killswitch": False,
            "can_export_audit": False,
            "approver_levels": [],
        }
    top = highest_config_level(snap)
    kill = _config_level(
        rt, role, "killswitch.on", _representative_changes()["killswitch.engage"][0][1]
    )
    levels = ["self"]
    if satisfies(role, "admin"):
        levels.append("admin")
    if satisfies(role, "owner"):
        levels.append("owner")
    return {
        "can_apply_policy": "yes" if satisfies(role, top) else "approval",
        "can_manage_members": satisfies(role, "admin"),
        "can_killswitch": satisfies(role, kill),
        "can_export_audit": satisfies(role, "admin"),
        "approver_levels": levels,
    }


CAPABILITY_ROWS: list[tuple[str, str, str]] = [
    ("org.view", "View dashboards, decisions & audit", "org"),
    ("approvals.self", "Approve own requests & sponsored agents' self-level items", "approvals"),
    (
        "approvals.admin",
        "Approve admin-level items (data access, spend <= $200, deploys)",
        "approvals",
    ),
    (
        "approvals.owner",
        "Approve owner-level items (spend > $200, prod writes, disables)",
        "approvals",
    ),
    ("policy.edit", "Edit policy catalog (hot reload)", "policy"),
    ("budgets.raise", "Raise budgets", "budgets"),
    ("killswitch.engage", "Engage kill switch", "security"),
    ("killswitch.release", "Release kill switch", "security"),
    ("audit.export", "Export audit logs", "security"),
    ("members.manage", "Manage members & roles", "org"),
    ("agents.manage", "Manage agents (models, tools, status)", "agents"),
    ("agents.keys", "Issue / revoke agent API keys", "agents"),
    ("feed.refresh", "Refresh threat feed", "security"),
    ("mcp.repin", "Re-pin / quarantine MCP tools", "security"),
]


def _yes(v: bool, note: str | None = None) -> dict[str, Any]:
    return {"value": "yes" if v else "no", "approver": None, "note": note if v else None}


def capability_cells(
    rt: Any, role: str, config_levels: dict[str, list[str]], org_levels: dict[str, str]
) -> dict[str, dict[str, Any]]:
    """Cells of every capability row for one role ('owner'|'admin'|'member'|'agent'|'none')."""
    human = role in MEMBER_ROLES
    admin = satisfies(role, "admin")
    cells: dict[str, dict[str, Any]] = {
        "org.view": _yes(human),
        "approvals.self": _yes(
            human, "own requests & sponsored agents" if role == "member" else None
        ),
        "approvals.admin": _yes(admin),
        "approvals.owner": _yes(satisfies(role, "owner")),
        "audit.export": _yes(admin),
        "feed.refresh": _yes(admin),
        "mcp.repin": _yes(admin),
    }
    for cap, levels in config_levels.items():
        cells[cap] = (
            _cell_from_levels(role, levels)
            if human
            else {"value": "no", "approver": None, "note": None}
        )
    if not admin:
        cells["members.manage"] = {"value": "no", "approver": None, "note": None}
    else:
        privileged = [
            org_levels[k]
            for k in ("org.role.promote_admin", "org.role.promote_owner", "org.member.create_admin")
        ]
        if all(satisfies(role, lv) for lv in privileged):
            cells["members.manage"] = {"value": "yes", "approver": None, "note": None}
        else:
            top = max(privileged, key=lambda lv: APPROVER_RANK.get(lv, 0))
            cells["members.manage"] = {
                "value": "partial",
                "approver": top,
                "note": f"members only; admin/owner grants need {top}",
            }
    for cap, op in (("agents.manage", "org.agent.update"), ("agents.keys", "org.agent.key")):
        if not admin:
            cells[cap] = {"value": "no", "approver": None, "note": None}
        elif satisfies(role, org_levels[op]):
            cells[cap] = {"value": "yes", "approver": None, "note": None}
        else:
            cells[cap] = {"value": "approval", "approver": org_levels[op], "note": None}
    return cells


def _levels(rt: Any, role: str) -> tuple[dict[str, list[str]], dict[str, str]]:
    config_role = role if role in MEMBER_ROLES else "member"
    config_levels = {
        cap: [_config_level(rt, config_role, key, ch) for key, ch in changes]
        for cap, changes in _representative_changes().items()
    }
    requester = Identity(org_id="acme-capital", member_id=None, role=config_role)  # type: ignore[arg-type]
    org_levels = {op: org_op_level(rt, requester, op).required for op in ORG_OPS}
    return config_levels, org_levels


def capabilities_for(rt: Any, cache: OrgCache, viewer: Identity) -> dict[str, str]:
    """`WhoAmI.capabilities` (additive): capability id -> yes|approval|partial|no."""
    role = viewer_active_role(cache, viewer)
    config_levels, org_levels = _levels(rt, role)
    cells = capability_cells(rt, role, config_levels, org_levels)
    return {cap: cells[cap]["value"] for cap, _, _ in CAPABILITY_ROWS}


def matrix(rt: Any, snap: PolicySnapshot | None) -> dict[str, Any]:
    """`OrgPermissionsResponse` (plan 08 section 4.3), live from the policy snapshot."""
    per_role = {}
    for role in ROLES_ALL:
        config_levels, org_levels = _levels(rt, role)
        per_role[role] = capability_cells(rt, role, config_levels, org_levels)
    caps = [
        {
            "id": cap,
            "label": label,
            "group": group,
            "cells": {role: per_role[role][cap] for role in ROLES_ALL},
        }
        for cap, label, group in CAPABILITY_ROWS
    ]
    approval_levels: list[dict[str, Any]] = []
    if snap is not None:
        for set_name, rules in (
            ("rules", snap.doc.approvals.rules),
            ("config_rules", snap.doc.approvals.config_rules),
        ):
            for r in rules:
                approval_levels.append(
                    {
                        "rule_id": r.id,
                        "set": set_name,
                        "actions": list(r.when.action or []),
                        "kinds": list(r.when.kind or []),
                        "approver": r.approver,
                        "two_person": r.two_person,
                        "roles": roles_satisfying(r.approver),
                        "description": r.description,
                    }
                )
    return {
        "policy_version": snap.version if snap is not None else 0,
        "roles": ROLES_ALL,
        "capabilities": caps,
        "approval_levels": approval_levels,
    }


__all__ = [
    "CAPABILITY_ROWS",
    "DEST_RANK",
    "ORG_OPS",
    "authorize_agent_patch",
    "authorize_member_create",
    "authorize_member_patch",
    "authorize_simple",
    "capabilities_for",
    "level_max",
    "matrix",
    "member_patch_ops",
    "org_op_level",
    "satisfies",
    "viewer_active_role",
    "whoami_permissions",
]
