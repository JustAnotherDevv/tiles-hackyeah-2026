"""POST /api/playground (PlaygroundRequest → PlaygroundResponse, CONTRACTS sections 5.4/5.5).

Identity = the dashboard viewer, or the seeded agent named in `agent_id` (impersonation for
demos). Session `ses_playground_<viewer>`, source `playground`. Always evaluated **non-dry** so
the run shows in the live feed and `/api/decisions/{id}` resolves (Addendum A-11).

- `send: true` on `model.request` / `prompt.user` with a remote/local destination runs the
  **same `ModelCall` flow** as the model proxies (B02 `aegis.proxy.flow`), OpenAI wire for the
  mock / Ollama providers: redaction → model → response evaluation → local rehydration.
- `send: false`, tool / MCP surfaces and `third_party` evaluate only, then
  `complete(Outcome(200, Usage(requests=0)))` releases reservations.
- Upstream unreachable → `response: null` + a `system` warning, never 5xx.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from aegis.api.routes.guard import GuardInteraction, build_interaction, data_plane_headers
from aegis.core.deps import client_ip, get_rt
from aegis.core.types import Destination, Identity, Outcome, RequestContext, Usage, Verdict

log = logging.getLogger(__name__)

router = APIRouter(tags=["playground"])

_MODEL_SURFACES = {"model.request", "prompt.user"}
_DEST_CLASSES = {"local", "remote", "third_party"}
#: destination alias -> (provider, wire, default model) ; model None => policy default_local
_TARGETS: dict[str, tuple[str, str, str | None]] = {
    "remote": ("mock-openai", "openai", "mock-echo"),
    "mock": ("mock-openai", "openai", "mock-echo"),
    "mock-openai": ("mock-openai", "openai", "mock-echo"),
    "mock-anthropic": ("mock-anthropic", "anthropic", "mock-echo"),
    "local": ("ollama-openai", "openai", None),
    "ollama": ("ollama-openai", "openai", None),
    "ollama-openai": ("ollama-openai", "openai", None),
    "anthropic": ("anthropic", "anthropic", "claude-haiku-4-5"),
    "openai": ("openai", "openai", "gpt-4o-mini"),
}


class PlaygroundRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    kind: str | None = None
    surface: str | None = None
    destination: str | None = None
    model: str | None = None
    agent_id: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    send: bool = True


def _dump(model: Any) -> Any:
    if model is None:
        return None
    if isinstance(model, list):
        return [m.model_dump(mode="json", by_alias=True) for m in model]
    return model.model_dump(mode="json", by_alias=True)


def _default_local(rt: Any, ctx: RequestContext) -> str:
    try:
        snap = ctx.policy or rt.policy.snapshot()
        return snap.doc.models.default_local or "aegis-judge"
    except Exception:
        return "aegis-judge"


def _target(rt: Any, ctx: RequestContext, req: PlaygroundRequest
            ) -> tuple[str, str | None, str | None, str | None]:
    """(dest_class, provider, wire, model) for the request's destination."""
    dest = (req.destination or "remote").strip()
    snap = ctx.policy
    providers = getattr(getattr(snap, "doc", None), "providers", {}) or {}
    if dest == "third_party":
        return "third_party", None, None, req.model
    if dest in _TARGETS:
        provider, wire, model = _TARGETS[dest]
        if provider in providers:
            wire = providers[provider].wire
        dest_class = ("local" if provider.startswith("ollama") else "remote")
        if provider in providers:
            dest_class = providers[provider].destination
        return dest_class, provider, wire, req.model or model or _default_local(rt, ctx)
    if dest in providers:
        p = providers[dest]
        return p.destination, dest, p.wire, req.model
    if dest in _DEST_CLASSES:
        return dest, None, None, req.model
    return "remote", None, None, req.model


async def _identity(rt: Any, request: Request, agent_id: str | None) -> tuple[Identity, str]:
    viewer = await rt.org.resolve_viewer(request.headers, dict(request.query_params))
    viewer_id = viewer.member_id or viewer.agent_id or "viewer"
    if agent_id:
        ident = await rt.org.resolve_identity({}, hints={"agent_id": agent_id})
        return ident, viewer_id
    return viewer, viewer_id


def _controls_timings(ctx: RequestContext) -> list[dict[str, Any]]:
    rows: dict[str, float] = {}
    for cid, ms in ctx.state.get("core.control_timings", []):
        rows[cid] = rows.get(cid, 0.0) + float(ms)
    return [{"control_id": cid, "ms": round(ms, 3)}
            for cid, ms in sorted(rows.items(), key=lambda kv: -kv[1])]


def _outbound_text(verdict: Verdict, roles: set[str] | None = None) -> str:
    if verdict.action not in ("allow", "log", "redact"):
        return ""
    segs = [s for s in verdict.segments if roles is None or s.role in roles] or verdict.segments
    return "\n".join(s.text for s in segs)


def _body_for(wire: str, model: str, text: str) -> dict[str, Any]:
    messages = [{"role": "user", "content": text}]
    if wire == "anthropic":
        return {"model": model, "max_tokens": 512, "messages": messages, "stream": False}
    if wire == "ollama":
        return {"model": model, "messages": messages, "stream": False}
    return {"model": model, "messages": messages, "stream": False, "max_tokens": 512}


async def _evaluate_only(rt: Any, ctx: RequestContext, req: PlaygroundRequest,
                         ident: Identity, dest_class: str, provider: str | None,
                         model: str | None) -> Verdict:
    surface = req.surface or "model.request"
    gi = GuardInteraction(
        kind=req.kind,
        surface=surface,
        model=model,
        tool_name=req.tool_name,
        tool_args=req.tool_args,
        text=req.text,
        meta={"source": "playground"},
        destination=Destination(name=provider or f"playground:{dest_class}",
                                dest_class=dest_class,  # type: ignore[arg-type]
                                provider=provider).model_dump(),
    )
    interaction = await build_interaction(rt, gi, ident, ctx.policy)
    if surface in _MODEL_SURFACES and interaction.segments:
        seg = interaction.segments[0]
        if seg.path == "text":
            interaction.segments[0] = seg.model_copy(update={"path": "messages[0].content"})
    verdict = await rt.pipeline.evaluate(ctx, interaction)
    if interaction.direction == "out":
        try:
            await rt.pipeline.complete(ctx, interaction, verdict,
                                       Outcome(status_code=200, usage=Usage(requests=0)))
        except Exception:
            log.exception("playground completion failed")
    return verdict


@router.post("/api/playground")
async def playground(body: PlaygroundRequest, request: Request) -> Any:
    from fastapi.responses import JSONResponse

    t0 = time.perf_counter()
    rt = await get_rt(request)
    ident, viewer_id = await _identity(rt, request, body.agent_id)
    ctx = rt.pipeline.new_context(
        source="playground",
        identity=ident,
        session_id=f"ses_playground_{viewer_id}",
        headers={k: v for k, v in request.headers.items()
                 if k.lower() not in {"x-aegis-session", "x-aegis-wait"}},
        wait_for_approval_s=0.0,
        client_ip=client_ip(request),
    )
    surface = body.surface or "model.request"
    dest_class, provider, wire, model = _target(rt, ctx, body)
    response: dict[str, Any] | None = None
    verdict: Verdict | None = None

    can_send = (body.send and surface in _MODEL_SURFACES and provider is not None
                and wire is not None and model is not None and dest_class != "third_party")
    if can_send:
        try:
            from aegis.proxy.flow import ModelCall  # B02; lazy so the playground degrades
        except Exception:
            ModelCall = None  # type: ignore[assignment]
            log.warning("proxy flow unavailable; playground evaluates only")
        if ModelCall is not None:
            try:
                call = ModelCall(rt, wire=wire or "openai", ctx=ctx, source="playground",
                                 provider=provider, identity=ident, stream_mode="buffered")
                result = await call.run(_body_for(wire or "openai", model or "mock-echo",
                                                  body.text))
                verdict = result.verdict
                if verdict is not None and not result.blocked and result.status < 400:
                    raw = result.response_raw_text or ""
                    local = result.response_local_text
                    route = result.route
                    response = {
                        "raw": raw,
                        "local": local if local is not None else raw,
                        "model": getattr(route, "model", None) or model,
                        "provider": getattr(route, "provider", None) or provider,
                    }
                elif verdict is not None and not result.blocked:
                    rt.system("warning",
                              f"playground: {provider} answered {result.status} "
                              f"({result.error or 'upstream error'})", component="playground")
            except Exception:
                log.exception("playground model call failed")
                rt.system("warning", f"playground: model call to {provider} failed",
                          component="playground")
    if verdict is None:
        verdict = await _evaluate_only(rt, ctx, body, ident, dest_class, provider, model)

    payload = {
        "decision_id": verdict.id,
        "verdict": _dump(verdict),
        "original": body.text,
        "outbound": _outbound_text(verdict, {"user", "tool_args", "tool_result"}),
        "redactions": _dump(verdict.redactions),
        "response": response,
        "timings": {
            "total_ms": round((time.perf_counter() - t0) * 1000, 3),
            "controls": _controls_timings(ctx),
        },
    }
    return JSONResponse(payload, headers=data_plane_headers(ctx, verdict))
