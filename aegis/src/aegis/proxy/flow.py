"""`ModelCall` — the model-call orchestrator shared by the Anthropic / OpenAI / Ollama proxies and
the playground (CONTRACTS section 3.5 "Response path for model calls", plan 01 section 2.9).

Owner: core-gateway (bundle B02).

    ingress -> identity -> ctx -> route -> adapter.parse_request -> pipeline.evaluate(model.request)
      block / approval  -> adapter.blocked_response (synthetic 200 or 402/429 wire error)
      allow / redact    -> apply segments + body/header/route mutations (raw bytes forwarded
                           byte-identical when nothing changed) -> upstream
    response            -> parse_response -> pipeline.evaluate(model.response)
                           block -> notice message; redact -> apply; DLP-08 -> rehydrate
                           assistant text only (never tool_use inputs, never thinking)
    always              -> pipeline.complete() exactly once (also on errors / client disconnect),
                           X-Aegis-* + Server-Timing headers.

Streaming uses `defaults.stream_mode`: `buffered` (default; Anthropic `message_start`/`ping`
forwarded immediately, keep-alives every 15 s, final stream re-synthesized after evaluation),
`passthrough` (raw relay, output controls skipped, usage still recorded), `holdback` (not
implemented -> WARNING once, buffered).

Playground / programmatic use:

    call = ModelCall(rt, wire="openai", ctx=ctx, source="playground", provider="mock-openai")
    result = await call.run(body)          # ModelCallResult (verdicts, outbound body, texts)
    response = result.to_response()        # FastAPI Response (routes)
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import anyio
import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from aegis.core.policy_schema import Defaults
from aegis.core.timing import add_timing, server_timing_header
from aegis.core.types import (
    ACTION_PRECEDENCE,
    Decision,
    Destination,
    Identity,
    Interaction,
    Outcome,
    RequestContext,
    TextSegment,
    Usage,
    Verdict,
    new_id,
)
from aegis.proxy import upstream
from aegis.proxy.adapters._common import (
    cow_remove,
    cow_set,
    dumps,
    estimate_tokens,
    header,
    is_claude_code,
    loads,
    validate_messages_body,
    validate_response_body,
)
from aegis.proxy.blocking import block_message, decision_headers
from aegis.proxy.router import DEST_RANK, Route, resolve_route
from aegis.proxy.streaming import (
    KEEPALIVE,
    AnthropicAccumulator,
    OllamaAccumulator,
    OpenAIAccumulator,
    anthropic_events,
    anthropic_ping,
    ollama_lines,
    openai_chunks,
    with_keepalive,
)

log = logging.getLogger(__name__)

__all__ = [
    "ModelCall",
    "ModelCallResult",
    "apply_body_mutations",
    "fresh_segments",
    "get_adapter",
    "handle_model_request",
    "runtime_of",
]

KEEPALIVE_S = 15.0
_warned: set[str] = set()


# ====================================================================== helpers
def runtime_of(request: Request) -> Any:
    """`app.state.rt`, else the module-global runtime (raises RuntimeError before startup)."""
    rt = getattr(request.app.state, "rt", None)
    if rt is not None:
        return rt
    from aegis.core.runtime import get_runtime

    return get_runtime()


_ADAPTERS: dict[str, Any] = {}


def get_adapter(wire: str) -> Any:
    """Discovered adapter for `wire` (built-ins as fallback)."""
    if not _ADAPTERS:
        try:
            from aegis.core.discovery import discover_adapters

            _ADAPTERS.update(discover_adapters())
        except Exception:  # pragma: no cover - discovery broken
            log.exception("adapter discovery failed; using built-ins")
        from aegis.proxy.adapters.anthropic import AnthropicAdapter
        from aegis.proxy.adapters.ollama import OllamaAdapter
        from aegis.proxy.adapters.openai import OpenAIAdapter

        _ADAPTERS.setdefault("anthropic", AnthropicAdapter())
        _ADAPTERS.setdefault("openai", OpenAIAdapter())
        _ADAPTERS.setdefault("ollama", OllamaAdapter())
    return _ADAPTERS[wire]


def _error_body(wire: str, status: int, etype: str, message: str, **fields: Any) -> dict[str, Any]:
    try:
        from aegis.core.errors import wire_body

        return wire_body(wire, etype, message, **fields)
    except Exception:  # pragma: no cover - B01 errors module missing
        return get_adapter(wire).error_body(etype, message, {"type": etype, "message": message})


def _warn_once(key: str, msg: str, *args: Any) -> None:
    if key not in _warned:
        _warned.add(key)
        log.warning(msg, *args)


def _segments_text(segs: list[TextSegment], roles: set[str] | None = None) -> str:
    return "\n".join(s.text for s in segs if roles is None or s.role in roles)


@dataclass
class ModelCallResult:
    """Outcome of one model call (routes turn it into a Response; the playground reads fields)."""

    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] | bytes | None = None
    stream: AsyncIterator[bytes] | None = None
    media_type: str = "application/json"
    verdict: Verdict | None = None
    response_verdict: Verdict | None = None
    route: Route | None = None
    request_interaction: Interaction | None = None
    outbound: dict[str, Any] | None = None
    response_body: dict[str, Any] | None = None
    response_raw_text: str | None = None
    response_local_text: str | None = None
    usage: Usage | None = None
    upstream_ms: float | None = None
    error: str | None = None
    blocked: bool = False

    def to_response(self) -> Response:
        if self.stream is not None:
            return StreamingResponse(self.stream, status_code=self.status,
                                     headers=self.headers, media_type=self.media_type)
        if isinstance(self.body, (bytes, bytearray)):
            return Response(content=bytes(self.body), status_code=self.status,
                            headers=self.headers, media_type=self.media_type)
        return Response(content=dumps(self.body if self.body is not None else {}),
                        status_code=self.status, headers=self.headers,
                        media_type="application/json")


# ====================================================================== ModelCall
class ModelCall:
    """One model call through the gateway. Create per request; `await run(body, raw)`."""

    def __init__(
        self,
        rt: Any,
        *,
        wire: str,
        op: str | None = None,
        query: str = "",
        source: str = "proxy",
        client_headers: Mapping[str, str] | None = None,
        ctx: RequestContext | None = None,
        identity: Identity | None = None,
        identity_hints: Mapping[str, str] | None = None,
        provider: str | None = None,
        client_ip: str | None = None,
        stream_mode: str | None = None,
    ) -> None:
        self.rt = rt
        self.wire = wire
        self.adapter = get_adapter(wire)
        self.op = op
        self.query = query
        self.source = source
        self.headers: dict[str, str] = {str(k).lower(): str(v) for k, v in
                                        (client_headers or {}).items()}
        self.ctx = ctx
        self.identity = identity
        self.identity_hints = dict(identity_hints or {})
        self.provider = provider
        self.client_ip = client_ip
        self.stream_mode = stream_mode
        self.claude_code = is_claude_code(self.headers)
        self.downgraded_from: str | None = None
        # R10: the evaluated-but-not-completed request hop; `run` completes it on any escape
        self._open: tuple[RequestContext, Interaction, Verdict] | None = None

    # ------------------------------------------------------------------ context
    async def _make_ctx(self, body: dict[str, Any]) -> RequestContext:
        rt = self.rt
        identity = self.identity
        if identity is None:
            hints = dict(self.identity_hints)
            if self.claude_code:
                hints.setdefault("client", "claude-code")
            try:
                identity = await rt.org.resolve_identity(self.headers, hints=hints or None)
            except Exception:
                log.exception("resolve_identity failed; anonymous agent")
                identity = Identity()
        session_id = (header(self.headers, "x-aegis-session")
                      or header(self.headers, "x-claude-code-session-id"))
        body_hint = None
        try:
            from aegis.core.sessions import session_hint_from_body

            body_hint = session_hint_from_body(body)
        except Exception:
            body_hint = None
        kwargs: dict[str, Any] = {"source": self.source, "identity": identity,
                                  "session_id": session_id or body_hint, "headers": self.headers}
        try:
            ctx = rt.pipeline.new_context(**kwargs, client_ip=self.client_ip,
                                          body_session_hint=body_hint)
        except TypeError:  # protocol-only pipelines (no extra kwargs)
            ctx = rt.pipeline.new_context(**kwargs)
        if self.claude_code:
            ctx.state.setdefault("core.client", "claude-code")
        return ctx

    def _snapshot(self, ctx: RequestContext) -> Any:
        snap = ctx.policy
        if snap is None:
            try:
                snap = self.rt.policy.snapshot()
            except Exception:
                log.exception("policy snapshot failed")
                snap = None
        return snap

    @staticmethod
    def _defaults(snap: Any) -> Defaults:
        doc = getattr(snap, "doc", None)
        d = getattr(doc, "defaults", None)
        return d if isinstance(d, Defaults) else Defaults()

    # ------------------------------------------------------------------ pipeline wrappers
    async def _evaluate(self, ctx: RequestContext, i: Interaction) -> Verdict:
        t = time.perf_counter()
        before = ctx.timings.get("ctl")
        try:
            v = await self.rt.pipeline.evaluate(ctx, i)
        except Exception:
            log.exception("pipeline evaluate failed (fail-closed) surface=%s", i.surface)
            if not i.id:
                i.id = new_id("int")
            v = Verdict(
                id=new_id("dec"), request_id=ctx.request_id, interaction_id=i.id,
                action="block",
                primary=Decision(action="block", control_id="AEGIS-CORE",
                                 reason="internal error (fail-closed)", degraded=True,
                                 severity="high"),
                policy_version=ctx.policy_version, feed_serial=ctx.feed_serial, degraded=True,
            )
        if ctx.timings.get("ctl") == before:  # pipeline did not record control time
            add_timing(ctx, "ctl", v.latency_ms)
            for d in v.decisions:
                add_timing(ctx, f"ctl.{d.control_id}", d.latency_ms)
        add_timing(ctx, "pipeline", (time.perf_counter() - t) * 1000.0)
        if i.surface == "model.request":
            self._open = (ctx, i, v)
        return v

    async def _complete(self, ctx: RequestContext, i: Interaction, v: Verdict,
                        outcome: Outcome) -> None:
        if self._open is not None and self._open[1] is i:
            self._open = None
        with anyio.CancelScope(shield=True):
            try:
                await self.rt.pipeline.complete(ctx, i, v, outcome)
            except Exception:
                log.exception("pipeline complete failed")

    def _price(self, model: str | None, usage: Usage) -> float:
        try:
            return float(self.rt.ledger.price(model, usage) or 0.0)
        except Exception:
            log.debug("ledger price failed", exc_info=True)
            return 0.0

    async def _response_destination(self, ctx: RequestContext, route: Route) -> Destination:
        """CONTRACTS 3.4: an `in` hop's destination = where the content goes next (the agent's
        model context): remote unless the route is local or the agent is local-only."""
        dest = "local" if route.dest_class == "local" else "remote"
        agent_id = ctx.identity.agent_id
        if dest != "local" and agent_id:
            cached = ctx.state.get("core.agent_max_destination", "?")
            if cached == "?":
                cached = None
                try:
                    agent = await self.rt.org.get_agent(agent_id)
                    cached = getattr(agent, "max_destination", None)
                except Exception:
                    log.debug("get_agent failed", exc_info=True)
                ctx.state["core.agent_max_destination"] = cached
            if cached == "local":
                dest = "local"
        return Destination(name=route.provider, dest_class=dest, provider=route.provider,
                           host=route.destination.host, url=route.destination.url)

    # ------------------------------------------------------------------ headers
    def _aegis_headers(
        self,
        ctx: RequestContext,
        verdict: Verdict | None,
        *,
        rv: Verdict | None = None,
        upstream_ms: float | None = None,
    ) -> dict[str, str]:
        h: dict[str, str] = {"x-aegis-request-id": ctx.request_id}
        if verdict is not None:
            action = verdict.action
            if rv is not None and ACTION_PRECEDENCE.get(rv.action, 0) > ACTION_PRECEDENCE.get(
                    action, 0):
                action = rv.action
            h["x-aegis-decision-id"] = verdict.id
            h["x-aegis-decision"] = action
            h["x-aegis-policy-version"] = str(verdict.policy_version or ctx.policy_version)
            n = len(verdict.redactions) + (len(rv.redactions) if rv is not None else 0)
            h["x-aegis-redactions"] = str(n)
            apr = verdict.approval.id if verdict.approval else (
                verdict.primary.approval_id if verdict.primary else None)
            if apr:
                h["x-aegis-approval-id"] = apr
        else:
            h["x-aegis-policy-version"] = str(ctx.policy_version)
            h["x-aegis-redactions"] = "0"
        h["x-aegis-feed-serial"] = str(ctx.feed_serial) if ctx.feed_serial is not None else "none"
        if rv is not None:
            h["x-aegis-response-decision-id"] = rv.id
        if self.downgraded_from:
            h["x-aegis-downgraded-from"] = self.downgraded_from
        # A-06: control-requested headers (x-aegis-*, retry-after, x-should-retry)
        for k, v in decision_headers([verdict, rv]).items():
            h.setdefault(k, v)
        # plan 01 section 4.3 #1: BUD-01 may also leave the remaining budget in ctx.state
        bud = ctx.state.get("bud.remaining")
        if bud and "x-aegis-budget-remaining" not in h:
            h["x-aegis-budget-remaining"] = str(bud)
        h["server-timing"] = server_timing_header(ctx, upstream_ms=upstream_ms)
        return {k: v.encode("latin-1", "replace").decode("latin-1") for k, v in h.items()}

    def _error(self, ctx: RequestContext | None, status: int, etype: str, message: str,
               verdict: Verdict | None = None, **fields: Any) -> ModelCallResult:
        body = _error_body(self.wire, status, etype, message,
                           decision_id=verdict.id if verdict else None, **fields)
        headers = self._aegis_headers(ctx, verdict) if ctx is not None else {}
        return ModelCallResult(status=status, headers=headers, body=body, verdict=verdict,
                               error=message)

    # ------------------------------------------------------------------ main entry
    async def run(self, body: dict[str, Any], raw: bytes | None = None) -> ModelCallResult:
        """Run one call. Never raises for bad input / bad upstream data (R10): a type-confused
        body -> 400, an unexpected error after evaluation -> 500 envelope, and in every case
        `pipeline.complete()` is called for an evaluated hop (budget reservations / slots)."""
        try:
            return await self._run(body, raw)
        except Exception as exc:
            log.exception("model call failed wire=%s", self.wire)
            verdict = None
            if self._open is not None:
                ctx, i, verdict = self._open
                await self._complete(ctx, i, verdict, Outcome(
                    status_code=500, usage=Usage(requests=0),
                    error=f"internal error: {type(exc).__name__}"))
            return self._error(self.ctx, 500, "internal_error",
                               "[Aegis] internal error in the model proxy", verdict)

    async def _run(self, body: dict[str, Any], raw: bytes | None = None) -> ModelCallResult:
        ctx = self.ctx or await self._make_ctx(body)
        self.ctx = ctx
        snap = self._snapshot(ctx)
        defaults = self._defaults(snap)
        settings = getattr(self.rt, "settings", None)
        model = body.get("model")
        default_stream = self.wire == "ollama"
        stream = bool(body.get("stream", default_stream))
        if not isinstance(model, str) or not model:
            return self._error(ctx, 400, "invalid_request", "request body has no `model`")
        route = resolve_route(model, self.wire, snap, settings, provider=self.provider)
        if route is None:
            return self._error(ctx, 400, "invalid_request",
                               f"no provider route for model {model} on the {self.wire} API")
        op = self.op or ("chat" if self.wire != "ollama"
                         else get_adapter("ollama").op_of(body))
        self.op = op

        t_parse = time.perf_counter()
        problem = validate_messages_body(body, self.wire)
        if problem is None:
            try:
                req_i = self.adapter.parse_request(body, self.headers)
            except Exception as exc:  # unexpected shape -> never forward un-inspected
                log.info("parse_request rejected body wire=%s error=%s", self.wire,
                         type(exc).__name__)
                problem = "request body has an unsupported structure"
        if problem is not None:
            return self._error(ctx, 400, "invalid_request", f"[Aegis] {problem}")
        if route.redact_system:
            for s in req_i.segments:
                if s.role == "system":
                    s.redactable = True
        req_i.destination = route.destination
        req_i.raw = body
        try:
            req_i.headers = upstream.masked_headers(upstream.outbound_headers(
                self.headers, wire=self.wire,
                passthrough_auth=bool(route.cfg.passthrough_auth), api_key=route.api_key))
        except Exception:  # pragma: no cover - defensive
            log.debug("outbound header preview failed", exc_info=True)
        req_i.meta.update({"provider": route.provider, "body_bytes": len(raw) if raw else None,
                           "source": self.source})
        if self.wire == "ollama":
            req_i.meta["op"] = op
        try:
            req_i.meta["fresh_segments"] = fresh_segments(ctx.session_id, req_i.segments)
        except Exception:  # pragma: no cover - hint only
            log.debug("fresh_segments failed", exc_info=True)
        add_timing(ctx, "parse", (time.perf_counter() - t_parse) * 1000.0)

        verdict = await self._evaluate(ctx, req_i)
        if verdict.action in ("block", "require_approval"):
            return await self._blocked(ctx, req_i, verdict, model, stream, defaults, route)

        # ---------------------------------------------------------------- outbound body
        outbound = self.adapter.apply_segments(body, verdict.segments) if verdict.segments \
            else body
        outbound = self._apply_body_mutations(outbound, verdict)
        new_route = self._route_mutation(verdict, model, snap, settings, route)
        if new_route is not None:
            if DEST_RANK.get(new_route.dest_class, 1) > DEST_RANK.get(route.dest_class, 1):
                # more remote than what was evaluated -> evaluate again (never under-redact)
                await self._complete(ctx, req_i, verdict,
                                     Outcome(status_code=200, usage=Usage(requests=0),
                                             error="superseded by route mutation"))
                req_i = self.adapter.parse_request(body, self.headers)
                req_i.destination = new_route.destination
                req_i.raw = body
                req_i.meta.update({"provider": new_route.provider, "rerouted_from": model})
                verdict = await self._evaluate(ctx, req_i)
                if verdict.action in ("block", "require_approval"):
                    return await self._blocked(ctx, req_i, verdict, model, stream, defaults,
                                               new_route)
                outbound = self.adapter.apply_segments(body, verdict.segments) \
                    if verdict.segments else body
                outbound = self._apply_body_mutations(outbound, verdict)
            if new_route.model != model:
                outbound = cow_set(outbound, "model", new_route.model)
                self.downgraded_from = model
            route = new_route

        include_usage = False
        if self.wire == "openai" and stream:
            from aegis.proxy.adapters.openai import prepare_openai_request

            outbound, include_usage = prepare_openai_request(outbound)
        content = raw if (outbound is body and raw is not None) else dumps(outbound)
        self._attach_preview(verdict, outbound, route)

        mode = self.stream_mode or defaults.stream_mode
        if mode == "holdback":
            _warn_once("holdback", "stream_mode=holdback not implemented; using buffered")
            mode = "buffered"

        # ---------------------------------------------------------------- upstream
        hdrs = upstream.outbound_headers(
            self.headers, wire=self.wire, passthrough_auth=bool(route.cfg.passthrough_auth),
            api_key=route.api_key, mutations=verdict.mutations,
        )
        url = route.url(op, self.query)
        client = upstream.get_client()
        timeout = httpx.Timeout(connect=10.0, read=route.timeout_s, write=60.0, pool=10.0)
        t_up = time.perf_counter()
        try:
            req = client.build_request("POST", url, headers=hdrs, content=content,
                                       timeout=timeout)
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as exc:
            ms = (time.perf_counter() - t_up) * 1000.0
            add_timing(ctx, "upstream", ms)
            log.warning("upstream unreachable provider=%s url=%s error=%s", route.provider,
                        url, type(exc).__name__)
            await self._complete(ctx, req_i, verdict, Outcome(
                status_code=502, usage=Usage(requests=0), upstream_ms=ms,
                provider=route.provider, model_used=route.model, error=type(exc).__name__))
            res = self._error(ctx, 502, "upstream_error",
                              f"[Aegis] upstream {route.provider} unreachable: "
                              f"{type(exc).__name__}", verdict)
            res.route, res.request_interaction, res.outbound = route, req_i, outbound
            return res
        ttfb = (time.perf_counter() - t_up) * 1000.0

        base = ModelCallResult(status=resp.status_code, verdict=verdict, route=route,
                               request_interaction=req_i, outbound=outbound)

        if resp.status_code >= 300:
            data = await resp.aread()
            await resp.aclose()
            ms = (time.perf_counter() - t_up) * 1000.0
            add_timing(ctx, "upstream", ms)
            await self._complete(ctx, req_i, verdict, Outcome(
                status_code=resp.status_code, usage=Usage(), upstream_ms=ms,
                provider=route.provider, model_used=route.model,
                error=f"upstream status {resp.status_code}"))
            if not _is_json_object(data):
                # non-JSON upstream error (HTML 500, redirect, proxy page) -> wire envelope (§5.3)
                status = resp.status_code if 400 <= resp.status_code < 500 else 502
                res = self._error(ctx, status, "upstream_error",
                                  f"[Aegis] upstream {route.provider} returned HTTP "
                                  f"{resp.status_code}", verdict,
                                  upstream_status=resp.status_code)
                ra = resp.headers.get("retry-after")
                if ra:
                    res.headers["retry-after"] = ra
                res.route, res.request_interaction, res.outbound = route, req_i, outbound
                res.upstream_ms = ms
                return res
            base.headers = {**upstream.response_headers(resp.headers),
                            **self._aegis_headers(ctx, verdict, upstream_ms=ms)}
            base.body = data
            base.media_type = resp.headers.get("content-type", "application/json")
            base.upstream_ms = ms
            base.error = f"upstream status {resp.status_code}"
            return base

        if not stream:
            try:
                data = await resp.aread()
            except httpx.HTTPError as exc:
                data = b""
                log.warning("upstream read failed provider=%s error=%s", route.provider,
                            type(exc).__name__)
            finally:
                await resp.aclose()
            ms = (time.perf_counter() - t_up) * 1000.0
            add_timing(ctx, "upstream", ms)
            try:
                resp_obj = loads(data)
                if not isinstance(resp_obj, dict):
                    raise ValueError("not an object")
            except Exception:
                await self._complete(ctx, req_i, verdict, Outcome(
                    status_code=502, usage=Usage(), upstream_ms=ms, provider=route.provider,
                    model_used=route.model, error="unparseable upstream response"))
                return self._error(ctx, 502, "upstream_error",
                                   "[Aegis] unparseable upstream response", verdict)
            try:
                final, rv, outcome = await self._process_response(ctx, req_i, verdict, resp_obj,
                                                                  route, ms, defaults)
            except Exception as exc:  # wrong-typed upstream JSON -> 502, never a 500
                log.warning("invalid upstream response provider=%s error=%s", route.provider,
                            type(exc).__name__, exc_info=True)
                await self._complete(ctx, req_i, verdict, Outcome(
                    status_code=502, usage=Usage(), upstream_ms=ms, provider=route.provider,
                    model_used=route.model, error="invalid upstream response"))
                return self._error(ctx, 502, "upstream_error",
                                   "[Aegis] invalid upstream response", verdict)
            await self._complete(ctx, req_i, verdict, outcome)
            base.headers = {**upstream.response_headers(resp.headers),
                            **self._aegis_headers(ctx, verdict, rv=rv, upstream_ms=ms)}
            base.body = final
            base.response_verdict = rv
            base.response_body = final
            base.usage = outcome.usage
            base.upstream_ms = ms
            base.blocked = rv.action in ("block", "require_approval")
            self._fill_texts(base, resp_obj, final)
            return base

        # ---------------------------------------------------------------- streaming
        add_timing(ctx, "upstream", ttfb)
        up_headers = upstream.response_headers(resp.headers)
        if mode == "passthrough":
            gen = self._passthrough(resp, ctx, req_i, verdict, route, t_up)
        elif self.wire == "anthropic":
            gen = self._anthropic_buffered(resp, ctx, req_i, verdict, route, t_up, defaults,
                                           base)
        elif self.wire == "openai":
            gen = self._openai_buffered(resp, ctx, req_i, verdict, route, t_up, defaults,
                                        include_usage, base)
        else:
            gen = self._ollama_buffered(resp, ctx, req_i, verdict, route, t_up, defaults, base)
        media = resp.headers.get("content-type") or (
            "application/x-ndjson" if self.wire == "ollama" else "text/event-stream")
        base.headers = {**up_headers, "cache-control": "no-cache", "x-accel-buffering": "no",
                        **self._aegis_headers(ctx, verdict, upstream_ms=ttfb)}
        base.headers.pop("content-type", None)
        base.media_type = media
        base.stream = gen
        base.upstream_ms = ttfb
        return base

    # ------------------------------------------------------------------ pieces
    async def _blocked(self, ctx: RequestContext, req_i: Interaction, verdict: Verdict,
                       model: str, stream: bool, defaults: Defaults,
                       route: Route | None) -> ModelCallResult:
        kwargs: dict[str, Any] = {}
        if self.wire == "openai":
            so = req_i.meta.get("include_usage_requested")
            kwargs["include_usage"] = bool(so)
        if self.wire == "ollama":
            kwargs["op"] = self.op or "chat"
        status, body, hdrs = self.adapter.blocked_response(
            verdict, model=model, stream=stream, style=defaults.block_response, **kwargs)
        await self._complete(ctx, req_i, verdict, Outcome(
            status_code=status, usage=Usage(requests=0),
            provider=route.provider if route else None, error=f"aegis {verdict.action}"))
        headers = {**self._aegis_headers(ctx, verdict), **{k.lower(): v for k, v in hdrs.items()}}
        media = headers.pop("content-type", None) or "application/json"
        res = ModelCallResult(status=status, headers=headers, body=body, media_type=media,
                              verdict=verdict, route=route, request_interaction=req_i,
                              blocked=True)
        res.response_local_text = block_message(verdict)
        return res

    def _apply_body_mutations(self, outbound: dict[str, Any], verdict: Verdict) -> dict[str, Any]:
        return apply_body_mutations(outbound, verdict)

    def _route_mutation(self, verdict: Verdict, model: str, snap: Any, settings: Any,
                        route: Route) -> Route | None:
        new_model: str | None = None
        new_provider: str | None = None
        for m in verdict.mutations:
            if m.target != "route" or m.op != "set" or not m.value:
                continue
            if m.path == "model":
                new_model = str(m.value)
            elif m.path == "provider":
                new_provider = str(m.value)
        if not new_model and not new_provider:
            return None
        target = new_model or model
        found = resolve_route(target, self.wire, snap, settings, provider=new_provider)
        if found is None:
            log.warning("route mutation unresolvable model=%s provider=%s (kept %s)",
                        target, new_provider, route.provider)
            return None
        return found

    def _attach_preview(self, verdict: Verdict, outbound: dict[str, Any], route: Route) -> None:
        fn = getattr(self.rt.pipeline, "attach_request_preview", None)
        if not callable(fn):
            return
        try:
            msgs = outbound.get("messages") or []
            tail = []
            for m in msgs[-2:]:
                c = m.get("content") if isinstance(m, dict) else None
                text = c if isinstance(c, str) else dumps(c).decode("utf-8") if c else ""
                tail.append({"role": m.get("role") if isinstance(m, dict) else None,
                             "content": text[:2000]})
            preview = {
                "provider": route.provider, "url": route.url_base, "model": outbound.get("model"),
                "max_tokens": outbound.get("max_tokens", outbound.get("max_completion_tokens")),
                "stream": outbound.get("stream"), "n_messages": len(msgs), "messages_tail": tail,
            }
            if "prompt" in outbound:
                preview["prompt"] = str(outbound.get("prompt"))[:2000]
            fn(verdict.id, preview)
        except Exception:
            log.debug("attach_request_preview failed", exc_info=True)

    def _should_rehydrate(self, ctx: RequestContext, rv: Verdict,
                          defaults: Defaults) -> tuple[bool, set[str]]:
        if not defaults.rehydrate_responses:
            return False, set()
        for d in rv.decisions:
            meta = d.meta or {}
            if d.mode == "enforce" and meta.get("rehydrate"):
                roles = meta.get("roles") or ["assistant"]
                # A-40: never rehydrate tool_use inputs / tool_calls arguments
                return True, {str(r) for r in roles} - {"tool_args"}
        return False, set()

    async def _process_response(
        self, ctx: RequestContext, req_i: Interaction, verdict: Verdict,
        resp_obj: dict[str, Any], route: Route, upstream_ms: float, defaults: Defaults,
    ) -> tuple[dict[str, Any], Verdict, Outcome]:
        problem = validate_response_body(resp_obj, self.wire)
        if problem is not None:  # callers turn this into 502 upstream_error (R10)
            raise ValueError(f"invalid upstream response: {problem}")
        usage = self.adapter.parse_usage(resp_obj)
        resp_i = self.adapter.parse_response(resp_obj)
        if usage.input_tokens == 0 and usage.output_tokens == 0:
            usage = Usage(input_tokens=req_i.est_input_tokens or 0,
                          output_tokens=estimate_tokens(resp_i.text(), route.model),
                          compute_s=usage.compute_s, requests=1, estimated=True)
        model_used = resp_obj.get("model") if isinstance(resp_obj.get("model"), str) \
            else route.model
        if self.wire == "ollama" and not usage.compute_s:
            usage.compute_s = round(upstream_ms / 1000.0, 3)  # A-08: wall time fallback
        usage.cost_usd = self._price(model_used or route.model, usage)
        outcome = Outcome(status_code=200, usage=usage, upstream_ms=upstream_ms,
                          provider=route.provider, model_used=model_used)
        ctx.state["core.outcome"] = outcome
        resp_i.parent_id = req_i.id
        resp_i.model = route.model
        resp_i.destination = await self._response_destination(ctx, route)
        resp_i.meta.update({"provider": route.provider, "source": self.source,
                            "stream": req_i.meta.get("stream")})
        if self.wire == "ollama":
            resp_i.meta["op"] = self.op
        rv = await self._evaluate(ctx, resp_i)
        outcome.response_verdict_id = rv.id
        raw_text = _segments_text(resp_i.segments, {"assistant", "tool_args"})
        if rv.action in ("block", "require_approval"):
            text = block_message(rv)
            kwargs = {"op": self.op} if self.wire == "ollama" else {}
            final = self.adapter.notice_message(text, model=model_used, **kwargs)
            local_text = text
        else:
            segs = list(rv.segments) if rv.segments else list(resp_i.segments)
            final = self.adapter.apply_segments(resp_obj, segs) if rv.segments else resp_obj
            ok, roles = self._should_rehydrate(ctx, rv, defaults)
            if ok:
                new_segs: list[TextSegment] = []
                for s in segs:
                    if s.redactable and s.role in roles:
                        try:
                            txt = self.rt.redactor.rehydrate(ctx, s.text)
                        except Exception:
                            log.exception("rehydrate failed; placeholders kept")
                            txt = s.text
                        if txt != s.text:
                            s = s.model_copy(update={"text": txt})
                    new_segs.append(s)
                final = self.adapter.apply_segments(final, new_segs)
                segs = new_segs
            local_text = _segments_text(self.adapter.parse_response(final).segments,
                                        {"assistant", "tool_args"})
        try:
            self.rt.pipeline.attach_response(verdict.id, response_raw=raw_text,
                                             response_local=local_text)
        except Exception:
            log.debug("attach_response failed", exc_info=True)
        return final, rv, outcome

    def _fill_texts(self, res: ModelCallResult, resp_obj: dict[str, Any],
                    final: dict[str, Any]) -> None:
        try:
            res.response_raw_text = _segments_text(
                self.adapter.parse_response(resp_obj).segments, {"assistant"})
            res.response_local_text = _segments_text(
                self.adapter.parse_response(final).segments, {"assistant"})
        except Exception:  # pragma: no cover
            log.debug("text extraction failed", exc_info=True)

    # ------------------------------------------------------------------ stream generators
    async def _anthropic_buffered(
        self, resp: httpx.Response, ctx: RequestContext, req_i: Interaction, verdict: Verdict,
        route: Route, t_up: float, defaults: Defaults, res: ModelCallResult,
    ) -> AsyncIterator[bytes]:
        acc = AnthropicAccumulator()
        head_sent = False
        outcome: Outcome | None = None
        try:
            err: str | None = None
            try:
                async for item in with_keepalive(resp.aiter_bytes(), KEEPALIVE_S):
                    if item is KEEPALIVE:
                        yield anthropic_ping() if head_sent else b":keep-alive\n\n"
                        continue
                    for ev in acc.feed(item):
                        if ev.type == "message_start" and not head_sent:
                            head_sent = True
                            yield ev.to_bytes()
                        elif ev.type == "ping" and head_sent:
                            yield ev.to_bytes()
                acc.close()
            except httpx.HTTPError as exc:
                err = type(exc).__name__
                log.warning("upstream stream interrupted provider=%s error=%s",
                            route.provider, err)
            ms = (time.perf_counter() - t_up) * 1000.0
            if acc.error is not None or err is not None or not acc.started:
                if acc.error_raw is not None:
                    yield acc.error_raw
                else:
                    yield _sse_error("api_error", f"[Aegis] upstream stream failed: "
                                                  f"{err or 'no message received'}")
                outcome = Outcome(status_code=502, usage=Usage(requests=1), upstream_ms=ms,
                                  provider=route.provider, model_used=route.model,
                                  error=err or "upstream stream error")
                return
            try:
                msg = acc.message()
                final, rv, outcome = await self._process_response(ctx, req_i, verdict, msg,
                                                                  route, ms, defaults)
            except Exception as exc:
                log.warning("invalid upstream stream provider=%s error=%s", route.provider,
                            type(exc).__name__, exc_info=True)
                yield _sse_error("api_error", "[Aegis] invalid upstream response")
                outcome = _bad_upstream(route, ms)
                return
            res.response_verdict = rv
            res.response_body = final
            res.usage = outcome.usage
            self._fill_texts(res, msg, final)
            yield anthropic_events(final, include_start=not head_sent,
                                   delta_usage=acc.delta_usage or None)
        finally:
            with anyio.CancelScope(shield=True):
                await resp.aclose()
            await self._complete(ctx, req_i, verdict, outcome or Outcome(
                status_code=499, usage=Usage(requests=1), provider=route.provider,
                model_used=route.model, error="client disconnected"))

    async def _openai_buffered(
        self, resp: httpx.Response, ctx: RequestContext, req_i: Interaction, verdict: Verdict,
        route: Route, t_up: float, defaults: Defaults, include_usage: bool,
        res: ModelCallResult,
    ) -> AsyncIterator[bytes]:
        acc = OpenAIAccumulator()
        outcome: Outcome | None = None
        try:
            err: str | None = None
            try:
                async for item in with_keepalive(resp.aiter_bytes(), KEEPALIVE_S):
                    if item is KEEPALIVE:
                        yield b": keep-alive\n\n"
                        continue
                    acc.feed(item)
                acc.close()
            except httpx.HTTPError as exc:
                err = type(exc).__name__
            ms = (time.perf_counter() - t_up) * 1000.0
            if acc.error is not None or err is not None or not acc.chunks:
                if acc.error_raw is not None:
                    yield acc.error_raw
                else:
                    yield (b"data: " + dumps({"error": {
                        "type": "upstream_error", "code": "upstream_error",
                        "message": f"[Aegis] upstream stream failed: {err or 'empty stream'}"}})
                        + b"\n\n")
                yield b"data: [DONE]\n\n"
                outcome = Outcome(status_code=502, usage=Usage(requests=1), upstream_ms=ms,
                                  provider=route.provider, model_used=route.model,
                                  error=err or "upstream stream error")
                return
            try:
                comp = acc.completion()
                final, rv, outcome = await self._process_response(ctx, req_i, verdict, comp,
                                                                  route, ms, defaults)
            except Exception as exc:
                log.warning("invalid upstream stream provider=%s error=%s", route.provider,
                            type(exc).__name__, exc_info=True)
                yield (b"data: " + dumps({"error": {
                    "type": "upstream_error", "code": "upstream_error",
                    "message": "[Aegis] invalid upstream response"}}) + b"\n\n")
                yield b"data: [DONE]\n\n"
                outcome = _bad_upstream(route, ms)
                return
            res.response_verdict = rv
            res.response_body = final
            res.usage = outcome.usage
            self._fill_texts(res, comp, final)
            yield openai_chunks(final, include_usage=include_usage)
        finally:
            with anyio.CancelScope(shield=True):
                await resp.aclose()
            await self._complete(ctx, req_i, verdict, outcome or Outcome(
                status_code=499, usage=Usage(requests=1), provider=route.provider,
                model_used=route.model, error="client disconnected"))

    async def _ollama_buffered(
        self, resp: httpx.Response, ctx: RequestContext, req_i: Interaction, verdict: Verdict,
        route: Route, t_up: float, defaults: Defaults, res: ModelCallResult,
    ) -> AsyncIterator[bytes]:
        acc = OllamaAccumulator()
        outcome: Outcome | None = None
        try:
            err: str | None = None
            try:
                async for item in with_keepalive(resp.aiter_bytes(), KEEPALIVE_S):
                    if item is KEEPALIVE:
                        continue  # NDJSON has no comment syntax; blank lines are skipped
                    acc.feed(item)
                acc.close()
            except httpx.HTTPError as exc:
                err = type(exc).__name__
            ms = (time.perf_counter() - t_up) * 1000.0
            if acc.error is not None or err is not None or acc.final is None:
                if acc.error_raw is not None:
                    yield acc.error_raw
                else:
                    yield dumps({"error": f"[Aegis] upstream stream failed: "
                                          f"{err or 'incomplete stream'}"}) + b"\n"
                outcome = Outcome(status_code=502, usage=Usage(requests=1), upstream_ms=ms,
                                  provider=route.provider, model_used=route.model,
                                  error=err or "upstream stream error")
                return
            try:
                obj = acc.response()
                final, rv, outcome = await self._process_response(ctx, req_i, verdict, obj,
                                                                  route, ms, defaults)
            except Exception as exc:
                log.warning("invalid upstream stream provider=%s error=%s", route.provider,
                            type(exc).__name__, exc_info=True)
                yield dumps({"error": "[Aegis] invalid upstream response"}) + b"\n"
                outcome = _bad_upstream(route, ms)
                return
            res.response_verdict = rv
            res.response_body = final
            res.usage = outcome.usage
            self._fill_texts(res, obj, final)
            yield ollama_lines(final, op=self.op)
        finally:
            with anyio.CancelScope(shield=True):
                await resp.aclose()
            await self._complete(ctx, req_i, verdict, outcome or Outcome(
                status_code=499, usage=Usage(requests=1), provider=route.provider,
                model_used=route.model, error="client disconnected"))

    async def _passthrough(
        self, resp: httpx.Response, ctx: RequestContext, req_i: Interaction, verdict: Verdict,
        route: Route, t_up: float,
    ) -> AsyncIterator[bytes]:
        """`stream_mode: passthrough` — raw relay (no output controls), usage still recorded."""
        acc: Any
        if self.wire == "anthropic":
            acc = AnthropicAccumulator()
        elif self.wire == "openai":
            acc = OpenAIAccumulator()
        else:
            acc = OllamaAccumulator()
        outcome: Outcome | None = None
        try:
            try:
                async for chunk in resp.aiter_bytes():
                    try:
                        acc.feed(chunk)
                    except Exception:  # never break the relay because of the tee
                        pass
                    yield chunk
                acc.close()
            except httpx.HTTPError as exc:
                log.warning("passthrough stream interrupted error=%s", type(exc).__name__)
            ms = (time.perf_counter() - t_up) * 1000.0
            try:
                if self.wire == "anthropic":
                    obj = acc.message()
                elif self.wire == "openai":
                    obj = acc.completion()
                else:
                    obj = acc.response()
                usage = self.adapter.parse_usage(obj)
                resp_i = self.adapter.parse_response(obj)
            except Exception:
                usage, resp_i = Usage(), None
            usage.cost_usd = self._price(route.model, usage)
            outcome = Outcome(status_code=200, usage=usage, upstream_ms=ms,
                              provider=route.provider, model_used=route.model)
            record_only = getattr(self.rt.pipeline, "record_only", None)
            if resp_i is not None and callable(record_only):
                resp_i.parent_id = req_i.id
                resp_i.destination = await self._response_destination(ctx, route)
                resp_i.meta["passthrough"] = True
                try:
                    with anyio.CancelScope(shield=True):
                        rv = await record_only(ctx, resp_i, outcome)
                    outcome.response_verdict_id = getattr(rv, "id", None)
                except Exception:
                    log.debug("record_only failed", exc_info=True)
        finally:
            with anyio.CancelScope(shield=True):
                await resp.aclose()
            await self._complete(ctx, req_i, verdict, outcome or Outcome(
                status_code=499, usage=Usage(requests=1), provider=route.provider,
                model_used=route.model, error="client disconnected"))


def apply_body_mutations(outbound: dict[str, Any], verdict: Verdict) -> dict[str, Any]:
    """`target="body"` mutations, applied after `apply_segments` (A-13): sets first, then removes
    in descending list-index order so indices stay valid. Copy-on-write (input untouched)."""
    muts = [m for m in verdict.mutations if m.target == "body"]
    if not muts:
        return outbound
    for m in (m for m in muts if m.op == "set"):
        try:
            outbound = cow_set(outbound, m.path, m.value)
        except Exception:
            log.warning("body mutation failed op=set path=%s", m.path)

    def _key(m: Any) -> tuple[str, int]:
        mm = re.search(r"\[(\d+)\]$", m.path)
        return (m.path[: mm.start()] if mm else m.path, int(mm.group(1)) if mm else -1)

    for m in sorted((m for m in muts if m.op == "remove"), key=_key, reverse=True):
        outbound = cow_remove(outbound, m.path)
    return outbound


_SEEN: OrderedDict[str, set[bytes]] = OrderedDict()
_SEEN_SESSIONS = 256
_SEEN_PER_SESSION = 4096


def fresh_segments(session_id: str | None, segments: list[TextSegment]) -> list[int]:
    """GW-17: indexes of segments whose text (sha256) was not seen earlier in this session.

    A hint for expensive controls on long Claude Code conversations (the transcript is resent on
    every turn); redaction still runs on every segment. Bounded LRU: 256 sessions x 4096 hashes.
    """
    if not session_id:
        return list(range(len(segments)))
    seen = _SEEN.get(session_id)
    if seen is None:
        seen = set()
        _SEEN[session_id] = seen
        while len(_SEEN) > _SEEN_SESSIONS:
            _SEEN.popitem(last=False)
    else:
        _SEEN.move_to_end(session_id)
    fresh: list[int] = []
    for idx, s in enumerate(segments):
        h = hashlib.sha256(s.text.encode("utf-8", "surrogatepass")).digest()[:16]
        if h not in seen:
            fresh.append(idx)
            if len(seen) < _SEEN_PER_SESSION:
                seen.add(h)
    return fresh


def _is_json_object(data: bytes) -> bool:
    try:
        return isinstance(loads(data), dict) if data else False
    except Exception:
        return False


def _bad_upstream(route: Route, ms: float) -> Outcome:
    return Outcome(status_code=502, usage=Usage(requests=1), upstream_ms=ms,
                   provider=route.provider, model_used=route.model,
                   error="invalid upstream response")


def _sse_error(etype: str, message: str) -> bytes:
    from aegis.proxy.sse import encode_sse

    return encode_sse(dumps({"type": "error", "error": {"type": etype, "message": message}})
                      .decode("utf-8"), event="error")


# ====================================================================== route helper
async def handle_model_request(
    request: Request, *, wire: str, op: str | None = None,
    hints: Mapping[str, str] | None = None,
) -> Response:
    """Shared FastAPI handler body for the model proxy routes."""
    try:
        rt = runtime_of(request)
    except RuntimeError:
        return JSONResponse(_error_body(wire, 503, "unavailable", "gateway runtime not started"),
                            status_code=503)
    raw = await request.body()
    max_bytes = Defaults().max_body_bytes
    try:
        snap = rt.policy.snapshot()
        max_bytes = int(snap.doc.defaults.max_body_bytes)
    except Exception:
        pass
    if len(raw) > max_bytes:
        return JSONResponse(_error_body(wire, 413, "invalid_request",
                                        f"request body exceeds {max_bytes} bytes"),
                            status_code=413)
    try:
        body = loads(raw) if raw else None
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(_error_body(wire, 400, "invalid_request",
                                        "request body must be a JSON object"), status_code=400)
    client = getattr(request, "client", None)
    call = ModelCall(rt, wire=wire, op=op, query=request.url.query, source="proxy",
                     client_headers=request.headers, identity_hints=hints,
                     client_ip=getattr(client, "host", None))
    try:
        result = await call.run(body, raw)
    except Exception:
        log.exception("model call failed wire=%s", wire)
        return JSONResponse(_error_body(wire, 500, "internal_error",
                                        "[Aegis] internal error in the model proxy"),
                            status_code=500)
    return result.to_response()
