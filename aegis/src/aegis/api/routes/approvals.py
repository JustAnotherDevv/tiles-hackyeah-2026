"""Dashboard API `/api/approvals*` (CONTRACTS section 5.4; owner approvals-engine).

| Method & path                              | Behaviour                                              |
|--------------------------------------------|--------------------------------------------------------|
| GET  /api/approvals                        | ApprovalsResponse; items carry can_vote / why_not;     |
|                                            | ?status= ?kind= ?mine= ?actionable= ?limit=            |
| GET  /api/approvals/rules                  | ApprovalRulesResponse (ordered, human `when`)          |
| POST /api/approvals/simulate               | ApprovalRoute (+ `explain` extension)                  |
| POST /api/approvals                        | ApprovalDraft -> manual ApprovalRequest                |
| GET  /api/approvals/{id}                   | ApprovalRequest + can_vote / why_not                   |
| GET  /api/approvals/{id}/wait?timeout_s=   | long-poll until decided (extension, <= 60 s)           |
| GET  /api/approvals/{id}/timeline          | audit events of this approval (extension)              |
| POST /api/approvals/{id}/approve | /deny   | 403 forbidden (why_not) · 409 conflict · 404          |
| POST /api/approvals/{id}/cancel            | requester / sponsor / admin                            |
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from aegis.core.types import ApprovalDraft, ApprovalRequest, Identity

log = logging.getLogger(__name__)

ORDER = 100
router = APIRouter(tags=["approvals"])

STATUSES = ("pending", "approved", "denied", "expired", "cancelled")
KINDS = ("action", "config_change", "budget_raise", "mcp_pin")


# ---------------------------------------------------------------- guarded core surfaces
def _error(status: int, type_: str, message: str, **fields: Any) -> JSONResponse:
    try:
        from aegis.core.errors import api_error  # type: ignore[import-not-found]

        return api_error(status, type_, message, **fields)
    except Exception:  # TODO(integration): core-gateway errors not landed yet
        inner = {"type": type_, "message": message, "control_id": None, "decision_id": None,
                 "approval_id": None, "required_role": None, "expires_at": None, "scope": None,
                 "retry_after_s": None}
        inner.update(fields)
        return JSONResponse({"error": inner}, status_code=status)


def _rt(request: Request) -> Any:
    rt = getattr(request.app.state, "rt", None)
    if rt is None:
        try:
            from aegis.core.runtime import get_runtime  # type: ignore[import-not-found]

            rt = get_runtime()
        except Exception:
            rt = None
    return rt


async def _viewer(request: Request, rt: Any) -> Identity:
    try:
        from aegis.core.deps import viewer as core_viewer  # type: ignore[import-not-found]

        return await core_viewer(request)
    except ImportError:
        pass
    except Exception:
        log.debug("core viewer dependency failed; falling back", exc_info=True)
    org = getattr(rt, "org", None)
    if org is not None:
        try:
            return await org.resolve_viewer(request.headers, request.query_params)
        except Exception:
            log.debug("resolve_viewer failed", exc_info=True)
    # TODO(integration): org-rbac absent -> demo viewer from header, else owner
    member = request.headers.get("x-aegis-view-as") or request.query_params.get("view_as")
    svc = getattr(rt, "approvals", None)
    cache = getattr(svc, "org", None)
    if member and cache is not None:
        return cache.identity_for(member)
    return Identity(member_id=member or "u_katarzyna", role="owner" if not member else "member")


def _svc(rt: Any) -> Any:
    return getattr(rt, "approvals", None) if rt is not None else None


def _view(svc: Any, req: ApprovalRequest, viewer: Identity) -> dict[str, Any]:
    try:
        from aegis.approvals.views import trimmed

        data = trimmed(req)
    except Exception:
        data = req.model_dump(mode="json")
    can, why = False, "approvals unavailable"
    if svc is not None and hasattr(svc, "can_approve"):
        try:
            can, why = svc.can_approve(viewer, req)
        except Exception:
            can, why = False, "eligibility check failed"
    data["can_vote"] = bool(can)
    data["why_not"] = None if can else (why or None)
    can_deny = can
    if svc is not None and hasattr(svc, "can_deny") and req.status == "pending":
        try:
            can_deny = bool(svc.can_deny(viewer, req)[0])
        except Exception:
            can_deny = False
    data["can_deny"] = can_deny
    data["can_cancel"] = _can_cancel(svc, req, viewer)
    return data


def _can_cancel(svc: Any, req: ApprovalRequest, viewer: Identity) -> bool:
    if req.status != "pending":
        return False
    org = getattr(svc, "org", None)
    role = org.role_of(viewer) if org is not None else viewer.role
    if role in ("admin", "owner"):
        return True
    sponsor = req.payload.get("routing", {}).get("requester_member") if isinstance(
        req.payload, dict) else None
    return bool(viewer.member_id) and viewer.member_id in {sponsor, req.requester.member_id}


def _is_mine(req: ApprovalRequest, viewer: Identity) -> bool:
    """A-28: requested by the viewer or by an agent the viewer sponsors."""
    if not viewer.member_id:
        return bool(viewer.agent_id) and viewer.agent_id == req.requester.agent_id
    if viewer.member_id == req.requester.member_id:
        return True
    routing = req.payload.get("routing", {}) if isinstance(req.payload, dict) else {}
    return viewer.member_id == routing.get("requester_member")


# ---------------------------------------------------------------- list / rules / simulate
@router.get("/api/approvals")
async def list_approvals(
    request: Request,
    status: str = Query("all"),
    kind: str | None = Query(None),
    mine: bool = Query(False),
    actionable: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
) -> Any:
    rt = _rt(request)
    svc = _svc(rt)
    viewer = await _viewer(request, rt)
    if status not in (*STATUSES, "all"):
        return _error(400, "invalid_request", f"unknown status {status!r}")
    if kind is not None and kind not in KINDS:
        return _error(400, "invalid_request", f"unknown kind {kind!r}")
    if svc is None:
        return {"items": [], "counts": dict.fromkeys(STATUSES, 0)}
    items = await svc.list_requests(status=None if status == "all" else status, kind=kind,
                                    limit=limit)
    views = []
    for req in items:
        if mine and not _is_mine(req, viewer):
            continue
        v = _view(svc, req, viewer)
        if actionable and not (req.status == "pending" and v["can_vote"]):
            continue
        views.append(v)
    counts = svc.counts() if hasattr(svc, "counts") else dict.fromkeys(STATUSES, 0)
    return {"items": views, "counts": {s: int(counts.get(s, 0)) for s in STATUSES}}


@router.get("/api/approvals/rules")
async def approval_rules(request: Request) -> Any:
    svc = _svc(_rt(request))
    if svc is None or not hasattr(svc, "rules_view"):
        return {"rules": [], "config_rules": [],
                "defaults": {"ttl_s": 900, "default_approver": "admin",
                             "default_config_approver": "owner"}}
    return svc.rules_view()


class SimulateBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str = "action"
    action_type: str = ""
    amount_usd: float | None = None
    resource: str | None = None
    requester_member_id: str | None = None
    requester_agent_id: str | None = None
    # extensions (dashboard rules simulator / budget raise preview)
    labels: dict[str, Any] | None = None
    profile: str | None = None
    changes: list[dict[str, Any]] | None = None
    scope: str | None = None
    scope_type: str | None = None
    increase_pct: float | None = None
    control_id: str | None = None
    loosening: bool | None = None


@router.post("/api/approvals/simulate")
async def simulate(request: Request, body: SimulateBody) -> Any:
    rt = _rt(request)
    svc = _svc(rt)
    if body.kind not in KINDS:
        return _error(400, "invalid_request", f"unknown kind {body.kind!r}")
    if svc is None or not hasattr(svc, "simulate"):
        return _error(501, "not_implemented", "approvals service unavailable")
    viewer = await _viewer(request, rt)
    change = None
    if body.kind == "config_change" and not body.changes:
        change = {"kind": body.action_type or "other", "path": "simulated",
                  "scope": body.scope, "control_id": body.control_id,
                  "increase_pct": body.increase_pct, "loosening": bool(body.loosening)}
        if body.scope_type and not body.scope:
            change["facts"] = {"scope_type": body.scope_type}
        if change["kind"] not in _change_kinds():
            change = None
    try:
        return svc.simulate(
            kind=body.kind, action_type=body.action_type or (body.kind if body.kind != "action" else ""),
            viewer=viewer, amount_usd=body.amount_usd, resource=body.resource,
            requester_member_id=body.requester_member_id,
            requester_agent_id=body.requester_agent_id, labels=body.labels,
            profile=body.profile, changes=body.changes, change=change,
        )
    except Exception as exc:
        log.exception("approval simulate failed")
        return _error(400, "invalid_request", f"simulation failed: {exc}")


def _change_kinds() -> set[str]:
    from typing import get_args

    from aegis.core.policy_schema import ChangeKind

    return set(get_args(ChangeKind))


# ---------------------------------------------------------------- manual requests
@router.post("/api/approvals")
async def create_manual(request: Request, draft: ApprovalDraft) -> Any:
    rt = _rt(request)
    svc = _svc(rt)
    if svc is None:
        return _error(503, "unavailable", "approvals unavailable")
    viewer = await _viewer(request, rt)
    if draft.kind in ("config_change", "mcp_pin"):
        return _error(
            400, "invalid_request",
            "config changes go through /api/policy/apply or /api/budgets/raise; MCP re-pins "
            "through /api/mcp — they compute the change set server-side",
        )
    if draft.action_type.startswith("org."):
        return _error(400, "invalid_request", "org changes go through /api/members and /api/agents")
    if draft.kind == "budget_raise":
        patch = (draft.payload or {}).get("patch") or []
        if not isinstance(patch, list) or any(
            not str((p or {}).get("path", "")).startswith("budgets.limits") for p in patch
        ):
            return _error(400, "invalid_request",
                          "a budget_raise request may only patch budgets.limits entries")
    req = await svc.create_manual(viewer, draft)
    return _view(svc, req, viewer)


# ---------------------------------------------------------------- one request
@router.get("/api/approvals/{approval_id}")
async def get_approval(request: Request, approval_id: str) -> Any:
    rt = _rt(request)
    svc = _svc(rt)
    req = await svc.get(approval_id) if svc is not None else None
    if req is None:
        return _error(404, "not_found", f"approval {approval_id} not found",
                      approval_id=approval_id)
    return _view(svc, req, await _viewer(request, rt))


@router.get("/api/approvals/{approval_id}/wait")
async def wait_approval(
    request: Request, approval_id: str, timeout_s: float = Query(25.0, ge=0, le=60)
) -> Any:
    rt = _rt(request)
    svc = _svc(rt)
    if svc is None:
        return _error(404, "not_found", f"approval {approval_id} not found")
    try:
        try:
            req = await svc.wait(approval_id, timeout_s, consume=False)
        except TypeError:  # foreign implementation without `consume`
            req = await svc.wait(approval_id, timeout_s)
    except KeyError:
        return _error(404, "not_found", f"approval {approval_id} not found",
                      approval_id=approval_id)
    return _view(svc, req, await _viewer(request, rt))


@router.get("/api/approvals/{approval_id}/timeline")
async def approval_timeline(request: Request, approval_id: str) -> Any:
    rt = _rt(request)
    svc = _svc(rt)
    req = await svc.get(approval_id) if svc is not None else None
    if req is None:
        return _error(404, "not_found", f"approval {approval_id} not found")
    audit = getattr(rt, "audit", None)
    items: list[dict[str, Any]] = []
    if audit is not None:
        for event_type in ("approval.created", "approval.decided", "approval.executed",
                           "approval.expired", "system"):
            try:
                events, _ = await audit.query(event_type=event_type, limit=500)
            except Exception:
                continue
            for ev in events:
                if (ev.data or {}).get("approval_id") == approval_id:
                    items.append(ev.model_dump(mode="json", by_alias=True))
    items.sort(key=lambda e: (e.get("ts") or "", e.get("seq") or 0))
    return {"approval_id": approval_id, "items": items}


class VoteBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    comment: str | None = None


async def _vote(request: Request, approval_id: str, decision: str, body: VoteBody | None) -> Any:
    rt = _rt(request)
    svc = _svc(rt)
    if svc is None:
        return _error(503, "unavailable", "approvals unavailable")
    viewer = await _viewer(request, rt)
    try:
        req = await svc.vote(approval_id, viewer, decision, (body.comment if body else None))
    except KeyError:
        return _error(404, "not_found", f"approval {approval_id} not found",
                      approval_id=approval_id)
    except PermissionError as exc:
        return _error(403, "forbidden", str(exc) or "not allowed to vote",
                      approval_id=approval_id)
    except ValueError as exc:
        return _error(409, "conflict", str(exc), approval_id=approval_id)
    return _view(svc, req, viewer)


@router.post("/api/approvals/{approval_id}/approve")
async def approve(request: Request, approval_id: str, body: Annotated[VoteBody | None, Body()] = None) -> Any:
    return await _vote(request, approval_id, "approve", body)


@router.post("/api/approvals/{approval_id}/deny")
async def deny(request: Request, approval_id: str, body: Annotated[VoteBody | None, Body()] = None) -> Any:
    return await _vote(request, approval_id, "deny", body)


@router.post("/api/approvals/{approval_id}/cancel")
async def cancel(request: Request, approval_id: str) -> Any:
    rt = _rt(request)
    svc = _svc(rt)
    if svc is None:
        return _error(503, "unavailable", "approvals unavailable")
    viewer = await _viewer(request, rt)
    try:
        req = await svc.cancel(approval_id, viewer)
    except KeyError:
        return _error(404, "not_found", f"approval {approval_id} not found")
    except PermissionError as exc:
        return _error(403, "forbidden", str(exc), approval_id=approval_id)
    except ValueError as exc:
        return _error(409, "conflict", str(exc), approval_id=approval_id)
    return _view(svc, req, viewer)


__all__ = ["ORDER", "router"]
