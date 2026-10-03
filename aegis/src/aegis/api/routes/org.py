"""Org & RBAC dashboard API (CONTRACTS section 5.4 + plan 08 section 2.9 additive endpoints).

`/api/org`, `/api/members*`, `/api/agents*`, `/api/whoami`. Viewer = `rt.org.resolve_viewer`
(X-Aegis-View-As / ?view_as= / aegis_view_as cookie). Gated member changes answer
403 `approval_required` with the approval id (CONTRACTS section 5.3 envelope).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from aegis.core.types import Identity, utcnow
from aegis.org import changes as org_changes
from aegis.org import compat
from aegis.org import permissions as perms
from aegis.org.service import OrgServiceImpl

log = logging.getLogger(__name__)

router = APIRouter(tags=["org"])
ORDER = 100
ACTIVE_WINDOW = timedelta(minutes=10)
SPEND_TIMEOUT_S = 0.2


# ---------------------------------------------------------------- request bodies


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MemberCreate(_Body):
    name: str
    email: str | None = None
    role: Literal["owner", "admin", "member"] = "member"
    team_id: str | None = None
    title: str | None = None


class MemberPatch(_Body):
    role: Literal["owner", "admin", "member"] | None = None
    team_id: str | None = None
    active: bool | None = None
    title: str | None = None
    name: str | None = None


class AgentPatch(_Body):
    active: bool | None = None
    allowed_models: list[str] | None = None
    allowed_tools: list[str] | None = None
    denied_tools: list[str] | None = None
    profile: str | None = None
    max_destination: Literal["local", "remote", "third_party"] | None = None
    owner_member_id: str | None = None


class KeyCreate(_Body):
    scopes: list[str] | None = None
    expires_at: datetime | None = None


class ViewAsBody(_Body):
    view_as: str


# ---------------------------------------------------------------- helpers


async def _ctx(request: Request) -> tuple[Any, Identity]:
    rt = await compat.get_rt(request)
    viewer = await rt.org.resolve_viewer(request.headers, request.query_params)
    return rt, viewer


def _svc(rt: Any) -> OrgServiceImpl | None:
    org = getattr(rt, "org", None)
    return org if isinstance(org, OrgServiceImpl) else None


def _unavailable() -> Any:
    return compat.api_error(503, "unavailable", "org service unavailable (fallback org active)")


def _not_found(what: str) -> Any:
    return compat.api_error(404, "not_found", f"{what} not found")


async def _body(request: Request, model: type[BaseModel]) -> tuple[Any, Any]:
    try:
        raw = await request.json()
    except Exception:
        raw = None
    if not isinstance(raw, dict):
        return None, compat.api_error(400, "invalid_request", "JSON object body required")
    try:
        return model.model_validate(raw), None
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {"loc": (), "msg": "invalid"}
        loc = ".".join(str(p) for p in first.get("loc", ()))
        return None, compat.api_error(400, "invalid_request", f"{loc}: {first.get('msg')}")


def _snapshot(rt: Any) -> Any:
    try:
        return rt.policy.snapshot()
    except Exception:
        return None


async def _reconcile(svc: OrgServiceImpl | None) -> None:
    if svc is None or not svc.pending:
        return
    try:
        await svc.reconcile()
    except Exception:
        log.warning("org reconcile failed", exc_info=True)


def _member_json(svc: OrgServiceImpl | None, m: Any) -> dict[str, Any]:
    d = m.model_dump(mode="json")
    if svc is not None:
        d["agents"] = svc.sponsored(m.id)
        meta = dict(d.get("meta") or {})
        meta["pending_changes"] = org_changes.pending_for(svc, m.id)
        d["meta"] = meta
    else:
        d.setdefault("agents", [])
    return d


def _result_response(res: org_changes.ChangeResult) -> Any:
    if res.outcome in ("applied", "noop"):
        if res.entity is None:
            return JSONResponse({"ok": True}, status_code=res.status)
        svc_entity = res.entity.model_dump(mode="json")
        return JSONResponse(svc_entity, status_code=res.status)
    if res.outcome == "pending":
        return compat.api_error(403, "approval_required", res.message, **res.fields)
    if res.outcome == "not_found":
        return compat.api_error(404, "not_found", res.message)
    if res.outcome == "conflict":
        return compat.api_error(409, "conflict", res.message)
    if res.outcome == "invalid":
        return compat.api_error(400, "invalid_request", res.message)
    return compat.api_error(403, "forbidden", res.message, **res.fields)


def _killed(agent: Any, kill: Any) -> bool:
    if kill is None:
        return False
    if getattr(kill, "global_", False):
        return True
    if agent.team_id and agent.team_id in (kill.teams or []):
        return True
    if agent.owner_member_id and agent.owner_member_id in (kill.members or []):
        return False  # member kill switches stop the human, not the sponsored agents
    return compat.glob_any(list(kill.agents or []), agent.id)


async def _spend_today(rt: Any, agent_id: str) -> float:
    ledger = getattr(rt, "ledger", None)
    if ledger is None:
        return 0.0
    try:
        rows = await asyncio.wait_for(ledger.status(scope=f"agent:{agent_id}"), SPEND_TIMEOUT_S)
    except Exception:
        return 0.0
    for row in rows or []:
        if getattr(row, "dimension", None) == "usd" and getattr(row, "window", None) == "day":
            return round(float(getattr(row, "used", 0.0) or 0.0), 4)
    return 0.0


def _agent_status(agent: Any, kill: Any, now: datetime) -> str:
    if not agent.active or _killed(agent, kill):
        return "killed"
    if agent.last_seen and now - agent.last_seen < ACTIVE_WINDOW:
        return "active"
    return "idle"


async def _agents_json(rt: Any, svc: OrgServiceImpl | None, agents: list[Any]) -> list[dict]:
    snap = _snapshot(rt)
    kill = getattr(getattr(getattr(snap, "doc", None), "budgets", None), "kill_switch", None)
    now = utcnow()
    spends = await asyncio.gather(*(_spend_today(rt, a.id) for a in agents))
    out = []
    for agent, spend in zip(agents, spends, strict=True):
        d = agent.model_dump(mode="json")
        d["status"] = _agent_status(agent, kill, now)
        d["spend_today_usd"] = spend
        if svc is not None:
            d["keys"] = [k.view(now) for k in svc.list_keys(agent.id)]
            meta = dict(d.get("meta") or {})
            meta["pending_changes"] = org_changes.pending_for(svc, agent.id)
            d["meta"] = meta
        out.append(d)
    return out


def _view_as_options(svc: OrgServiceImpl | None, members: list[Any]) -> list[dict[str, Any]]:
    out = []
    for m in members:
        if not m.active:
            continue
        out.append(
            {
                "member_id": m.id,
                "name": m.name,
                "role": m.role,
                "label": m.meta.get("view_as_label") or f"{m.role.title()} - {m.name}",
                "team_id": m.team_id,
            }
        )
    return out


# ---------------------------------------------------------------- read endpoints


@router.get("/api/whoami")
async def whoami(request: Request) -> Any:
    rt, viewer = await _ctx(request)
    svc = _svc(rt)
    await _reconcile(svc)
    member = await rt.org.get_member(viewer.member_id) if viewer.member_id else None
    members = await rt.org.list_members()
    snap = _snapshot(rt)
    if svc is not None:
        permissions = perms.whoami_permissions(rt, svc.cache, viewer, snap)
        capabilities = perms.capabilities_for(rt, svc.cache, viewer)
    else:
        owner = viewer.role == "owner"
        permissions = {
            "can_apply_policy": "yes" if owner else "approval",
            "can_manage_members": viewer.role in ("owner", "admin"),
            "can_killswitch": viewer.role in ("owner", "admin"),
            "can_export_audit": viewer.role in ("owner", "admin"),
            "approver_levels": ["self"]
            + (["admin"] if viewer.role in ("owner", "admin") else [])
            + (["owner"] if owner else []),
        }
        capabilities = {}
    return {
        "identity": viewer.model_dump(mode="json"),
        "member": _member_json(svc, member) if member else None,
        "permissions": permissions,
        "capabilities": capabilities,
        "view_as_options": _view_as_options(svc, members),
    }


@router.post("/api/whoami")
async def set_view_as(request: Request) -> Any:
    """Sets the `aegis_view_as` cookie (browser downloads / EventSource without headers)."""
    rt = await compat.get_rt(request)
    body, err = await _body(request, ViewAsBody)
    if err is not None:
        return err
    svc = _svc(rt)
    from aegis.org.identity import resolve_alias

    mid = resolve_alias(svc.cache, body.view_as) if svc else body.view_as
    if svc is not None and mid is None:
        return compat.api_error(400, "invalid_request", f"unknown member {body.view_as!r}")
    resp = JSONResponse({"ok": True, "view_as": mid})
    resp.set_cookie("aegis_view_as", str(mid), samesite="lax", httponly=False, path="/")
    return resp


@router.get("/api/org")
async def get_org(request: Request) -> Any:
    rt, _viewer = await _ctx(request)
    svc = _svc(rt)
    org = await rt.org.org()
    teams = await rt.org.list_teams()
    members = await rt.org.list_members()
    agents = await rt.org.list_agents()
    team_rows = []
    for t in teams:
        d = t.model_dump(mode="json")
        d["member_count"] = sum(
            1 for m in members if t.id == m.team_id or t.id in (m.meta.get("teams") or [])
        )
        d["agent_count"] = sum(1 for a in agents if a.team_id == t.id)
        team_rows.append(d)
    meta: dict[str, Any] = {}
    if svc is not None:
        meta = {
            k: svc.cache.org_meta.get(k)
            for k in ("description", "timezone", "email_domain", "seed_version", "policy_profile")
        }
        meta["health"] = svc.health()
        snap = _snapshot(rt)
        if snap is not None:
            meta["policy_profile"] = snap.doc.profile
    return {
        "org": org.model_dump(mode="json"),
        "teams": team_rows,
        "counts": {"members": len(members), "agents": len(agents), "teams": len(teams)},
        "meta": meta,
    }


@router.get("/api/members")
async def list_members(
    request: Request,
    team_id: str | None = None,
    role: str | None = None,
    active: bool | None = None,
) -> Any:
    rt, _viewer = await _ctx(request)
    svc = _svc(rt)
    await _reconcile(svc)
    members = await rt.org.list_members()
    if team_id:
        members = [
            m for m in members if m.team_id == team_id or team_id in (m.meta.get("teams") or [])
        ]
    if role:
        members = [m for m in members if m.role == role]
    if active is not None:
        members = [m for m in members if m.active == active]
    return {"items": [_member_json(svc, m) for m in members]}


@router.get("/api/members/{member_id}")
async def get_member(request: Request, member_id: str) -> Any:
    rt, _viewer = await _ctx(request)
    svc = _svc(rt)
    await _reconcile(svc)
    member = await rt.org.get_member(member_id)
    if member is None:
        return _not_found(f"member {member_id}")
    return _member_json(svc, member)


@router.get("/api/agents")
async def list_agents(request: Request) -> Any:
    rt, _viewer = await _ctx(request)
    svc = _svc(rt)
    agents = await rt.org.list_agents()
    return {"items": await _agents_json(rt, svc, agents)}


@router.get("/api/agents/{agent_id}")
async def get_agent(request: Request, agent_id: str) -> Any:
    rt, _viewer = await _ctx(request)
    agent = await rt.org.get_agent(agent_id)
    if agent is None:
        return _not_found(f"agent {agent_id}")
    return (await _agents_json(rt, _svc(rt), [agent]))[0]


@router.get("/api/org/permissions")
async def org_permissions(request: Request) -> Any:
    rt, _viewer = await _ctx(request)
    return perms.matrix(rt, _snapshot(rt))


@router.get("/api/org/changes")
async def list_org_changes(request: Request, status: str | None = None, limit: int = 100) -> Any:
    rt, _viewer = await _ctx(request)
    svc = _svc(rt)
    if svc is None:
        return {"items": []}
    await _reconcile(svc)
    items = await svc.list_changes(
        status if status and status != "all" else None, max(1, min(limit, 1000))
    )
    return {"items": [c.model_dump(mode="json") for c in items]}


# ---------------------------------------------------------------- governed mutations


@router.post("/api/members")
async def create_member(request: Request) -> Any:
    rt, viewer = await _ctx(request)
    svc = _svc(rt)
    if svc is None:
        return _unavailable()
    body, err = await _body(request, MemberCreate)
    if err is not None:
        return err
    res = await org_changes.request_member_create(svc, viewer, body.model_dump(exclude_none=True))
    if res.outcome == "applied" and res.entity is not None:
        return JSONResponse(_member_json(svc, res.entity), status_code=201)
    return _result_response(res)


@router.patch("/api/members/{member_id}")
async def patch_member(request: Request, member_id: str) -> Any:
    rt, viewer = await _ctx(request)
    svc = _svc(rt)
    if svc is None:
        return _unavailable()
    body, err = await _body(request, MemberPatch)
    if err is not None:
        return err
    patch = body.model_dump(exclude_unset=True)
    if "team_id" in patch and patch["team_id"] is None:
        patch.pop("team_id")
    res = await org_changes.request_member_patch(svc, viewer, member_id, patch)
    if res.outcome in ("applied", "noop") and res.entity is not None:
        return JSONResponse(_member_json(svc, res.entity), status_code=200)
    return _result_response(res)


@router.patch("/api/agents/{agent_id}")
async def patch_agent(request: Request, agent_id: str) -> Any:
    rt, viewer = await _ctx(request)
    svc = _svc(rt)
    if svc is None:
        return _unavailable()
    body, err = await _body(request, AgentPatch)
    if err is not None:
        return err
    patch = body.model_dump(exclude_unset=True)
    res = await org_changes.request_agent_patch(svc, viewer, agent_id, patch)
    if res.outcome in ("applied", "noop") and res.entity is not None:
        return JSONResponse((await _agents_json(rt, svc, [res.entity]))[0], status_code=200)
    return _result_response(res)


# ---------------------------------------------------------------- agent keys (ORG-12)


@router.get("/api/agents/{agent_id}/keys")
async def list_agent_keys(request: Request, agent_id: str) -> Any:
    rt, viewer = await _ctx(request)
    svc = _svc(rt)
    if svc is None:
        return _unavailable()
    if not perms.satisfies(perms.viewer_active_role(svc.cache, viewer), "admin"):
        return compat.api_error(
            403, "forbidden", "viewing agent keys requires admin", required_role="admin"
        )
    if agent_id not in svc.cache.agents:
        return _not_found(f"agent {agent_id}")
    now = utcnow()
    return {"items": [k.view(now) for k in svc.list_keys(agent_id)]}


@router.post("/api/agents/{agent_id}/keys")
async def issue_agent_key(request: Request, agent_id: str) -> Any:
    rt, viewer = await _ctx(request)
    svc = _svc(rt)
    if svc is None:
        return _unavailable()
    if agent_id not in svc.cache.agents:
        return _not_found(f"agent {agent_id}")
    authz = perms.authorize_simple(rt, svc.cache, viewer, "org.agent.key", f"agent:{agent_id}")
    if authz.decision != "direct":
        return compat.api_error(
            403, "forbidden", f"issuing keys: {authz.reason}", required_role=authz.required
        )
    body = KeyCreate()
    if (await request.body()).strip():
        body, err = await _body(request, KeyCreate)
        if err is not None:
            return err
    rec, plaintext = await svc.issue_key(
        agent_id, actor=viewer, scopes=body.scopes, expires_at=body.expires_at
    )
    out = rec.view()
    out["key"] = plaintext  # shown once; only the HMAC is stored
    return JSONResponse(out, status_code=201, headers={"Cache-Control": "no-store"})


@router.post("/api/agents/{agent_id}/keys/{key_id}/revoke")
async def revoke_agent_key(request: Request, agent_id: str, key_id: str) -> Any:
    rt, viewer = await _ctx(request)
    svc = _svc(rt)
    if svc is None:
        return _unavailable()
    rec = svc.cache.keys_by_id.get(key_id)
    if rec is None or rec.principal != f"agent:{agent_id}":
        return _not_found(f"key {key_id}")
    authz = perms.authorize_simple(rt, svc.cache, viewer, "org.agent.key", f"agent:{agent_id}")
    if authz.decision != "direct":
        return compat.api_error(
            403, "forbidden", f"revoking keys: {authz.reason}", required_role=authz.required
        )
    revoked = await svc.revoke_key(key_id, actor=viewer)
    return revoked.view() if revoked else _not_found(f"key {key_id}")


# ---------------------------------------------------------------- lifecycle

#: Register org_executor as the approvals `action` executor (CONTRACTS A-25). It handles
#: `org.*` only and returns None otherwise, so ordinary action grants stay redeemable. The
#: approval.updated listener + read-time reconcile are the safety nets.
REGISTER_ACTION_EXECUTOR = True


async def _listen(rt: Any, svc: OrgServiceImpl) -> None:
    try:
        async for msg in rt.bus.subscribe({"approval.updated", "approval.created"}):
            data = getattr(msg, "data", None) or {}
            action_type = str(data.get("action_type") or "")
            if action_type and not action_type.startswith("org."):
                continue
            if data.get("status") in (None, "pending") and action_type:
                continue
            try:
                await svc.reconcile(data.get("id"))
            except Exception:
                log.warning("org reconcile from bus failed", exc_info=True)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("org approval listener stopped", exc_info=True)


async def on_startup(rt: Any) -> None:
    svc = _svc(rt)
    if svc is None:
        return
    org_changes.bind_service(svc)
    if REGISTER_ACTION_EXECUTOR:
        try:
            rt.approvals.register_executor("action", org_changes.org_executor)
        except Exception:
            log.warning("could not register org executor", exc_info=True)
    if not svc.test_mode and getattr(rt, "bus", None) is not None:
        svc.listener_task = asyncio.get_running_loop().create_task(_listen(rt, svc))
    await _reconcile(svc)


async def on_shutdown(rt: Any) -> None:
    svc = _svc(rt)
    if svc is not None and svc.listener_task is not None:
        svc.listener_task.cancel()
        svc.listener_task = None


__all__ = ["ORDER", "on_shutdown", "on_startup", "router"]
