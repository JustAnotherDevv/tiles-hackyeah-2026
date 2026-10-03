"""Anthropic Messages proxy: `POST /v1/messages` (`?beta=true` ok), `POST /v1/messages/count_tokens`.

Owner: core-gateway (bundle B02). Claude Code points `ANTHROPIC_BASE_URL` here; its OAuth
`Authorization` + `anthropic-*` headers pass through untouched (staging FINDINGS). The pipeline
runs `model.request` -> upstream -> `model.response` (see `aegis.proxy.flow.ModelCall`).

`count_tokens` (Addendum A-16): for remote providers the **dry-run-redacted** body is forwarded
(never the raw one); local / mock routes, blocked bodies and upstream errors answer with the
local estimate `{"input_tokens": n}`.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from aegis.core.types import Identity
from aegis.proxy import upstream
from aegis.proxy.adapters._common import dumps, is_claude_code, loads
from aegis.proxy.flow import (
    apply_body_mutations,
    get_adapter,
    handle_model_request,
    runtime_of,
)
from aegis.proxy.router import resolve_route

log = logging.getLogger(__name__)

router = APIRouter(tags=["proxy"])


@router.post("/v1/messages")
async def messages(request: Request) -> Response:
    """Anthropic Messages API (JSON + SSE)."""
    return await handle_model_request(request, wire="anthropic", op="messages")


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: Request) -> Response:
    """Token count: redacted forward for remote providers, local estimate otherwise."""
    raw = await request.body()
    try:
        body = loads(raw) if raw else None
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse({"type": "error", "error": {
            "type": "invalid_request_error", "message": "request body must be a JSON object"}},
            status_code=400)
    adapter = get_adapter("anthropic")
    headers = {k.lower(): v for k, v in request.headers.items()}
    interaction = adapter.parse_request(body, headers)
    estimate = {"input_tokens": int(interaction.est_input_tokens or 0)}
    try:
        rt = runtime_of(request)
    except RuntimeError:
        return JSONResponse(estimate)
    try:
        snap = rt.policy.snapshot()
    except Exception:
        snap = None
    route = resolve_route(body.get("model"), "anthropic", snap, getattr(rt, "settings", None))
    if route is None or route.dest_class == "local" or route.provider.startswith("mock"):
        return JSONResponse(estimate)
    try:
        hints = {"client": "claude-code"} if is_claude_code(headers) else None
        identity = await rt.org.resolve_identity(headers, hints=hints)
    except Exception:
        identity = Identity()
    try:
        ctx = rt.pipeline.new_context(source="proxy", identity=identity, headers=headers,
                                      dry_run=True)
        interaction.destination = route.destination
        interaction.raw = body
        verdict = await rt.pipeline.evaluate(ctx, interaction, dry_run=True)
        if verdict.action in ("block", "require_approval"):
            return JSONResponse(estimate)
        outbound = adapter.apply_segments(body, verdict.segments) if verdict.segments else body
        outbound = apply_body_mutations(outbound, verdict)
        hdrs = upstream.outbound_headers(headers, wire="anthropic",
                                         passthrough_auth=bool(route.cfg.passthrough_auth),
                                         api_key=route.api_key, mutations=verdict.mutations)
        resp = await upstream.get_client().post(
            route.url("count_tokens", request.url.query), headers=hdrs, content=dumps(outbound),
            timeout=httpx.Timeout(10.0))
        if resp.status_code == 200:
            return Response(content=resp.content, status_code=200,
                            media_type="application/json")
        log.debug("count_tokens upstream status=%s; using estimate", resp.status_code)
    except Exception:
        log.debug("count_tokens forward failed; using estimate", exc_info=True)
    return JSONResponse(estimate)
