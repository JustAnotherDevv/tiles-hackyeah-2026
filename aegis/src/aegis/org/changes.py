"""Governed org changes (plan 08 section 2.7).

`request_*` authorize a member/agent change: direct when the viewer's role satisfies the
routed level, otherwise an `org_changes` row + `rt.approvals.create_manual(...)` (403
`approval_required`). Approved changes are applied by `org_executor` (when registered),
by the `approval.updated` bus listener, or lazily by `reconcile()` on reads - idempotently.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aegis.core.types import (
    APPROVER_RANK,
    ApprovalDraft,
    ApprovalRequest,
    Identity,
    Member,
    new_id,
    utcnow,
)
from aegis.org import permissions as perms
from aegis.org import store
from aegis.org.models import Authz, OrgChange

if TYPE_CHECKING:
    from aegis.org.service import OrgServiceImpl

log = logging.getLogger(__name__)

TERMINAL = {"denied": "denied", "expired": "expired", "cancelled": "cancelled"}


@dataclass
class ChangeResult:
    """Outcome of a change request, converted to HTTP by the route module."""

    outcome: str  # applied | pending | forbidden | conflict | invalid | not_found | noop | denied
    status: int
    message: str = ""
    entity: Any = None  # Member | Agent (applied / noop)
    approval: ApprovalRequest | None = None
    change: OrgChange | None = None
    authz: Authz | None = None
    fields: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- helpers


def _public(obj: Any) -> dict[str, Any]:
    from aegis.org.service import public_dict

    return public_dict(obj)


def _role_word(role: str) -> str:
    return {"owner": "owner", "admin": "admin", "member": "member"}.get(role, role)


def describe(op: str, target_name: str, changes: dict[str, Any], before: dict[str, Any]) -> str:
    """Human title: 'Promote Piotr Zieliński to admin'."""
    if op.startswith("org.role."):
        to = changes.get("role")
        if op.endswith(("promote_admin", "promote_owner")):
            return f"Promote {target_name} to {_role_word(str(to))}"
        return f"Change {target_name}'s role to {_role_word(str(to))}"
    if op.startswith("org.member.create"):
        return f"Add {target_name} as {_role_word(str(changes.get('role', 'member')))}"
    if op.startswith("org.member.deactivate"):
        return (
            f"Deactivate {target_name}"
            if changes.get("active") is False
            else f"Reactivate {target_name}"
        )
    if op == "org.agent.widen_destination":
        return (
            f"Widen {target_name} destination {before.get('max_destination') or 'any'} -> "
            f"{changes.get('max_destination') or 'any'}"
        )
    if op.startswith("org.agent"):
        return f"Update agent {target_name} ({', '.join(sorted(changes))})"
    return f"Update {target_name} ({', '.join(sorted(changes))})"


def _change_words(changes: dict[str, Any], before: dict[str, Any]) -> str:
    parts = []
    for k, v in changes.items():
        if k == "email":
            continue
        parts.append(f"{k}: {before.get(k)} -> {v}")
    return ", ".join(parts)


async def _create_manual(
    svc: OrgServiceImpl, viewer: Identity, draft: ApprovalDraft
) -> ApprovalRequest | None:
    approvals = getattr(svc.rt, "approvals", None)
    if approvals is None or not hasattr(approvals, "create_manual"):
        return None
    try:
        return await approvals.create_manual(viewer, draft)
    except Exception:
        log.warning(
            "approvals.create_manual failed action_type=%s", draft.action_type, exc_info=True
        )
        return None


async def _get_approval(svc: OrgServiceImpl, approval_id: str) -> ApprovalRequest | None:
    approvals = getattr(svc.rt, "approvals", None)
    if approvals is None or not hasattr(approvals, "get"):
        return None
    try:
        return await approvals.get(approval_id)
    except Exception:
        log.warning("approvals.get failed id=%s", approval_id, exc_info=True)
        return None


def _ok(svc: OrgServiceImpl, entity: Any, status: int = 200, **kw: Any) -> ChangeResult:
    return ChangeResult(outcome="applied", status=status, entity=entity, **kw)


def _from_authz(authz: Authz) -> ChangeResult:
    if authz.decision == "forbidden":
        return ChangeResult(
            outcome="forbidden",
            status=403,
            message=authz.reason,
            authz=authz,
            fields={"required_role": authz.required},
        )
    if authz.decision == "conflict":
        return ChangeResult(outcome="conflict", status=409, message=authz.reason, authz=authz)
    return ChangeResult(outcome="invalid", status=400, message=authz.reason, authz=authz)


# ---------------------------------------------------------------- apply


async def apply_change(
    svc: OrgServiceImpl,
    change: OrgChange,
    *,
    actor: Identity,
    via: str,
    approval_id: str | None = None,
) -> Any:
    """Write + cache refresh + audit `org.changed` + bus `org.updated`. Returns the entity."""
    cache = svc.cache
    now = utcnow()
    patch = dict(change.patch)
    if change.target_type == "member":
        if change.op.startswith("org.member.create"):
            mid = change.target_id or svc.new_member_id(patch.get("name", "member"))
            if mid in cache.members:
                mid = svc.new_member_id(patch.get("name", "member"))
            team = patch.get("team_id")
            entity: Any = Member(
                id=mid,
                org_id=cache.org.id,
                team_id=team,
                name=patch.get("name") or mid,
                email=patch.get("email"),
                role=patch.get("role", "member"),
                title=patch.get("title"),
                active=True,
                created_at=now,
                meta={"teams": [team] if team else [], "created_by": actor.member_id},
            )
            change.target_id = mid
        else:
            current = cache.members[change.target_id or ""]
            update = dict(patch)
            meta = dict(current.meta)
            if update.get("team_id"):
                teams = [t for t in (meta.get("teams") or []) if t]
                new = update["team_id"]
                if new in teams:
                    teams.remove(new)
                elif teams:
                    teams.pop(0)
                meta["teams"] = [new, *teams]
            update["meta"] = meta
            entity = current.model_copy(update=update, deep=True)
        before = change.before or {}
        result = await svc.write_member(entity)
        svc.publish(member=result)
    else:
        current_agent = cache.agents[change.target_id or ""]
        before = change.before or {}
        result = await svc.write_agent(current_agent.model_copy(update=patch, deep=True))
        svc.publish(agent=result)
    await svc.audit(
        change.op.removeprefix("org."),
        actor=actor,
        target=f"{change.target_type}:{change.target_id}",
        reason=describe(change.op, getattr(result, "name", change.target_id or ""), patch, before)
        + (f" (approved via {approval_id})" if approval_id else ""),
        data={
            "action_type": change.action_type,
            "target": change.target_id,
            "before": before,
            "after": _public(result),
            "via": via,
            "outcome": "applied",
            "approval_id": approval_id,
            "org_change_id": change.id,
            "requested_by": change.requested_by.model_dump(mode="json"),
        },
    )
    return result


async def _set_change(svc: OrgServiceImpl, change: OrgChange) -> None:
    def _w(conn: sqlite3.Connection) -> None:
        store.update_change(conn, change)

    await svc.db(_w)
    if change.status == "pending":
        svc.pending[change.id] = change
    else:
        svc.pending.pop(change.id, None)


# ---------------------------------------------------------------- request flows


async def _governed(
    svc: OrgServiceImpl,
    viewer: Identity,
    authz: Authz,
    *,
    target_type: str,
    target_id: str | None,
    target_name: str,
    changes: dict[str, Any],
    before: dict[str, Any],
    resource: str,
    current: Any,
) -> ChangeResult:
    """Common tail: direct apply, or create/reuse the approval request."""
    action_type = authz.action_type or "org.member.update"
    change = OrgChange(
        id=new_id("och"),
        op=action_type,
        action_type=action_type,
        target_type=target_type,  # type: ignore[arg-type]
        target_id=target_id,
        patch=changes,
        before=before,
        requested_by=viewer,
        required_role=authz.required,
        status="pending",
    )
    title = describe(action_type, target_name, changes, before)
    if authz.decision == "direct":
        change.status = "applied"
        change.decided_at = utcnow()
        entity = await apply_change(svc, change, actor=viewer, via="direct")
        change.result = {"applied": True, "authz": authz.reason}
        await svc.db(store.insert_change, change)
        return _ok(
            svc,
            entity,
            status=201 if action_type.startswith("org.member.create") else 200,
            change=change,
            authz=authz,
        )

    # approval: dedupe a pending request for the same (target, op)
    for pend in list(svc.pending.values()):
        if (
            pend.target_id == target_id
            and pend.action_type == action_type
            and pend.patch == changes
            and pend.approval_id
        ):
            apr = await _get_approval(svc, pend.approval_id)
            if apr is not None and apr.status == "pending":
                return _pending_result(pend, apr, title)
    await svc.db(store.insert_change, change)
    svc.pending[change.id] = change
    viewer_name = viewer.display_name or viewer.member_id or "someone"
    summary = (
        f"Requested by {viewer_name} ({viewer.role}): {_change_words(changes, before)}. "
        f"Needs {authz.required}."
    )
    payload_patch = {k: (v if k != "email" else _mask(v)) for k, v in changes.items()}
    draft = ApprovalDraft(
        kind="action",
        action_type=action_type,
        title=title,
        summary=summary,
        resource=resource,
        labels={
            "category": "org",
            "op": action_type.removeprefix("org."),
            "to_role": str(changes.get("role", getattr(current, "role", "") or "")),
        },
        payload={  # CONTRACTS A-24 org shape (emails masked)
            "org_change_id": change.id,
            "op": action_type.removeprefix("org."),
            "action_type": action_type,
            "target": {"type": target_type, "id": target_id, "name": target_name},
            "patch": payload_patch,
            "before": _mask_dict(before),
            "required_role": authz.required,
            "rule_id": authz.rule_id,
        },
    )
    apr = await _create_manual(svc, viewer, draft)
    if apr is None or apr.status == "denied":
        change.status = "denied"
        change.decided_at = utcnow()
        change.result = {
            "applied": False,
            "reason": "approvals unavailable" if apr is None else "denied at creation",
        }
        if apr is not None:
            change.approval_id = apr.id
        await _set_change(svc, change)
        await svc.audit(
            action_type.removeprefix("org."),
            actor=viewer,
            target=resource,
            reason=f"{title}: approval denied",
            data={
                "outcome": "denied",
                "org_change_id": change.id,
                "approval_id": change.approval_id,
                "rule_id": authz.rule_id,
            },
        )
        msg = (
            "approvals unavailable - ask an owner"
            if apr is None
            else f"{title} was denied by policy ({apr.rule_id or 'rule'})"
        )
        return ChangeResult(
            outcome="forbidden",
            status=403,
            message=msg,
            change=change,
            authz=authz,
            fields={"required_role": authz.required, "approval_id": change.approval_id},
        )
    async with svc.exec_lock:
        # An auto-approved request may already have been executed inside create_manual.
        stored = await svc.db(store.get_change, change.id)
        if stored is not None and stored.status != "pending":
            change = stored
        change.approval_id = apr.id
        change.expires_at = apr.expires_at
        if APPROVER_RANK.get(str(apr.required_role), 0) > APPROVER_RANK.get(
            change.required_role, 0
        ):
            change.required_role = apr.required_role
        await _set_change(svc, change)
    if apr.status == "approved":  # auto-approved
        await execute_approved(svc, apr)  # no-op when the executor already ran
        final = await svc.db(store.get_change, change.id)
        if final is not None and final.status == "applied":
            entity = (
                svc.cache.members.get(final.target_id or "")
                if target_type == "member"
                else svc.cache.agents.get(final.target_id or "")
            )
            return _ok(
                svc, entity.model_copy(deep=True) if entity else None, change=final, approval=apr
            )
        if final is not None and final.status != "pending":
            reason = (final.result or {}).get("reason") or final.status
            return ChangeResult(
                outcome="forbidden",
                status=403,
                message=f"{title}: approved but not applied ({reason})",
                change=final,
                authz=authz,
                fields={"required_role": change.required_role, "approval_id": apr.id},
            )
    await svc.audit(
        action_type.removeprefix("org."),
        actor=viewer,
        target=resource,
        reason=f"{title}: sent for {change.required_role} approval ({apr.id})",
        data={
            "outcome": "pending_approval",
            "org_change_id": change.id,
            "approval_id": apr.id,
            "rule_id": authz.rule_id,
            "before": _mask_dict(before),
            "patch": payload_patch,
            "via": "approval",
        },
    )
    return _pending_result(change, apr, title)


def _pending_result(change: OrgChange, apr: ApprovalRequest, title: str) -> ChangeResult:
    role = change.required_role
    word = title[0].lower() + title[1:] if title else "this change"
    gerund = word.replace("promote ", "promoting ", 1).replace("add ", "adding ", 1)
    gerund = gerund.replace("deactivate ", "deactivating ", 1).replace("change ", "changing ", 1)
    message = f"{gerund[0].upper() + gerund[1:]} needs {role} approval"
    return ChangeResult(
        outcome="pending",
        status=403,
        message=message,
        change=change,
        approval=apr,
        fields={"approval_id": apr.id, "required_role": role, "expires_at": apr.expires_at},
    )


def _mask(v: Any) -> Any:
    from aegis.org.service import mask_email

    return mask_email(v) if isinstance(v, str) else v


def _mask_dict(d: dict[str, Any]) -> dict[str, Any]:
    return {k: (_mask(v) if k == "email" else v) for k, v in (d or {}).items()}


async def request_member_patch(
    svc: OrgServiceImpl, viewer: Identity, member_id: str, patch: dict[str, Any]
) -> ChangeResult:
    target = svc.cache.members.get(member_id)
    if target is None:
        return ChangeResult(
            outcome="not_found", status=404, message=f"member {member_id} not found"
        )
    authz, changes = perms.authorize_member_patch(svc.rt, svc.cache, viewer, target, patch)
    if authz.decision == "noop":
        return ChangeResult(outcome="noop", status=200, entity=target.model_copy(deep=True))
    if authz.decision not in ("direct", "approval"):
        await _audit_refused(svc, viewer, authz, f"member:{member_id}", changes)
        return _from_authz(authz)
    before = {k: getattr(target, k) for k in changes}
    return await _governed(
        svc,
        viewer,
        authz,
        target_type="member",
        target_id=member_id,
        target_name=target.name,
        changes=changes,
        before=before,
        resource=f"member:{member_id}",
        current=target,
    )


async def request_member_create(
    svc: OrgServiceImpl, viewer: Identity, body: dict[str, Any]
) -> ChangeResult:
    authz = perms.authorize_member_create(svc.rt, svc.cache, viewer, body)
    if authz.decision not in ("direct", "approval"):
        await _audit_refused(svc, viewer, authz, "member:new", body)
        return _from_authz(authz)
    new_id_ = svc.new_member_id(body.get("name", "member"))
    changes = {k: body[k] for k in ("name", "email", "role", "team_id", "title") if k in body}
    changes.setdefault("role", "member")
    return await _governed(
        svc,
        viewer,
        authz,
        target_type="member",
        target_id=new_id_,
        target_name=body.get("name") or new_id_,
        changes=changes,
        before={},
        resource=f"member:{new_id_}",
        current=None,
    )


async def request_agent_patch(
    svc: OrgServiceImpl, viewer: Identity, agent_id: str, patch: dict[str, Any]
) -> ChangeResult:
    agent = svc.cache.agents.get(agent_id)
    if agent is None:
        return ChangeResult(outcome="not_found", status=404, message=f"agent {agent_id} not found")
    authz, changes = perms.authorize_agent_patch(svc.rt, svc.cache, viewer, agent, patch)
    if authz.decision == "noop":
        return ChangeResult(outcome="noop", status=200, entity=agent.model_copy(deep=True))
    if authz.decision not in ("direct", "approval"):
        await _audit_refused(svc, viewer, authz, f"agent:{agent_id}", changes)
        return _from_authz(authz)
    before = {k: getattr(agent, k) for k in changes}
    return await _governed(
        svc,
        viewer,
        authz,
        target_type="agent",
        target_id=agent_id,
        target_name=agent.id,
        changes=changes,
        before=before,
        resource=f"agent:{agent_id}",
        current=agent,
    )


async def _audit_refused(
    svc: OrgServiceImpl, viewer: Identity, authz: Authz, target: str, changes: dict[str, Any]
) -> None:
    if authz.decision not in ("forbidden", "conflict"):
        return
    await svc.audit(
        (authz.action_type or "org.change").removeprefix("org."),
        actor=viewer,
        target=target,
        reason=f"refused: {authz.reason}",
        data={
            "outcome": authz.decision,
            "patch": _mask_dict(changes),
            "rule_id": authz.rule_id,
            "required_role": authz.required,
        },
    )


# ---------------------------------------------------------------- execution on approval


def _find_change(
    svc: OrgServiceImpl, approval_id: str, payload: dict[str, Any] | None = None
) -> OrgChange | None:
    for c in svc.pending.values():
        if c.approval_id == approval_id:
            return c
    cid = (payload or {}).get("org_change_id")
    if cid and cid in svc.pending:
        return svc.pending[cid]
    return None


async def execute_approved(svc: OrgServiceImpl, req: ApprovalRequest) -> dict[str, Any]:
    """Apply the pending change of an approved `org.*` request (idempotent, never raises)."""
    try:
        async with svc.exec_lock:
            change = _find_change(svc, req.id, req.payload)
            if change is None:
                return {
                    "status": "noop",
                    "applied": False,
                    "message": "no pending org change for this approval",
                }
            reason = _approval_problem(svc, change, req)
            if reason:
                change.status = "failed"
                change.decided_at = utcnow()
                change.result = {"applied": False, "reason": reason}
                await _set_change(svc, change)
                await svc.audit(
                    change.op.removeprefix("org."),
                    actor=_approver(svc, req),
                    target=f"{change.target_type}:{change.target_id}",
                    reason=f"approved change not applied: {reason}",
                    data={
                        "outcome": "failed",
                        "org_change_id": change.id,
                        "approval_id": req.id,
                        "via": "approval",
                    },
                )
                return {
                    "status": "rejected",
                    "applied": False,
                    "reason": reason,
                    "message": reason,
                    "org_change_id": change.id,
                }
            entity = await apply_change(
                svc, change, actor=_approver(svc, req), via="approval", approval_id=req.id
            )
            change.status = "applied"
            change.decided_at = utcnow()
            change.result = {"applied": True, "approved_by": list(req.decided_by)}
            await _set_change(svc, change)
            return {
                "status": "applied",
                "applied": True,
                "message": f"applied {change.op} to {change.target_type}:{change.target_id}",
                "org_change_id": change.id,
                "target": f"{change.target_type}:{change.target_id}",
                "after": _public(entity),
            }
    except Exception as exc:  # never raise into approvals-engine
        log.exception("org change execution failed approval=%s", req.id)
        return {
            "status": "error",
            "applied": False,
            "reason": f"error: {type(exc).__name__}",
            "message": f"org change failed: {type(exc).__name__}",
        }


def _approver(svc: OrgServiceImpl, req: ApprovalRequest) -> Identity:
    mid = req.decided_by[-1] if req.decided_by else None
    votes = [v for v in req.votes if v.decision == "approve"]
    if mid is None and votes:
        mid = votes[-1].member_id
    m = svc.cache.members.get(mid or "")
    if m is None:
        return Identity(org_id=svc.cache.org.id, member_id=mid, role="member")
    return Identity(
        org_id=m.org_id, team_id=m.team_id, member_id=m.id, role=m.role, display_name=m.name
    )


def _approval_problem(svc: OrgServiceImpl, change: OrgChange, req: ApprovalRequest) -> str | None:
    """Re-check hard floors against the actual approvers + invariants at apply time."""
    approvers = list(
        dict.fromkeys(
            list(req.decided_by) + [v.member_id for v in req.votes if v.decision == "approve"]
        )
    )
    if not approvers:
        if req.required_role == "auto" and APPROVER_RANK.get(change.required_role, 0) <= 0:
            return None
        return "no human approver recorded"
    if change.target_type == "member" and change.target_id in approvers:
        return "target cannot approve own promotion"
    _, floor = perms.ORG_OPS.get(change.action_type, ("owner", "admin"))
    need = perms.level_max(floor, change.required_role)
    roles = [
        svc.cache.members[a].role
        for a in approvers
        if a in svc.cache.members and svc.cache.members[a].active
    ]
    if not any(perms.satisfies(r, need) for r in roles):
        return f"approver role does not satisfy {need}"
    requester = change.requested_by.member_id
    if requester and approvers == [requester]:
        return "requester cannot approve own request"
    if change.target_type == "member" and not change.op.startswith("org.member.create"):
        target = svc.cache.members.get(change.target_id or "")
        if target is None:
            return "target member no longer exists"
        losing = (
            target.role == "owner"
            and target.active
            and (
                change.patch.get("role", "owner") != "owner" or change.patch.get("active") is False
            )
        )
        if losing and svc.cache.active_owner_ids() == [target.id]:
            return f"{target.name} is the last active owner"
    if change.target_type == "agent" and change.target_id not in svc.cache.agents:
        return "target agent no longer exists"
    return None


async def org_executor(req: ApprovalRequest) -> dict[str, Any] | None:
    """Approval executor for kind `action`: handles only `org.*`, None otherwise."""
    if not str(req.action_type or "").startswith("org."):
        return None
    from aegis.org.service import OrgServiceImpl

    svc = _CURRENT.get("svc")
    if not isinstance(svc, OrgServiceImpl):
        return {"status": "error", "applied": False, "message": "org service unavailable"}
    return await execute_approved(svc, req)


_CURRENT: dict[str, Any] = {}


def bind_service(svc: Any) -> None:
    _CURRENT["svc"] = svc


async def reconcile(svc: OrgServiceImpl, approval_id: str | None = None) -> int:
    """Settle pending changes from their approvals' state. Returns how many changed."""
    if not svc.pending:
        return 0
    done = 0
    for change in list(svc.pending.values()):
        if not change.approval_id or (approval_id and change.approval_id != approval_id):
            continue
        apr = await _get_approval(svc, change.approval_id)
        if apr is None:
            continue
        if apr.status == "approved":
            res = await execute_approved(svc, apr)
            done += 1 if res.get("org_change_id") else 0
        elif apr.status in TERMINAL:
            async with svc.exec_lock:
                if change.id not in svc.pending:
                    continue
                change.status = TERMINAL[apr.status]  # type: ignore[assignment]
                change.decided_at = apr.decided_at or utcnow()
                change.result = {"applied": False, "reason": f"approval {apr.status}"}
                await _set_change(svc, change)
            await svc.audit(
                change.op.removeprefix("org."),
                actor=_approver(svc, apr),
                target=f"{change.target_type}:{change.target_id}",
                reason=f"{describe(change.op, change.target_id or '', change.patch, change.before)}"
                f": approval {apr.status}",
                data={
                    "outcome": apr.status,
                    "org_change_id": change.id,
                    "approval_id": apr.id,
                    "via": "approval",
                },
            )
            done += 1
    return done


def pending_for(svc: OrgServiceImpl, target_id: str) -> list[dict[str, Any]]:
    """`Member.meta.pending_changes` entries for one member / agent."""
    out = []
    for c in svc.pending.values():
        if c.target_id != target_id:
            continue
        to = c.patch.get("role") or c.patch.get("max_destination") or c.patch.get("team_id")
        if to is None and "active" in c.patch:
            to = "active" if c.patch["active"] else "inactive"
        out.append(
            {
                "org_change_id": c.id,
                "approval_id": c.approval_id,
                "op": c.op.removeprefix("org."),
                "to": to,
                "required_role": c.required_role,
                "expires_at": c.expires_at.isoformat() if c.expires_at else None,
            }
        )
    return out


__all__ = [
    "ChangeResult",
    "apply_change",
    "bind_service",
    "execute_approved",
    "org_executor",
    "pending_for",
    "reconcile",
    "request_agent_patch",
    "request_member_create",
    "request_member_patch",
]
