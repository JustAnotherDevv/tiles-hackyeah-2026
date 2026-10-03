"""POST /egress - governed third-party HTTP egress proxy (metadata-egress, META-06).

Flow: validate -> identity + ctx (hold `approvals.defaults.hold_s.egress`) -> evaluate
`egress.request` -> blocked/pending: 403/402/429 envelope, upstream never contacted ->
allowed: apply segments + DLP-03 mutations, resolve AEGIS_HOST_MAP, send (no redirects) ->
evaluate `egress.response` (same ctx, A-02) -> 200 {status, headers, body, decision_id,
redactions, ...}. `rt.pipeline.complete()` is called exactly once per request.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from aegis.core.types import Outcome, Usage, Verdict
from aegis.egress import compat
from aegis.egress.forwarder import (
    EgressForwarder,
    EgressRequest,
    EgressValidationError,
    apply_response_verdict,
    apply_verdict,
    build_interaction,
    build_response_interaction,
    parse_body,
    shape_response,
)
from aegis.egress.hostmap import HostMap, UnresolvableHost

log = logging.getLogger(__name__)
router = APIRouter()

_STATE_KEY = "metadata-egress.forwarder"
_FALLBACK: dict[str, EgressForwarder] = {}
ALLOWED = ("allow", "log", "redact")


# ---------------------------------------------------------------- helpers
def get_forwarder(rt: Any) -> EgressForwarder:
    extras = getattr(rt, "extras", None)
    fwd = None
    if isinstance(extras, dict):
        fwd = extras.get(_STATE_KEY)
    if fwd is None:
        fwd = _FALLBACK.get("default")
    if fwd is None:
        fwd = EgressForwarder(HostMap.from_settings(getattr(rt, "settings", None)))
        _FALLBACK["default"] = fwd
        if isinstance(extras, dict):
            extras[_STATE_KEY] = fwd
    return fwd


def _err(status: int, type_: str, message: str, headers: dict[str, str] | None = None,
         **fields: Any) -> JSONResponse:
    try:
        from aegis.core.errors import api_error

        return api_error(status, type_, message, headers=headers, **fields)
    except Exception:  # pragma: no cover - core missing
        inner = {"type": type_, "message": message, **fields}
        return JSONResponse({"error": inner}, status_code=status, headers=headers)


def _verdict_error(verdict: Verdict) -> JSONResponse:
    try:
        from aegis.core.errors import verdict_error

        return verdict_error(verdict)
    except Exception:  # pragma: no cover - TODO(integration) core.errors missing
        p = verdict.primary
        etype = "approval_required" if verdict.action == "require_approval" else "policy_blocked"
        return _err(403, etype, f"[Aegis] Blocked by {p.control_id if p else 'policy'}: "
                    f"{p.reason if p else ''}", control_id=p.control_id if p else None,
                    decision_id=verdict.id)


def _server_timing(ctx: Any, upstream_ms: float) -> str:
    try:
        from aegis.core.timing import server_timing_header

        return server_timing_header(ctx, upstream_ms=upstream_ms)
    except Exception:
        total = (time.perf_counter() - ctx.t0) * 1000 if getattr(ctx, "t0", None) else 0.0
        ctl = (getattr(ctx, "timings", {}) or {}).get("ctl", 0.0)
        return (f"aegis;dur={max(0.0, total - upstream_ms):.2f}, ctl;dur={ctl:.2f}, "
                f"upstream;dur={upstream_ms:.2f}")


def _headers(ctx: Any, verdict: Verdict, response_verdict: Verdict | None = None,
             upstream_ms: float = 0.0) -> dict[str, str]:
    try:
        from aegis.core.errors import decision_headers

        h = decision_headers(verdict, response_verdict)
    except Exception:
        h = {}
    h.update({
        "x-aegis-request-id": ctx.request_id,
        "x-aegis-decision-id": verdict.id,
        "x-aegis-decision": verdict.action,
        "x-aegis-policy-version": str(verdict.policy_version),
        "x-aegis-feed-serial": "" if verdict.feed_serial is None else str(verdict.feed_serial),
        "x-aegis-redactions": str(len(verdict.redactions)
                                  + (len(response_verdict.redactions) if response_verdict else 0)),
        "server-timing": _server_timing(ctx, upstream_ms),
    })
    if response_verdict is not None:
        h["x-aegis-response-decision-id"] = response_verdict.id
    approval_id = (verdict.approval.id if verdict.approval else None) or (
        verdict.primary.approval_id if verdict.primary else None)
    if approval_id:
        h["x-aegis-approval-id"] = approval_id
    return h


def _blocked_status(verdict: Verdict) -> int:
    try:
        from aegis.core.errors import block_status

        stop = block_status(verdict.primary)
        if stop:
            return stop[0]
    except Exception:
        pass
    p = verdict.primary
    return int(p.http_status) if p is not None and p.http_status else 403


async def _complete(rt: Any, ctx: Any, inter: Any, verdict: Verdict, outcome: Outcome) -> None:
    try:
        await rt.pipeline.complete(ctx, inter, verdict, outcome)
    except Exception:
        log.exception("egress completion failed decision=%s", verdict.id)


def _metric(result: str, dest_class: str) -> None:
    compat.inc_metric("aegis_egress_requests_total", {"result": result, "dest_class": dest_class})


async def _response_dest(rt: Any, identity: Any) -> str:
    try:
        if identity.agent_id:
            agent = await rt.org.get_agent(identity.agent_id)
            if agent is not None and getattr(agent, "max_destination", None) == "local":
                return "local"
    except Exception:
        pass
    return "remote"


def _hold_s(snap: Any) -> float:
    try:
        return float(snap.doc.approvals.defaults.hold_s.get("egress", 15))
    except Exception:
        return 15.0


def _max_body(snap: Any) -> int:
    try:
        return int(snap.doc.defaults.max_body_bytes)
    except Exception:
        return 8_000_000


# ---------------------------------------------------------------- route
@router.post("/egress")
async def egress(request: Request) -> JSONResponse:
    from aegis.core.deps import get_rt

    rt = await get_rt(request)
    snap = None
    try:
        snap = rt.policy.snapshot()
    except Exception:
        snap = None
    try:
        data = await request.json()
    except Exception:
        return _err(400, "invalid_request", "request body must be JSON")
    try:
        req = EgressRequest.parse(data, max_body_bytes=_max_body(snap))
    except EgressValidationError as e:
        return _err(400, "invalid_request", str(e))

    identity = await rt.org.resolve_identity(request.headers)
    wait = req.wait_s
    if wait is None and not request.headers.get("x-aegis-wait"):
        wait = _hold_s(snap)
    client_ip = request.client.host if request.client else None
    ctx = rt.pipeline.new_context(
        source="egress", identity=identity,
        session_id=request.headers.get("x-aegis-session") or req.session_id,
        headers=request.headers, approval_token=request.headers.get("x-aegis-approval"),
        wait_for_approval_s=float(wait or 0.0), client_ip=client_ip)
    snap = getattr(ctx, "policy", None) or snap
    interaction, real_headers = build_interaction(req, snap=snap)
    dclass = interaction.destination.dest_class
    verdict: Verdict = await rt.pipeline.evaluate(ctx, interaction)

    # ---- blocked / pending: never contact the upstream
    if verdict.action not in ALLOWED:
        status = _blocked_status(verdict)
        await _complete(rt, ctx, interaction, verdict,
                        Outcome(status_code=status, usage=Usage(requests=0),
                                error=verdict.action))
        _metric("pending" if verdict.action == "require_approval" else "blocked", dclass)
        resp = _verdict_error(verdict)
        for k, v in _headers(ctx, verdict).items():
            resp.headers.setdefault(k, v)
        return resp

    fwd = get_forwarder(rt)
    out = apply_verdict(req, interaction, real_headers, verdict)
    try:
        target = fwd.resolve(out.url)
    except UnresolvableHost as e:
        await _complete(rt, ctx, interaction, verdict,
                        Outcome(status_code=502, usage=Usage(requests=0), error=str(e)))
        _metric("upstream_error", dclass)
        return _err(502, "upstream_error", str(e), headers=_headers(ctx, verdict),
                    decision_id=verdict.id)
    try:
        up = await fwd.send(out, target)
    except (httpx.HTTPError, OSError) as e:
        await _complete(rt, ctx, interaction, verdict,
                        Outcome(status_code=502, usage=Usage(requests=0),
                                error=f"upstream: {type(e).__name__}",
                                provider=f"egress:{target.host}"))
        _metric("upstream_error", dclass)
        return _err(502, "upstream_error", f"upstream unreachable ({type(e).__name__})",
                    headers=_headers(ctx, verdict), decision_id=verdict.id)

    # ---- response hop (same ctx, A-02)
    parsed = parse_body(up)
    resp_inter = build_response_interaction(interaction, parsed,
                                            dest_class=await _response_dest(rt, identity))
    rverdict: Verdict | None = None
    if resp_inter.segments:
        try:
            rverdict = await rt.pipeline.evaluate(ctx, resp_inter)
        except Exception:
            log.exception("egress response evaluation failed")
            rverdict = None
    outcome = Outcome(status_code=up.status, upstream_ms=up.upstream_ms,
                      provider=f"egress:{target.host}",
                      usage=Usage(requests=1, tool_calls=1, estimated=False),
                      response_verdict_id=rverdict.id if rverdict else None)
    if rverdict is not None and rverdict.action not in ALLOWED:
        outcome.status_code = 403
        outcome.error = f"response {rverdict.action}"
        await _complete(rt, ctx, interaction, verdict, outcome)
        _metric("blocked", dclass)
        resp = _verdict_error(rverdict)
        for k, v in _headers(ctx, verdict, rverdict, up.upstream_ms).items():
            resp.headers.setdefault(k, v)
        return resp
    body = apply_response_verdict(parsed, resp_inter, rverdict) if rverdict else parsed.value
    if parsed.kind in ("binary", "empty"):
        body = None
    try:
        import json as _json

        raw_txt = up.content[:65536].decode("utf-8", "replace") if parsed.kind != "binary" else None
        local_txt = (_json.dumps(body, ensure_ascii=False)[:65536] if parsed.kind == "json"
                     else (body[:65536] if isinstance(body, str) else None))
        rt.pipeline.attach_response(verdict.id, response_raw=raw_txt, response_local=local_txt)
    except Exception:
        log.debug("attach_response failed decision=%s", verdict.id)
    await _complete(rt, ctx, interaction, verdict, outcome)
    _metric("allowed", dclass)
    redactions = list(verdict.redactions) + (list(rverdict.redactions) if rverdict else [])
    payload = shape_response(up, body, parsed, decision_id=verdict.id, redactions=redactions,
                             response_decision_id=rverdict.id if rverdict else None)
    payload["applied"] = out.applied
    return JSONResponse(payload, headers=_headers(ctx, verdict, rverdict, up.upstream_ms))


# ---------------------------------------------------------------- lifecycle
async def on_startup(rt: Any) -> None:
    fwd = EgressForwarder(HostMap.from_settings(getattr(rt, "settings", None)))
    extras = getattr(rt, "extras", None)
    if isinstance(extras, dict):
        extras[_STATE_KEY] = fwd
    _FALLBACK["default"] = fwd
    compat.publish("system", {"level": "info", "component": "egress",
                              "message": f"egress proxy ready; host map {len(fwd.host_map)} hosts; "
                                         "pdf: stdlib"}, rt)


async def on_shutdown(rt: Any) -> None:
    fwd = _FALLBACK.pop("default", None)
    extras = getattr(rt, "extras", None)
    if isinstance(extras, dict):
        fwd = extras.pop(_STATE_KEY, None) or fwd
    if fwd is not None:
        await fwd.aclose()
