"""POST /v1/guard and POST /v1/guard/complete (CONTRACTS section 5.1).

Generic policy check for SDKs, scripted agents and the test-suite. The body describes one
interaction; the answer is **always 200** with the verdict:
`{verdict, decision_id, segments, text, approval}`.

Request-direction, non-dry, allowed verdicts are parked (TTL 600 s) so the caller can report the
real outcome with `/v1/guard/complete {decision_id, status_code, usage}` (settles budgets,
`on_complete` hooks run exactly once). Blocked / pending verdicts are completed immediately with
`Usage(requests=0)`; expired parked entries are completed with status 499.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from aegis.core.deps import client_ip, get_rt
from aegis.core.errors import AegisHTTPError, block_status, decision_headers
from aegis.core.paths import glob_match
from aegis.core.types import (
    Destination,
    Identity,
    Interaction,
    Outcome,
    RequestContext,
    TextSegment,
    Usage,
    Verdict,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["guard"])

PARK_TTL_S = 600.0
SWEEP_EVERY_S = 30.0
_PARK_KEY = "guard.parked"
_SWEEP_KEY = "guard.sweeper"

_SURFACE_KIND = {
    "prompt": "model_call",
    "model": "model_call",
    "tool": "tool_call",
    "artifact": "model_call",
    "mcp": "mcp",
    "egress": "egress",
    "a2a": "a2a",
    "config": "config_change",
}
_IN_SURFACES = {
    "model.response", "tool.output", "mcp.result", "mcp.list", "egress.response", "a2a.result",
    "artifact.file",
}
#: Addendum A-13: segments on these surfaces are untrusted everywhere
UNTRUSTED_SURFACES = {"tool.output", "mcp.result", "mcp.list", "egress.response", "a2a.result"}
_DEST_CLASSES = {"local", "remote", "third_party"}


# ------------------------------------------------------------------ request models
class GuardInteraction(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str | None = None
    surface: str = "model.request"
    direction: str | None = None
    destination: Any = None  # "local" | "remote" | "third_party" | Destination dict
    model: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    mcp_server: str | None = None
    mcp_method: str | None = None
    url: str | None = None
    http_method: str | None = None
    headers: dict[str, str] | None = None
    text: str | None = None
    segments: list[TextSegment] | None = None
    amount_usd: float | None = None
    resource: str | None = None
    action_type: str | None = None
    labels: dict[str, str] | None = None
    meta: dict[str, Any] | None = None
    est_input_tokens: int | None = None
    max_output_tokens: int | None = None


class GuardIdentity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: str | None = None
    member_id: str | None = None
    team_id: str | None = None


class GuardRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    interaction: GuardInteraction
    identity: GuardIdentity | None = None
    session_id: str | None = None
    wait_s: float | None = None
    approval_id: str | None = None
    dry_run: bool = False


class GuardComplete(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision_id: str
    status_code: int = 200
    usage: Usage = Field(default_factory=lambda: Usage())
    error: str | None = None
    upstream_ms: float | None = None
    provider: str | None = None
    model_used: str | None = None


# ------------------------------------------------------------------ helpers
def tool_arg_segments(args: Any, prefix: str = "tool_args") -> list[TextSegment]:
    """Every string leaf of `tool_args` → TextSegment(path="tool_args.<dotted>", role tool_args)."""
    out: list[TextSegment] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, str):
            if value:
                out.append(TextSegment(path=path, text=value, role="tool_args"))
        elif isinstance(value, dict):
            for k, v in value.items():
                key = str(k)
                sub = f"{path}.{key}" if key.replace("_", "").replace("-", "").isalnum() \
                    else f'{path}["{key}"]'
                walk(v, sub)
        elif isinstance(value, (list, tuple)):
            for n, v in enumerate(value):
                walk(v, f"{path}[{n}]")

    walk(args, prefix)
    return out


def _kind_for(surface: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    return _SURFACE_KIND.get(surface.split(".", 1)[0], "tool_call")


def _snapshot(rt: Any, ctx: RequestContext | None = None) -> Any:
    if ctx is not None and ctx.policy is not None:
        return ctx.policy
    try:
        return rt.policy.snapshot()
    except Exception:
        return None


async def _agent_local_only(rt: Any, ident: Identity) -> bool:
    if not ident.agent_id:
        return False
    try:
        agent = await rt.org.get_agent(ident.agent_id)
    except Exception:
        return False
    return bool(agent and agent.max_destination == "local")


def _route_destination(rt: Any, model: str | None, snap: Any) -> Destination | None:
    """Model-call destination via the proxy router (B02), if it is available."""
    if not model:
        return None
    try:
        from aegis.proxy import router as proxy_router  # B02 (optional)

        resolve = proxy_router.resolve_route
    except Exception:
        return None
    for wire in ("openai", "anthropic", "ollama"):
        try:
            route = resolve(model, wire, snap, rt.settings)
        except Exception:
            continue
        dest = getattr(route, "destination", None)
        if isinstance(dest, Destination):
            return dest
    return None


async def classify_destination(
    rt: Any, gi: GuardInteraction, kind: str, direction: str, ident: Identity, snap: Any
) -> Destination:
    """Destination per CONTRACTS section 3.4 (explicit wins)."""
    d = gi.destination
    if isinstance(d, dict):
        try:
            return Destination.model_validate(d)
        except Exception:
            pass
    if isinstance(d, str) and d:
        if d in _DEST_CLASSES:  # Addendum A-12
            return Destination(name=f"guard:{d}", dest_class=d)  # type: ignore[arg-type]
        providers = getattr(getattr(snap, "doc", None), "providers", {}) or {}
        if d in providers:
            p = providers[d]
            return Destination(name=d, dest_class=p.destination, provider=d, url=p.base_url)
    if kind == "config_change":
        return Destination(name="aegis", dest_class="local")
    if direction == "in" or gi.surface == "prompt.user":
        local = await _agent_local_only(rt, ident)
        return Destination(name="agent-context", dest_class="local" if local else "remote")
    doc = getattr(snap, "doc", None)
    if kind == "model_call":
        routed = _route_destination(rt, gi.model, snap)
        if routed is not None:
            return routed
        if gi.model and gi.model.endswith(":cloud"):
            return Destination(name="ollama", dest_class="remote", provider="ollama")
        return Destination(name=gi.model or "model", dest_class="remote")
    if kind == "egress" or gi.surface.startswith("egress."):
        host = None
        if gi.url:
            from urllib.parse import urlsplit

            host = urlsplit(gi.url).hostname
        internal = getattr(getattr(doc, "destinations", None), "internal_domains", []) or []
        is_local = bool(host) and any(glob_match(p, host) for p in internal)
        return Destination(name=f"egress:{host or 'unknown'}", host=host, url=gi.url,
                           dest_class="local" if is_local else "third_party")
    tool = gi.tool_name or ""
    server = gi.mcp_server or (tool.split(".", 1)[0] if kind == "mcp" and "." in tool else None)
    if kind == "mcp" or server:
        servers = getattr(getattr(doc, "mcp", None), "servers", {}) or {}
        cfg = servers.get(server or "")
        return Destination(name=f"mcp:{server or 'unknown'}",
                           dest_class=cfg.destination if cfg else "third_party",
                           url=getattr(cfg, "url", None) if cfg else None)
    dests = getattr(doc, "destinations", None)
    local_tools = getattr(dests, "local_tools", None) or []
    third = getattr(dests, "third_party_tools", None) or []
    if tool and any(glob_match(p, tool) for p in local_tools):
        return Destination(name=f"tool:{tool}", dest_class="local")
    if tool and any(glob_match(p, tool) for p in third):
        return Destination(name=f"tool:{tool}", dest_class="third_party")
    return Destination(name=f"tool:{tool or 'unknown'}", dest_class="third_party")


async def build_interaction(
    rt: Any, gi: GuardInteraction, ident: Identity, snap: Any
) -> Interaction:
    surface = gi.surface
    kind = _kind_for(surface, gi.kind)
    direction = gi.direction or ("in" if surface in _IN_SURFACES else "out")
    segments: list[TextSegment] = list(gi.segments or [])
    if not segments and gi.text and surface != "artifact.file":
        if surface == "mcp.list":
            segments.append(TextSegment(path="text", text=gi.text, role="tool_description",
                                        trusted=False))
        elif direction == "in":
            segments.append(TextSegment(path="text", text=gi.text, role="tool_result",
                                        trusted=False))
        else:
            segments.append(TextSegment(path="text", text=gi.text, role="user"))
    if gi.tool_args:
        have = {s.path for s in segments}
        segments.extend(s for s in tool_arg_segments(gi.tool_args) if s.path not in have)
    if surface in UNTRUSTED_SURFACES:
        segments = [s if not s.trusted else s.model_copy(update={"trusted": False})
                    for s in segments]
    meta = dict(gi.meta or {})
    raw: Any = None
    if surface == "artifact.file" and isinstance(meta.get("artifact_b64"), str):  # A-12
        import base64
        import binascii

        try:
            raw = base64.b64decode(meta["artifact_b64"], validate=False)
        except (binascii.Error, ValueError) as exc:
            raise AegisHTTPError(400, "invalid_request", f"invalid artifact_b64: {exc}") from exc
        if "sha256" not in meta:
            import hashlib

            meta["sha256"] = hashlib.sha256(raw).hexdigest()
    elif surface == "mcp.list" and meta.get("raw_result") is not None:
        raw = meta.get("raw_result")
    tool_name = gi.tool_name
    mcp_server = gi.mcp_server
    if tool_name and tool_name.startswith("mcp__"):  # Claude Code naming → <server>.<tool>
        parts = tool_name.split("__")
        if len(parts) >= 3:
            mcp_server = mcp_server or parts[1]
            tool_name = f"{parts[1]}.{'__'.join(parts[2:])}"
    destination = await classify_destination(rt, gi, kind, direction, ident, snap)
    data: dict[str, Any] = {
        "kind": kind,
        "surface": surface,
        "direction": direction,
        "destination": destination,
        "model": gi.model,
        "tool_name": tool_name,
        "tool_args": gi.tool_args,
        "mcp_server": mcp_server,
        "mcp_method": gi.mcp_method,
        "http_method": gi.http_method,
        "url": gi.url,
        "headers": {k.lower(): v for k, v in (gi.headers or {}).items()},
        "segments": segments,
        "action_type": gi.action_type,
        "amount_usd": gi.amount_usd,
        "resource": gi.resource,
        "labels": gi.labels or {},
        "est_input_tokens": gi.est_input_tokens,
        "max_output_tokens": gi.max_output_tokens,
        "meta": {**meta, "source": meta.get("source", "guard")},
    }
    if data["est_input_tokens"] is None and segments and kind == "model_call":
        data["est_input_tokens"] = _estimate_tokens(" ".join(s.text for s in segments), gi.model)
    try:
        interaction = Interaction.model_validate(data)
    except Exception as exc:
        raise AegisHTTPError(400, "invalid_request", f"invalid interaction: {exc}") from exc
    if raw is not None:
        interaction.raw = raw
    return interaction


def _estimate_tokens(text: str, model: str | None) -> int:
    try:
        from aegis.budgets.tokens import estimate_tokens  # budgets-ledger public surface

        return int(estimate_tokens(text, model))
    except Exception:
        return max(1, len(text) // 4)


def _blocked_outcome(verdict: Verdict, ctx: RequestContext) -> Outcome:
    stop = block_status(verdict.primary)
    status = stop[0] if stop else 403
    return Outcome(status_code=status, usage=Usage(requests=0), error=verdict.action)


def _server_timing(ctx: RequestContext) -> str:
    try:
        from aegis.core.timing import server_timing_header  # B02 (core/timing.py)

        return server_timing_header(ctx, upstream_ms=0.0)
    except Exception:
        total = (time.perf_counter() - ctx.t0) * 1000 if ctx.t0 else 0.0
        ctl = ctx.timings.get("ctl", 0.0)
        return f"aegis;dur={total:.2f}, ctl;dur={ctl:.2f}, upstream;dur=0.00"


def data_plane_headers(ctx: RequestContext, verdict: Verdict) -> dict[str, str]:
    """X-Aegis-* + Server-Timing + control headers (A-06) for a guard-style response."""
    headers = decision_headers(verdict)
    headers.update({
        "x-aegis-request-id": ctx.request_id,
        "x-aegis-decision-id": verdict.id,
        "x-aegis-decision": verdict.action,
        "x-aegis-policy-version": str(verdict.policy_version),
        "x-aegis-feed-serial": "" if verdict.feed_serial is None else str(verdict.feed_serial),
        "x-aegis-redactions": str(len(verdict.redactions)),
        "server-timing": _server_timing(ctx),
    })
    approval_id = (verdict.approval.id if verdict.approval else None) or (
        verdict.primary.approval_id if verdict.primary else None)
    if approval_id:
        headers["x-aegis-approval-id"] = approval_id
    return headers


def _parked(rt: Any) -> dict[str, tuple[float, RequestContext, Interaction, Verdict]]:
    extras = getattr(rt, "extras", None)
    if extras is None:
        extras = {}
        with contextlib.suppress(Exception):
            rt.extras = extras
    return extras.setdefault(_PARK_KEY, {})


async def sweep_parked(rt: Any, now: float | None = None) -> int:
    """Complete expired parked verdicts with status 499 (releases budget reservations)."""
    parked = _parked(rt)
    now = now if now is not None else time.monotonic()
    expired = [k for k, (exp, *_rest) in parked.items() if exp <= now]
    for key in expired:
        item = parked.pop(key, None)
        if item is None:
            continue
        _exp, ctx, inter, verdict = item
        try:
            await rt.pipeline.complete(ctx, inter, verdict,
                                       Outcome(status_code=499, usage=Usage(requests=0),
                                               error="guard completion expired"))
        except Exception:
            log.exception("guard parked completion failed decision=%s", key)
    return len(expired)


def _json(model: Any) -> Any:
    if model is None:
        return None
    if isinstance(model, list):
        return [m.model_dump(mode="json", by_alias=True) for m in model]
    return model.model_dump(mode="json", by_alias=True)


# ------------------------------------------------------------------ routes
@router.post("/v1/guard")
async def guard(body: GuardRequest, request: Request) -> JSONResponse:
    rt = await get_rt(request)
    settings = rt.settings
    await sweep_parked(rt)
    hints: dict[str, str] = {}
    if body.identity is not None and getattr(settings, "demo_mode", True):
        hints = {k: v for k, v in body.identity.model_dump().items() if v}
    identity = await rt.org.resolve_identity(request.headers, hints=hints or None)
    snap = _snapshot(rt)
    wait = body.wait_s  # explicit body value (incl. 0) wins (A-19)
    if wait is None and request.headers.get("x-aegis-wait"):
        try:
            wait = float(request.headers["x-aegis-wait"])
        except ValueError:
            wait = None
    if wait is None:
        try:
            wait = float(snap.doc.approvals.defaults.hold_s.get("guard", 0))
        except Exception:
            wait = 0.0
    ctx = rt.pipeline.new_context(
        source="guard",
        identity=identity,
        session_id=body.session_id,
        headers=({k: v for k, v in request.headers.items() if k.lower() != "x-aegis-wait"}
                 if body.wait_s is not None else request.headers),
        approval_token=body.approval_id,
        wait_for_approval_s=wait or 0.0,
        dry_run=body.dry_run,
        client_ip=client_ip(request),
    )
    interaction = await build_interaction(rt, body.interaction, identity, ctx.policy or snap)
    verdict: Verdict = await rt.pipeline.evaluate(ctx, interaction, dry_run=body.dry_run)

    if not body.dry_run and interaction.direction == "out":
        if verdict.action in ("allow", "log", "redact"):
            _parked(rt)[verdict.id] = (time.monotonic() + PARK_TTL_S, ctx, interaction, verdict)
        else:
            try:
                await rt.pipeline.complete(ctx, interaction, verdict,
                                           _blocked_outcome(verdict, ctx))
            except Exception:
                log.exception("guard completion failed decision=%s", verdict.id)

    allowed = verdict.action in ("allow", "log", "redact")
    text = "\n".join(s.text for s in verdict.segments) if allowed and verdict.segments else None
    return JSONResponse(
        {
            "verdict": _json(verdict),
            "decision_id": verdict.id,
            "segments": _json(verdict.segments),
            "text": text,
            "approval": _json(verdict.approval),
        },
        headers=data_plane_headers(ctx, verdict),
    )


@router.post("/v1/guard/complete")
async def guard_complete(body: GuardComplete, request: Request) -> dict[str, Any]:
    rt = await get_rt(request)
    item = _parked(rt).pop(body.decision_id, None)
    if item is None:
        raise AegisHTTPError(404, "not_found",
                             f"no pending guard decision {body.decision_id} (unknown or expired)",
                             decision_id=body.decision_id)
    _exp, ctx, interaction, verdict = item
    usage = body.usage
    if not usage.cost_usd:
        with contextlib.suppress(Exception):
            usage.cost_usd = float(rt.ledger.price(interaction.model, usage))
    outcome = Outcome(status_code=body.status_code, usage=usage, error=body.error,
                      upstream_ms=body.upstream_ms, provider=body.provider,
                      model_used=body.model_used or interaction.model)
    await rt.pipeline.complete(ctx, interaction, verdict, outcome)
    return {"ok": True}


# ------------------------------------------------------------------ lifecycle
async def _sweeper(rt: Any) -> None:
    while True:
        await asyncio.sleep(SWEEP_EVERY_S)
        try:
            await sweep_parked(rt)
        except Exception:
            log.exception("guard sweep failed")


async def on_startup(rt: Any) -> None:
    if getattr(rt.settings, "test_mode", False):
        return
    task = asyncio.create_task(_sweeper(rt), name="aegis-guard-sweeper")
    _parked(rt)  # ensure the map exists
    rt.extras[_SWEEP_KEY] = task


async def on_shutdown(rt: Any) -> None:
    task = getattr(rt, "extras", {}).pop(_SWEEP_KEY, None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    # release every parked reservation
    with contextlib.suppress(Exception):
        await sweep_parked(rt, now=float("inf"))
