"""Budgets dashboard API (budgets-ledger): `/api/budgets*` and `/api/killswitch`.

Contract endpoints (CONTRACTS section 5.4): GET /api/budgets, GET /api/budgets/history,
POST /api/budgets/raise, POST /api/budgets/reset (admin), POST /api/killswitch.
Additive (Addendum A-36, page-local TS types): POST /api/budgets/raise/preview,
GET /api/budgets/enforcement, GET /api/budgets/pricing, POST /api/budgets/usage (admin),
GET /api/budgets/sessions.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from pydantic import ValidationError

from aegis.budgets import killswitch as ks_mod
from aegis.budgets import ladder, windows
from aegis.budgets.events import audit_event
from aegis.budgets.ledger import Ledger
from aegis.budgets.limits import DIMENSIONS, SCOPE_TYPES, LimitIndex, scope_type
from aegis.budgets.pricing import PricingTable
from aegis.budgets.schemas import (
    KillSwitchRequest,
    RaiseRequest,
    ResetRequest,
    UsageImportRequest,
)
from aegis.core.deps import get_rt, require_role, viewer
from aegis.core.errors import api_error
from aegis.core.policy_schema import ApplyResult, PatchOp, PolicyChange, PolicyDoc
from aegis.core.types import ROLE_RANK, Identity

log = logging.getLogger(__name__)

ORDER = 100
router = APIRouter(tags=["budgets"])

RT = Depends(get_rt)
VIEWER = Depends(viewer)
ADMIN = Depends(require_role("admin"))
BODY = Body(default_factory=dict)

WINDOWS = ("hour", "day", "week", "month", "session", "total")
# R7: upper bounds for a budget limit / usage import, per dimension. Generous for a real org,
# but rules out Infinity / 1e308 (which would silently disable enforcement in policy.yaml).
MAX_AMOUNT: dict[str, float] = {
    "usd": 1e6,
    "spend_usd": 1e6,
    "tokens": 1e12,
    "compute_s": 1e8,
    "requests": 1e9,
    "tool_calls": 1e9,
}
MAX_SCOPE_LEN = 200
MAX_REASON_LEN = 500
MAX_QUERY_LEN = 200
EMPTY_KS = {"global": False, "teams": [], "members": [], "agents": [], "sessions": []}


def _ledger(rt: Any) -> Ledger | None:
    led = getattr(rt, "ledger", None)
    return led if isinstance(led, Ledger) else None


def _bad(message: str, **fields: Any) -> Any:
    return api_error(400, "invalid_request", message, **fields)


def _validate_scope(scope: str, *, allow_glob: bool = True) -> str | None:
    if len(scope or "") > MAX_SCOPE_LEN:
        return f"scope too long (max {MAX_SCOPE_LEN} characters)"
    kind, _, ident = (scope or "").partition(":")
    if kind not in SCOPE_TYPES or not ident:
        return f"unknown scope {scope!r} (org:|team:|member:|agent:|session:|model:|tool:<id>)"
    if not allow_glob and any(c in ident for c in "*?["):
        return f"scope {scope!r} must be concrete"
    return None


def _check_amount(
    raw: Any, value: float, dimension: str, field: str, *, allow_negative: bool = False
) -> str | None:
    """R7: finite, sign-checked, bounded per dimension; JSON booleans are not amounts."""
    if isinstance(raw, bool):
        return f"{field} must be a number, not a boolean"
    if not math.isfinite(value):
        return f"{field} must be a finite number (got {raw!r})"
    if allow_negative:
        if value == 0:
            return f"{field} must be non-zero"
    elif value <= 0:
        return f"{field} must be > 0"
    cap = MAX_AMOUNT.get(dimension, 1e6)
    if abs(value) > cap:
        return f"{field} {value:g} exceeds the maximum of {cap:g} {dimension}"
    return None


def _check_reason(reason: str | None) -> str | None:
    if reason is not None and len(reason) > MAX_REASON_LEN:
        return f"reason too long (max {MAX_REASON_LEN} characters)"
    return None


def _check_raise(body: dict[str, Any], req: RaiseRequest) -> str | None:
    return (
        _validate_scope(req.scope)
        or _check_amount(
            (body or {}).get("new_limit"), req.new_limit, req.dimension, "new_limit"
        )
        or _check_reason(req.reason)
    )


def _dump(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json", by_alias=True)
    return dict(result)


def _identity_for(led: Ledger | None, scope: str) -> Identity:
    if led is not None:
        return led._scope_ident.get(scope) or led._identity_for_scope(scope)
    return Identity()


def _apply_ops(doc: PolicyDoc, patch: list[PatchOp]) -> PolicyDoc:
    """Apply PatchOps to a copy of the doc (preview only; the real apply is policy-engine's)."""
    from aegis.core.paths import get_path, remove_path, set_path

    data = doc.model_dump(mode="json", by_alias=True)
    for op in patch:
        if op.op == "set":
            set_path(data, op.path, op.value)
        elif op.op == "append":
            lst = get_path(data, op.path)
            if not isinstance(lst, list):
                lst = []
                set_path(data, op.path, lst)
            lst.append(op.value)
        else:
            remove_path(data, op.path)
    return PolicyDoc.model_validate(data)


def _raise_plan(rt: Any, body: RaiseRequest) -> tuple[list[PatchOp], PolicyChange, float | None]:
    snap = rt.policy.snapshot()
    led = _ledger(rt)
    index = LimitIndex.compile(snap)
    entry = index.resolve(body.scope, _identity_for(led, body.scope)).get(
        (body.window, body.dimension)
    )
    if entry is None:  # aggregated / glob scope given literally
        entry = index.find(body.scope, body.window)
        if entry is not None and body.dimension not in entry.dims:
            entry = entry if entry.scope == body.scope else None
    before = entry.dims.get(body.dimension) if entry is not None else None
    patch = ladder.build_raise_patch(
        index, entry, body.scope, body.window, body.dimension, body.new_limit
    )
    change = None
    try:
        from aegis.policy.diff import diff_docs

        changes = diff_docs(snap.doc, _apply_ops(snap.doc, patch))
        change = next((c for c in changes if c.kind.startswith("budget.")), None) or (
            changes[0] if changes else None
        )
    except Exception:
        log.debug("budget preview diff unavailable", exc_info=True)
    if change is None:
        after = body.new_limit
        if before is None:
            kind = "budget.add"
        elif after > before:
            kind = "budget.raise"
        elif after < before:
            kind = "budget.lower"
        else:
            kind = "other"
        pct = ladder.increase_pct(before, after) if before else None
        change = PolicyChange(
            kind=kind,  # type: ignore[arg-type]
            path=patch[0].path,
            before=before,
            after=after,
            scope=body.scope,
            dimension=body.dimension,
            increase_pct=pct,
            loosening=kind == "budget.raise",
            summary=(
                f"{body.scope} {body.window} {body.dimension} "
                f"{ladder.fmt_amount(body.dimension, before or 0)} → "
                f"{ladder.fmt_amount(body.dimension, after)}"
                + (f" ({pct:+.0f}%)" if pct is not None else "")
            ),
        )
    return patch, change, before


def _parse(model: Any, body: Any) -> Any:
    try:
        return model.model_validate(body or {}), None
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", ()))
        return None, _bad(f"invalid {loc or 'body'}: {first.get('msg', 'bad value')}")


# ---------------------------------------------------------------- reads
@router.get("/api/budgets")
async def get_budgets(rt: Any = RT, who: Identity = VIEWER) -> Any:
    led = _ledger(rt)
    if led is None:
        return {
            "generated_at": windows.iso(windows.now()),
            "currency": "USD",
            "pricing_version": PricingTable.default().version,
            "scopes": [],
            "kill_switch": dict(EMPTY_KS),
        }
    return await led.tree()


@router.get("/api/budgets/history")
async def get_history(
    scope: str = Query(..., max_length=MAX_SCOPE_LEN),
    dimension: str = Query("usd", max_length=32),
    window: str = Query("24h", max_length=16),
    rt: Any = RT,
    who: Identity = VIEWER,
) -> Any:
    if err := _validate_scope(scope):
        return _bad(err)
    if dimension not in DIMENSIONS:
        return _bad(f"unknown dimension {dimension!r}")
    led = _ledger(rt)
    if led is None:
        now = windows.iso(windows.now())
        return {
            "scope": scope,
            "dimension": dimension,
            "points": [{"ts": now, "used": 0.0, "limit": 0.0}],
            "forecast": None,
        }
    return await led.history(scope, dimension, window)


@router.get("/api/budgets/enforcement")
async def get_enforcement(window: str = Query("24h", max_length=16), rt: Any = RT, who: Identity = VIEWER) -> Any:
    led = _ledger(rt)
    if led is None:
        return {
            "window": window,
            "loop_detections": 0,
            "by_detector": {},
            "downgrades": 0,
            "hard_blocks": 0,
            "throttles": 0,
            "step_caps": 0,
            "approvals_requested": 0,
            "kills": 0,
            "cost_avoided_usd": 0.0,
            "recent": [],
        }
    return led.enforcement.summary(window)


@router.get("/api/budgets/pricing")
async def get_pricing(rt: Any = RT, who: Identity = VIEWER) -> Any:
    led = _ledger(rt)
    return (led.pricing if led is not None else PricingTable.default()).as_dict()


@router.get("/api/budgets/sessions")
async def get_sessions(
    agent_id: str | None = Query(None, max_length=MAX_QUERY_LEN), rt: Any = RT, who: Identity = VIEWER
) -> Any:
    led = _ledger(rt)
    if led is None:
        return {"items": []}
    items = []
    killed = set(led.kills.sessions())
    ks = led.kill_switch()
    for sid, (seen, ident) in sorted(led._sessions.items(), key=lambda kv: kv[1][0], reverse=True)[
        :100
    ]:
        if agent_id and ident.agent_id != agent_id:
            continue
        st = led.loops.peek(sid)
        items.append(
            {
                "session_id": sid,
                "identity": ident.model_dump(mode="json"),
                "last_seen": windows.iso(seen),
                "usage": {k: round(v, 6) for k, v in led.session_usage(sid).items() if v},
                "loop": st.snapshot() if st is not None else None,
                "killed": sid in killed or bool(ks_mod.match(ks, ident, sid)),
            }
        )
    return {"items": items}


# ---------------------------------------------------------------- governed changes
@router.post("/api/budgets/raise")
async def post_raise(body: dict[str, Any] = BODY, rt: Any = RT, who: Identity = VIEWER) -> Any:
    req, err = _parse(RaiseRequest, body)
    if err is not None:
        return err
    if e := _check_raise(body, req):
        return _bad(e)
    patch, change, _before = _raise_plan(rt, req)
    reason = req.reason or change.summary or f"raise {req.scope}"
    try:
        result = await rt.policy.propose(who, patch=patch, reason=reason, source="dashboard")
    except Exception as exc:
        log.warning("budget raise propose failed scope=%s error=%s", req.scope, exc)
        result = ApplyResult(status="rejected", message=f"policy store unavailable: {exc}")
    out = _dump(result)
    if out.get("status") == "applied":
        led = _ledger(rt)
        if led is not None:
            led.coalescer.mark(None)
    return out


@router.post("/api/budgets/raise/preview")
async def post_raise_preview(
    body: dict[str, Any] = BODY, rt: Any = RT, who: Identity = VIEWER
) -> Any:
    req, err = _parse(RaiseRequest, body)
    if err is not None:
        return err
    if e := _check_raise(body, req):
        return _bad(e)
    patch, change, _before = _raise_plan(rt, req)
    route = None
    can_apply = False
    try:
        route = rt.approvals.route(
            kind="config_change", action_type=change.kind, requester=who, changes=[change]
        )
        need = route.required_role
        if need == "auto":
            can_apply = True
        elif need == "deny" or route.two_person:
            can_apply = False
        elif need == "self":
            can_apply = not who.agent_id and bool(who.member_id)
        else:
            can_apply = ROLE_RANK.get(who.role, 0) >= ROLE_RANK.get(need, 99)
    except Exception:
        log.debug("approvals route unavailable for preview", exc_info=True)
    return {
        "change": change.model_dump(mode="json"),
        "route": route.model_dump(mode="json") if route is not None else None,
        "viewer_can_apply": can_apply,
        "patch": [p.model_dump(mode="json") for p in patch],
    }


@router.post("/api/killswitch")
async def post_killswitch(body: dict[str, Any] = BODY, rt: Any = RT, who: Identity = VIEWER) -> Any:
    req, err = _parse(KillSwitchRequest, body)
    if err is not None:
        return err
    if e := (
        (f"scope too long (max {MAX_SCOPE_LEN} characters)"
         if len(req.scope) > MAX_SCOPE_LEN else None)
        or _check_reason(req.reason)
    ):
        return _bad(e)
    try:
        ks_mod.parse_scope(req.scope)
    except ValueError as exc:
        return _bad(str(exc))
    snap = rt.policy.snapshot()
    patch = ks_mod.toggle_patch(snap, req.scope, req.active)
    if patch is None:
        state = "on" if req.active else "off"
        return _dump(
            ApplyResult(
                status="noop",
                version=getattr(snap, "version", None),
                message=f"kill switch already {state} for {req.scope}",
            )
        )
    reason = req.reason or f"kill switch {'on' if req.active else 'off'}: {req.scope}"
    try:
        result = await rt.policy.propose(who, patch=patch, reason=reason, source="dashboard")
    except Exception as exc:
        log.warning("killswitch propose failed scope=%s error=%s", req.scope, exc)
        result = ApplyResult(status="rejected", message=f"policy store unavailable: {exc}")
    out = _dump(result)
    led = _ledger(rt)
    if out.get("status") == "applied" and led is not None:
        try:
            led._on_policy(rt.policy.snapshot())  # immediate, without waiting for the watcher
        except Exception:
            log.debug("killswitch runtime refresh failed", exc_info=True)
        if not req.active and req.scope.startswith("session:"):
            led.kills.discard(req.scope.split(":", 1)[1])
    return out


# ---------------------------------------------------------------- admin levers
@router.post("/api/budgets/reset")
async def post_reset(body: dict[str, Any] = BODY, rt: Any = RT, who: Identity = ADMIN) -> Any:
    req, err = _parse(ResetRequest, body)
    if err is not None:
        return err
    if req.scope and (e := _validate_scope(req.scope)):
        return _bad(e)
    led = _ledger(rt)
    if led is not None:
        await led.reset(req.scope, reseed=req.reseed)
        await audit_event(
            rt,
            "system",
            actor=who,
            reason=f"budget counters reset ({req.scope or 'all'})",
            data={
                "component": "budgets",
                "action": "reset",
                "scope": req.scope,
                "reseed": req.reseed,
            },
        )
    return {"ok": True}


@router.post("/api/budgets/usage")
async def post_usage(body: dict[str, Any] = BODY, rt: Any = RT, who: Identity = ADMIN) -> Any:
    req, err = _parse(UsageImportRequest, body)
    if err is not None:
        return err
    if e := _validate_scope(req.scope, allow_glob=scope_type(req.scope) in ("model", "tool")):
        return _bad(e)
    if e := (
        _check_amount(body.get("amount"), req.amount, req.dimension, "amount", allow_negative=True)
        or _check_reason(req.reason)
    ):
        return _bad(e)
    led = _ledger(rt)
    if led is None:
        return {"ok": False, "statuses": []}
    statuses = await led.import_usage(req.scope, req.dimension, req.amount, req.window)
    await audit_event(
        rt,
        "system",
        actor=who,
        reason=f"usage import: {req.reason}",
        data={
            "component": "budgets",
            "action": "usage_import",
            "scope": req.scope,
            "window": req.window,
            "dimension": req.dimension,
            "amount": req.amount,
        },
    )
    return {"ok": True, "statuses": [s.model_dump(mode="json") for s in statuses]}
