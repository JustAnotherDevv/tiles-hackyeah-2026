# ruff: noqa: B008 - FastAPI Depends()/Query() defaults are the documented pattern
"""Dashboard API `/api/policy*`, `/api/controls`, `/api/coverage` (CONTRACTS 5.4 + Addendum A-31; owner policy-engine).

| Method & path                     | Role    | Response                                              |
|-----------------------------------|---------|-------------------------------------------------------|
| GET  /api/policy                  | member  | PolicyResponse                                        |
| GET  /api/policy/schema           | member  | JSON Schema of PolicyDoc (Monaco)                     |
| POST /api/policy/validate         | member  | ValidationReport (`selftest: false` = schema only)    |
| POST /api/policy/diff             | member  | PolicyDiffResponse (+ rule_id); 422 on invalid YAML   |
| POST /api/policy/apply            | member  | ApplyResult (governed propose); 409 when stale        |
| GET  /api/policy/history          | member  | {items: PolicyVersionInfo[]}                          |
| GET  /api/policy/versions/{v}     | member  | {version, yaml}; 404                                  |
| POST /api/policy/rollback         | member  | ApplyResult (governed like apply)                     |
| POST /api/policy/reload           | admin   | ApplyResult (re-read config/policy.yaml)              |
| GET  /api/policy/selftest         | member  | SelfTestRun; 404 before the first run                 |
| POST /api/policy/selftest         | admin   | SelfTestRun                                           |
| GET  /api/policy/status           | member  | store status (additive)                               |
| GET  /api/policy/effective        | member  | effective control configs (?profile=, additive)       |
| GET  /api/controls                | member  | {items: ControlView[]}                                |
| GET  /api/coverage                | member  | CoverageResponse                                      |
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from aegis.core.deps import get_rt, require_role
from aegis.core.errors import api_error
from aegis.core.policy_schema import ApplyResult, PolicyChange, ValidationIssue
from aegis.core.types import Identity

log = logging.getLogger(__name__)

ORDER = 100
router = APIRouter(tags=["policy"])

_member = require_role("member")
_admin = require_role("admin")


# ---------------------------------------------------------------- bodies
class _Body(BaseModel):
    model_config = ConfigDict(extra="allow")


class YamlBody(_Body):
    yaml: str
    selftest: bool = True


class ApplyBody(_Body):
    yaml: str
    base_version: int | None = None
    reason: str | None = None


class RollbackBody(_Body):
    version: int
    reason: str | None = None


class SelfTestBody(_Body):
    which: str = "all"
    profile: str | None = None


# ---------------------------------------------------------------- helpers
def _store(rt: Any) -> Any:
    return rt.policy


def _dump(model: Any) -> Any:
    if isinstance(model, BaseModel):
        return model.model_dump(mode="json", by_alias=True)
    return model


def _issues(errors: list[ValidationIssue]) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json") for e in errors]


def _route(rt: Any, viewer: Identity, changes: list[PolicyChange]) -> Any:
    """`rt.approvals.route(kind="config_change", ...)` or None (never raises)."""
    approvals = getattr(rt, "approvals", None)
    fn = getattr(approvals, "route", None)
    if not callable(fn) or not changes:
        return None
    try:
        from aegis.policy.diff import primary_kind

        return fn(kind="config_change", action_type=primary_kind(changes), requester=viewer, changes=changes)
    except Exception as exc:
        log.debug("approval route unavailable: %s", exc)
        return None


def _apply_response(res: ApplyResult) -> Any:
    body = _dump(res)
    if res.status == "conflict":
        return api_error(409, "conflict", res.message or "policy changed underneath you",
                         current_version=res.version, result=body)
    return body


def _invalid(errors: list[ValidationIssue], message: str | None = None) -> JSONResponse:
    from aegis.policy.validate import first_error_message

    return api_error(422, "invalid_request", message or first_error_message(errors) or "invalid policy YAML",
                     errors=_issues(errors))


# ---------------------------------------------------------------- policy
@router.get("/api/policy")
async def get_policy(rt: Any = Depends(get_rt), _v: Identity = Depends(_member)) -> Any:
    store = _store(rt)
    snap = store.snapshot()
    return {
        "version": snap.version,
        "yaml": store.current_yaml(),
        "sha256": snap.sha256,
        "applied_at": snap.applied_at.isoformat().replace("+00:00", "Z"),
        "applied_by": snap.applied_by,
        "source": snap.source,
        "profile": snap.doc.profile,
        "controls_count": len(snap.controls),
    }


@router.get("/api/policy/schema")
async def get_schema(_v: Identity = Depends(_member)) -> Any:
    from aegis.policy.schema import build_schema

    return build_schema()


@router.get("/api/policy/status")
async def get_status(rt: Any = Depends(get_rt), _v: Identity = Depends(_member)) -> Any:
    store = _store(rt)
    fn = getattr(store, "status", None)
    if callable(fn):
        st = dict(fn())
        w = getattr(store, "watcher", None)
        st["watcher"] = bool(getattr(w, "running", False))
        return st
    snap = store.snapshot()
    return {"state": "ok", "version": snap.version, "file_in_sync": None, "last_error": None}


@router.post("/api/policy/validate")
async def validate_policy(body: YamlBody, rt: Any = Depends(get_rt), viewer: Identity = Depends(_member)) -> Any:
    store = _store(rt)
    if not body.selftest and hasattr(store, "build_candidate"):
        # keystroke validation: parse + schema + semantic checks only
        from aegis.core.policy_schema import ValidationReport
        from aegis.policy.diff import diff_docs

        cur = store.snapshot()
        cand, v, _ = store.build_candidate(body.yaml, version=cur.version + 1, source="validate", actor=None)
        if cand is None:
            report = ValidationReport(valid=False, errors=v.errors, warnings=v.warnings, selftest_passed=False)
        else:
            report = ValidationReport(valid=True, errors=[], warnings=v.warnings, selftest=[], selftest_passed=True,
                                      changes=diff_docs(cur.doc, cand.doc))
    else:
        report = await store.validate(body.yaml)
    if report.valid and report.changes:
        route = _route(rt, viewer, report.changes)
        if route is not None:
            report.required_role = route.required_role
    out = _dump(report)
    return out


@router.post("/api/policy/diff")
async def diff_policy(body: YamlBody, rt: Any = Depends(get_rt), viewer: Identity = Depends(_member)) -> Any:
    from aegis.policy.diff import unified_diff

    store = _store(rt)
    try:
        changes = store.diff(body.yaml)
    except ValueError as exc:
        errors = list(getattr(exc, "errors", None) or [ValidationIssue(message=str(exc))])
        return _invalid(errors)
    snap = store.snapshot()
    route = _route(rt, viewer, changes)
    return {
        "changes": [c.model_dump(mode="json") for c in changes],
        "unified": unified_diff(store.current_yaml(), body.yaml, f"policy v{snap.version}", "proposed"),
        "required_role": route.required_role if route is not None else None,
        "rule_id": route.rule_id if route is not None else None,
        "two_person": bool(route.two_person) if route is not None else False,
    }


@router.post("/api/policy/apply")
async def apply_policy(body: ApplyBody, rt: Any = Depends(get_rt), viewer: Identity = Depends(_member)) -> Any:
    store = _store(rt)
    res = await store.propose(viewer, yaml_text=body.yaml, reason=body.reason, base_version=body.base_version,
                              source="dashboard")
    return _apply_response(res)


@router.get("/api/policy/history")
async def policy_history(limit: int = Query(50, ge=1, le=1000), rt: Any = Depends(get_rt),
                         _v: Identity = Depends(_member)) -> Any:
    return {"items": [_dump(h) for h in _store(rt).history(limit)]}


@router.get("/api/policy/versions/{version}")
async def policy_version(version: int, rt: Any = Depends(get_rt), _v: Identity = Depends(_member)) -> Any:
    text = _store(rt).get_version_yaml(version)
    if text is None:
        return api_error(404, "not_found", f"policy version v{version} not found")
    return {"version": version, "yaml": text}


@router.post("/api/policy/rollback")
async def rollback_policy(body: RollbackBody, rt: Any = Depends(get_rt), viewer: Identity = Depends(_member)) -> Any:
    store = _store(rt)
    text = store.get_version_yaml(body.version)
    if text is None:
        return api_error(404, "not_found", f"policy version v{body.version} not found")
    reason = body.reason or f"rollback to v{body.version}"
    res = await store.propose(viewer, yaml_text=text, reason=reason, base_version=None, source="rollback",
                              apply_source="rollback")
    return _apply_response(res)


@router.post("/api/policy/reload")
async def reload_policy(rt: Any = Depends(get_rt), _v: Identity = Depends(_admin)) -> Any:
    store = _store(rt)
    fn = getattr(store, "reload_from_file", None)
    if not callable(fn):
        return api_error(501, "unavailable", "policy store does not support reload")
    return _apply_response(await fn(reason="manual reload"))


@router.get("/api/policy/selftest")
async def get_selftest(rt: Any = Depends(get_rt), _v: Identity = Depends(_member)) -> Any:
    fn = getattr(_store(rt), "last_selftest", None)
    run = fn() if callable(fn) else None
    if run is None:
        return api_error(404, "not_found", "no policy self-test has run yet")
    return _dump(run)


@router.post("/api/policy/selftest")
async def run_selftest(body: SelfTestBody | None = None, rt: Any = Depends(get_rt),
                       _v: Identity = Depends(_admin)) -> Any:
    body = body or SelfTestBody()
    fn = getattr(_store(rt), "run_selftest", None)
    if not callable(fn):
        return api_error(501, "unavailable", "policy self-test unavailable")
    which = body.which if body.which in ("all", "gate", "async") else "all"
    return _dump(await fn(which=which, profile=body.profile))


@router.get("/api/policy/effective")
async def effective(profile: str | None = Query(None), rt: Any = Depends(get_rt),
                    _v: Identity = Depends(_member)) -> Any:
    store = _store(rt)
    fn = getattr(store, "effective_controls", None)
    try:
        eff = fn(profile) if callable(fn) else store.snapshot().controls
    except Exception as exc:
        return api_error(400, "invalid_request", f"cannot compute effective controls: {exc}")
    return {"profile": profile or store.snapshot().doc.profile,
            "items": [c.model_dump(mode="json", by_alias=True) for c in eff.values()]}


# ---------------------------------------------------------------- controls & coverage
@router.get("/api/controls")
async def list_controls(rt: Any = Depends(get_rt), _v: Identity = Depends(_member)) -> Any:
    from aegis.policy.views import control_views

    store = _store(rt)
    return {"items": control_views(rt, store.snapshot(), getattr(store, "stats", None))}


@router.get("/api/coverage")
async def get_coverage(rt: Any = Depends(get_rt), _v: Identity = Depends(_member)) -> Any:
    from aegis.policy.views import coverage

    return coverage(rt, _store(rt).snapshot())


# ---------------------------------------------------------------- lifecycle
def _test_mode(rt: Any) -> bool:
    s = getattr(rt, "settings", None)
    return bool(getattr(s, "test_mode", False)) or os.environ.get("AEGIS_TEST_MODE") == "1"


async def on_startup(rt: Any) -> None:
    store = getattr(rt, "policy", None)
    if store is None or not hasattr(store, "versions"):  # Null policy store -> nothing to wire
        return
    from aegis.policy.governance import register_executors
    from aegis.policy.views import DecisionStats

    if not register_executors(store):
        log.info("approval executors not registered (approvals service unavailable)")
    if getattr(store, "stats", None) is None:
        store.stats = DecisionStats(rt)
        with contextlib.suppress(Exception):
            store.stats.start()
    if _test_mode(rt):
        return
    from aegis.policy.watcher import PolicyWatcher

    if getattr(store, "watcher", None) is None:
        store.watcher = PolicyWatcher(store)
    try:
        store.watcher.start()
    except Exception:
        log.exception("policy watcher failed to start (use POST /api/policy/reload)")
    task = asyncio.get_running_loop().create_task(store.startup_selftest(), name="aegis-policy-selftest")
    store._bg.add(task)
    task.add_done_callback(store._bg.discard)


async def on_shutdown(rt: Any) -> None:
    store = getattr(rt, "policy", None)
    if store is None:
        return
    for attr in ("watcher", "stats"):
        obj = getattr(store, attr, None)
        stop = getattr(obj, "stop", None)
        if callable(stop):
            with contextlib.suppress(Exception):
                await stop()


__all__ = ["ORDER", "on_shutdown", "on_startup", "router"]
