"""Ollama native proxy: `ANY /ollama/{path}` (`OLLAMA_HOST=http://127.0.0.1:8787/ollama`).

Owner: core-gateway (bundle B02).

* `POST api/chat`, `POST api/generate` -> governed model call (`ModelCall`, wire `ollama`).
* `api/pull|create|push|delete|copy` -> `model.admin` interaction (Addendum A-13: `tool_name =
  "ollama.<op>"`, `tool_args` = parsed body, `tool_args.modelfile` segment is a `document`,
  `trusted=False`; `meta.op`; destination local, `:cloud` -> remote) -> blocked: 403
  `{"error": "[Aegis] Blocked by <ID>: <reason>", "aegis": {...}}` (killed: 429), allowed: the
  upstream response is relayed as a stream; `pipeline.complete()` runs in `finally`.
* everything else (`api/tags|show|version|ps|embed|embeddings|blobs …`) -> plain local passthrough.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import anyio
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from aegis.core.timing import add_timing, server_timing_header
from aegis.core.types import Destination, Identity, Interaction, Outcome, TextSegment, Usage
from aegis.proxy import upstream
from aegis.proxy.adapters._common import dumps, is_claude_code, loads, string_leaves
from aegis.proxy.blocking import block_info, decision_headers
from aegis.proxy.flow import handle_model_request, runtime_of
from aegis.proxy.router import providers_for

log = logging.getLogger(__name__)

router = APIRouter(tags=["proxy"])

ADMIN_OPS = {"pull", "create", "push", "delete", "copy"}
_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _ollama_base(rt: Any) -> str:
    settings = getattr(rt, "settings", None)
    try:
        snap = rt.policy.snapshot()
    except Exception:
        snap = None
    cfg = providers_for(snap, settings).get("ollama")
    base = cfg.base_url if cfg is not None else (
        getattr(settings, "ollama_url", None) or "http://127.0.0.1:11434")
    base = base.rstrip("/")
    ollama = (getattr(settings, "ollama_url", None) or "").rstrip("/")
    if ollama and base.startswith("http://127.0.0.1:11434"):
        base = ollama + base[len("http://127.0.0.1:11434"):]
    return base[:-4] if base.endswith("/api") else base


def _err(status: int, message: str, inner: dict[str, Any] | None = None,
         headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": message, "aegis": inner or {"message": message}},
                        status_code=status, headers=headers)


@router.api_route("/ollama/{path:path}", methods=_METHODS)
async def ollama_proxy(path: str, request: Request) -> Response:
    path = path.strip("/")
    op = path[4:] if path.startswith("api/") else path
    if request.method == "POST" and op in {"chat", "generate"}:
        return await handle_model_request(request, wire="ollama", op=op)
    try:
        rt = runtime_of(request)
    except RuntimeError:
        return _err(503, "[Aegis] gateway runtime not started")
    if op in ADMIN_OPS and request.method in {"POST", "DELETE"}:
        return await _model_admin(rt, request, op)
    return await _passthrough(rt, request, path)


async def _passthrough(rt: Any, request: Request, path: str) -> Response:
    base = _ollama_base(rt)
    url = f"{base}/{path}"
    if request.url.query:
        url += "?" + request.url.query
    raw = await request.body()
    hdrs = upstream.outbound_headers(request.headers, wire="ollama", passthrough_auth=False,
                                     content_type=None)
    client = upstream.get_client()
    try:
        req = client.build_request(request.method, url, headers=hdrs, content=raw or None,
                                   timeout=httpx.Timeout(connect=5.0, read=300.0, write=60.0,
                                                         pool=10.0))
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        return _err(502, f"[Aegis] Ollama unreachable at {base}: {type(exc).__name__}",
                    {"type": "upstream_error", "message": "ollama unreachable"})
    return _relay(resp, None)


def _relay(resp: httpx.Response, on_done: Any) -> StreamingResponse:
    async def body() -> AsyncIterator[bytes]:
        status = resp.status_code
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        except httpx.HTTPError:
            status = 502
        finally:
            with anyio.CancelScope(shield=True):
                await resp.aclose()
                if on_done is not None:
                    try:
                        await on_done(status)
                    except Exception:
                        log.exception("ollama relay completion failed")

    headers = upstream.response_headers(resp.headers)
    media = headers.pop("content-type", None) or "application/json"
    return StreamingResponse(body(), status_code=resp.status_code, headers=headers,
                             media_type=media)


def _admin_interaction(op: str, method: str, body: dict[str, Any]) -> Interaction:
    model = body.get("model") or body.get("name") or body.get("source") or ""
    segs: list[TextSegment] = []
    for p, s in string_leaves(body, "tool_args"):
        if p == "tool_args.modelfile":
            segs.append(TextSegment(path=p, text=s, role="document", trusted=False))
        else:
            segs.append(TextSegment(path=p, text=s, role="tool_args"))
    dest = "remote" if str(model).endswith(":cloud") else "local"
    meta: dict[str, Any] = {"op": op, "wire": "ollama", "insecure": bool(body.get("insecure"))}
    if op == "copy":
        meta["from"] = body.get("source")
        meta["destination_model"] = body.get("destination")
    if op == "create":
        meta["from"] = body.get("from")
    if isinstance(model, str) and model.startswith("hf.co/"):
        meta["source"] = "huggingface"
    return Interaction(
        kind="model_call",
        surface="model.admin",
        direction="out",
        destination=Destination(name="ollama", dest_class=dest, provider="ollama"),
        model=str(model) or None,
        tool_name=f"ollama.{op}",
        tool_args=body,
        url=f"/api/{op}",
        http_method=method,
        segments=segs,
        raw=body,
        meta=meta,
    )


async def _model_admin(rt: Any, request: Request, op: str) -> Response:
    raw = await request.body()
    try:
        body = loads(raw) if raw else {}
    except Exception:
        body = None
    if not isinstance(body, dict):
        return _err(400, "[Aegis] request body must be a JSON object",
                    {"type": "invalid_request", "message": "body must be a JSON object"})
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        hints = {"client": "claude-code"} if is_claude_code(headers) else None
        identity = await rt.org.resolve_identity(headers, hints=hints)
    except Exception:
        identity = Identity()
    ctx = rt.pipeline.new_context(source="proxy", identity=identity, headers=headers)
    interaction = _admin_interaction(op, request.method, body)
    t = time.perf_counter()
    try:
        verdict = await rt.pipeline.evaluate(ctx, interaction)
    except Exception:
        log.exception("model.admin evaluate failed (fail-closed)")
        return _err(403, "[Aegis] Blocked by AEGIS-CORE: internal error (fail-closed)",
                    {"type": "policy_blocked", "message": "internal error (fail-closed)"})
    add_timing(ctx, "pipeline", (time.perf_counter() - t) * 1000.0)
    aegis_h = {
        "x-aegis-request-id": ctx.request_id,
        "x-aegis-decision-id": verdict.id,
        "x-aegis-decision": verdict.action,
        "x-aegis-policy-version": str(verdict.policy_version),
        "x-aegis-feed-serial": str(ctx.feed_serial) if ctx.feed_serial is not None else "none",
        "x-aegis-redactions": str(len(verdict.redactions)),
        **decision_headers([verdict]),
    }
    if verdict.action in ("block", "require_approval"):
        info = block_info(verdict, wire="ollama")
        status = info.status or 403
        with anyio.CancelScope(shield=True):
            try:
                await rt.pipeline.complete(ctx, interaction, verdict,
                                           Outcome(status_code=status, usage=Usage(requests=0)))
            except Exception:
                log.exception("complete failed")
        aegis_h["server-timing"] = server_timing_header(ctx)
        return _err(status, info.message, info.inner, {**aegis_h, **info.headers})
    base = _ollama_base(rt)
    hdrs = upstream.outbound_headers(headers, wire="ollama", passthrough_auth=False,
                                     mutations=verdict.mutations)
    client = upstream.get_client()
    t_up = time.perf_counter()
    try:
        req = client.build_request(request.method, f"{base}/api/{op}", headers=hdrs,
                                   content=dumps(body),
                                   timeout=httpx.Timeout(connect=5.0, read=3600.0, write=60.0,
                                                         pool=10.0))
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        with anyio.CancelScope(shield=True):
            await rt.pipeline.complete(ctx, interaction, verdict, Outcome(
                status_code=502, usage=Usage(requests=0), provider="ollama",
                error=type(exc).__name__))
        return _err(502, f"[Aegis] Ollama unreachable: {type(exc).__name__}",
                    {"type": "upstream_error", "message": "ollama unreachable"}, aegis_h)
    add_timing(ctx, "upstream", (time.perf_counter() - t_up) * 1000.0)

    async def done(status: int) -> None:
        await rt.pipeline.complete(ctx, interaction, verdict, Outcome(
            status_code=status, usage=Usage(requests=1), provider="ollama",
            upstream_ms=(time.perf_counter() - t_up) * 1000.0, model_used=interaction.model))

    out = _relay(resp, done)
    aegis_h["server-timing"] = server_timing_header(ctx)
    out.headers.update(aegis_h)
    return out
