"""McpGovernor (transport-agnostic) + Streamable HTTP plumbing for `/mcp/{server}`.

The HTTP route and the stdio endpoint both reduce traffic to two calls:

    gv  = await governor.on_client_message(mctx, msg)          # client -> server
          gv.action == "forward"  -> send gv.message upstream (maybe rewritten)
          gv.action == "respond"  -> send gv.message back to the client, never upstream
    msg = await governor.on_server_message(mctx, msg, request, gv)   # server -> client

Every decision comes from `rt.pipeline.evaluate` (controls MCP-01..04 + DLP/INJ/ACT/... from other
workstreams). The transport keeps the spike's verified mechanics: era detection, SSE codec,
routing-header checks and recomputation, request/response correlation, synthetic isError
results, TOFU pin bookkeeping. Fail-closed: if governance raises, `tools/call` is blocked and
`tools/list` only shows tools whose pin still matches.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from aegis.core.types import Identity, Interaction, Outcome, Usage, Verdict
from aegis.mcp import interactions as ix
from aegis.mcp.jsonrpc import (
    INVALID_REQUEST,
    LEGACY,
    MODERN,
    PARSE_ERROR,
    UNKNOWN_SERVER,
    UPSTREAM_UNREACHABLE,
    approval_pending_result,
    blocked_result,
    check_modern_request,
    detect_era,
    is_notification,
    is_request,
    is_response,
    iter_sse,
    jsonrpc_error,
    recompute_routing_headers,
)
from aegis.mcp.pins import diff_summary, diff_tools

if TYPE_CHECKING:
    from aegis.mcp.service import McpService

log = logging.getLogger(__name__)

CONTENT_METHODS = ("tools/call", "resources/read", "prompts/get")
LIFECYCLE_METHODS = ("initialize", "server/discover")
SERVER_TO_CLIENT_REQUESTS = ("sampling/createMessage", "elicitation/create", "roots/list")

# Request headers passed upstream. Client credentials (Authorization, Cookie, x-api-key) and the
# client Host are NEVER forwarded (token passthrough is a spec MUST NOT; upstream DNS-rebinding
# guard). Per-server credentials are injected from `mcp.servers[s].headers_env`.
FWD_REQUEST = {"accept", "content-type", "mcp-session-id", "mcp-protocol-version", "mcp-method",
               "mcp-name", "last-event-id"}
FWD_RESPONSE = {"content-type", "mcp-session-id", "mcp-protocol-version", "cache-control",
                "x-accel-buffering"}
SECRET_HEADERS = {"authorization", "cookie", "x-api-key", "proxy-authorization"}
LOCAL_ORIGINS = ("http://localhost", "http://127.0.0.1", "https://localhost", "https://127.0.0.1",
                 "http://[::1]", "vscode-file://", "app://")


@dataclass
class McpCtx:
    """Per-request MCP context (one policy snapshot, one identity, one RequestContext)."""

    server: str
    transport: str = "http"
    era: str = LEGACY
    session: str | None = None
    identity: Identity = field(default_factory=Identity)
    rctx: Any = None  # RequestContext
    snap: Any = None  # PolicySnapshot
    cfg: Any = None  # McpServerConfig | None
    result_destination: str = "remote"
    public_url: str = "http://127.0.0.1:8787"
    dry_run: bool = False
    request_id: str | None = None

    def hop(self) -> ix.McpHopInfo:
        return ix.McpHopInfo(
            server=self.server, transport=self.transport, era=self.era, session=self.session,
            url=getattr(self.cfg, "url", None),
            destination=getattr(self.cfg, "destination", None) or "third_party",
            result_destination=self.result_destination,
            extra_meta={"mcp.pinned": bool(getattr(self.cfg, "pinned", True))},
        )


@dataclass
class GovVerdict:
    action: str  # forward | respond
    message: Any
    rewritten: bool = False
    decision_id: str | None = None
    final_action: str | None = None
    approval_id: str | None = None
    redactions: int = 0
    interaction: Interaction | None = None
    verdict: Verdict | None = None
    input_schema: dict[str, Any] | None = None
    completed: bool = False


def _cfg_mcp03(snap: Any) -> dict[str, Any]:
    cfg = snap.control("MCP-03") if snap is not None and hasattr(snap, "control") else None
    return dict(getattr(cfg, "params", {}) or {}) if cfg is not None else {}


class McpGovernor:
    """Transport-agnostic MCP governance on top of `rt.pipeline`."""

    def __init__(self, service: McpService) -> None:
        self.service = service

    @property
    def rt(self) -> Any:
        return self.service.rt

    @property
    def pins(self) -> Any:
        return self.service.pins

    # ------------------------------------------------------------------ pipeline wrappers
    async def _evaluate(self, mctx: McpCtx, i: Interaction) -> Verdict:
        if mctx.dry_run:
            return await self.rt.pipeline.evaluate(mctx.rctx, i, policy=mctx.snap, dry_run=True)
        return await self.rt.pipeline.evaluate(mctx.rctx, i, policy=mctx.snap)

    async def complete(self, mctx: McpCtx, gv: GovVerdict, outcome: Outcome) -> None:
        """`rt.pipeline.complete` exactly once per evaluated request-direction interaction."""
        if gv.completed or gv.interaction is None or gv.verdict is None or mctx.dry_run:
            return
        gv.completed = True
        try:
            await self.rt.pipeline.complete(mctx.rctx, gv.interaction, gv.verdict, outcome)
        except Exception:
            log.exception("pipeline complete failed server=%s", mctx.server)

    # ------------------------------------------------------------------ client -> server
    async def on_client_message(self, mctx: McpCtx, msg: Any) -> GovVerdict:
        if is_request(msg):
            method = msg.get("method")
            if method == "tools/call":
                return await self.govern_call(mctx, msg)
            if method in LIFECYCLE_METHODS:
                log.debug("mcp lifecycle server=%s method=%s era=%s", mctx.server, method, mctx.era)
        return GovVerdict("forward", msg)

    async def govern_call(self, mctx: McpCtx, msg: dict[str, Any]) -> GovVerdict:
        t0 = time.perf_counter()
        params = msg.get("params") or {}
        tool = str(params.get("name", ""))
        status = self.pins.callable_status(mctx.server, tool)
        if (status.status == "unvetted" and mctx.cfg is not None and not mctx.dry_run
                and _cfg_mcp03(mctx.snap).get("unvetted_call", "scan") == "scan"):
            try:
                await self.service.scan_server(mctx.server, mctx.identity, snap=mctx.snap)
            except Exception:
                log.warning("vet-on-first-use scan failed server=%s", mctx.server, exc_info=True)
            status = self.pins.callable_status(mctx.server, tool)
        i = ix.call_interaction(mctx.hop(), msg, status.as_meta())
        try:
            verdict = await self._evaluate(mctx, i)
        except Exception:
            log.exception("mcp governance failed (fail-closed) server=%s tool=%s", mctx.server, tool)
            text = (f"[Aegis] Blocked: governance unavailable (fail-closed) for "
                    f"{mctx.server}.{tool}")
            return GovVerdict("respond", blocked_result(msg.get("id"), mctx.era, text,
                                                        {"action": "block", "controls": []}),
                              final_action="block", interaction=i)
        self._observe("mcp.call", t0)
        gv = GovVerdict("forward", msg, decision_id=verdict.id, final_action=verdict.action,
                        interaction=i, verdict=verdict, redactions=len(verdict.redactions),
                        input_schema=self.pins.input_schema(mctx.server, tool))
        if verdict.action == "block":
            cid, reason = ix.primary_of(verdict)
            primary = verdict.primary
            text = f"[Aegis] Blocked by {cid}: {reason}. Decision {verdict.id}"
            gv.action, gv.message = "respond", blocked_result(
                msg.get("id"), mctx.era, text, ix.decision_meta(verdict))
            code = (primary.http_status if primary is not None and primary.http_status else 403)
            await self.complete(mctx, gv, Outcome(status_code=code, usage=Usage(requests=0)))
            return gv
        if verdict.action == "require_approval":
            cid, reason = ix.primary_of(verdict)
            apr = verdict.approval
            apr_id = apr.id if apr is not None else (verdict.primary.approval_id if verdict.primary else None)
            gv.approval_id = apr_id
            role = apr.required_role if apr is not None else "admin"
            title = apr.title if apr is not None else reason
            link = f"{mctx.public_url}/ui/governance/approvals?id={apr_id}"
            gv.action, gv.message = "respond", approval_pending_result(
                msg.get("id"), mctx.era, control_id=cid, title=title, required_role=role,
                approval_id=apr_id or "apr_?", link=link, meta=ix.decision_meta(verdict))
            await self.complete(mctx, gv, Outcome(status_code=403, usage=Usage(requests=0)))
            return gv
        new_msg, changed = ix.apply_call_verdict(msg, i, verdict)
        gv.message, gv.rewritten = new_msg, changed
        return gv

    # ------------------------------------------------------------------ server -> client
    async def on_server_message(self, mctx: McpCtx, msg: Any, request: dict[str, Any] | None = None,
                                gv: GovVerdict | None = None) -> Any:
        if is_response(msg) and request is not None and "result" in msg:
            method = request.get("method")
            result = msg.get("result")
            if isinstance(result, dict) and result.get("resultType") == "input_required":
                log.info("mcp input_required server=%s method=%s", mctx.server, method)
                return msg
            if method == "tools/list":
                return await self.govern_list(mctx, msg)
            if method in CONTENT_METHODS:
                return await self.govern_result(mctx, msg, request, gv)
        elif is_notification(msg) and msg.get("method") == "notifications/tools/list_changed":
            await self.service.mark_stale(mctx.server, mctx.identity)
        elif is_request(msg) and msg.get("method") in SERVER_TO_CLIENT_REQUESTS:
            log.info("mcp server->client request server=%s method=%s", mctx.server, msg.get("method"))
        return msg

    async def govern_result(self, mctx: McpCtx, msg: dict[str, Any], request: dict[str, Any],
                            gv: GovVerdict | None) -> dict[str, Any]:
        t0 = time.perf_counter()
        parent = gv.interaction if gv is not None else None
        i = ix.result_interaction(mctx.hop(), msg, request, parent)
        if not i.segments:
            return msg
        try:
            verdict = await self._evaluate(mctx, i)
        except Exception:
            log.exception("mcp result governance failed (fail-closed) server=%s", mctx.server)
            return blocked_result(msg.get("id"), mctx.era,
                                  "[Aegis] Result withheld: governance unavailable (fail-closed)",
                                  {"action": "block", "controls": []})
        self._observe("mcp.result", t0)
        out = ix.apply_result_verdict(msg, i, verdict, mctx.era)
        if gv is not None:
            gv.redactions += len(verdict.redactions)
        return out

    async def govern_list(self, mctx: McpCtx, msg: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        async with self.service.list_lock(mctx.server):
            out = await self._govern_list_locked(mctx, msg)
        self._observe("mcp.list", t0)
        return out

    async def _govern_list_locked(self, mctx: McpCtx, msg: dict[str, Any]) -> dict[str, Any]:
        result = msg.get("result") or {}
        tools = [t for t in (result.get("tools") or []) if isinstance(t, dict)]
        cfg = mctx.cfg
        allowed = list(getattr(cfg, "allowed_tools", None) or ["*"])
        snap = mctx.snap
        version = getattr(snap, "version", 0)
        feed_serial = self.service.feed_serial()
        outcomes: dict[int, ix.ListOutcome] = {}
        todo: list[tuple[int, dict[str, Any], Any, tuple[Any, ...]]] = []
        for idx, tool in enumerate(tools):
            name = str(tool.get("name", ""))
            if not any(_glob(p, name) for p in allowed):
                log.debug("mcp tool filtered by allowed_tools server=%s tool=%s", mctx.server, name)
                outcomes[idx] = ix.ListOutcome(True, None, reason="allowed_tools")
                continue
            check = self.pins.check(mctx.server, tool)
            key = (mctx.server, name, check.hash, version, feed_serial, check.status, check.reason)
            cached = None if mctx.dry_run else self.service.list_cache.get(key)
            if cached is not None:
                outcomes[idx] = cached
                continue
            todo.append((idx, tool, check, key))

        if todo:
            hop = mctx.hop()
            items = [(idx, tool, check, key,
                      ix.list_interaction(hop, tool, idx, check.as_meta(), msg.get("id")))
                     for idx, tool, check, key in todo]
            verdicts = await asyncio.gather(*(self._evaluate(mctx, it[4]) for it in items),
                                            return_exceptions=True)
            for (idx, tool, check, key, inter), verdict in zip(items, verdicts, strict=True):
                if isinstance(verdict, BaseException):
                    log.error("mcp list governance failed (fail-closed) server=%s tool=%s err=%s",
                              mctx.server, tool.get("name"), verdict)
                    keep = check.status == "match"
                    outcomes[idx] = ix.ListOutcome(not keep, tool if keep else None,
                                                   reason="governance unavailable (fail-closed)")
                    continue
                outcome = ix.apply_list_outcome(tool, inter, verdict)
                outcomes[idx] = outcome
                if not mctx.dry_run:
                    await self._bookkeep(mctx, tool, check, outcome, verdict)
                    self.service.list_cache[key] = outcome

        visible = [outcomes[i].tool_out for i in range(len(tools))
                   if i in outcomes and not outcomes[i].drop and outcomes[i].tool_out is not None]
        if not mctx.dry_run and result.get("nextCursor") is None:
            await self.pins.mark_baseline(mctx.server)
        new_result = ix.modern_ttl_clamp(result, mctx.era)
        if visible == tools and new_result is result:
            return msg
        return {**msg, "result": {**new_result, "tools": visible}}

    async def _bookkeep(self, mctx: McpCtx, tool: dict[str, Any], check: Any,
                        outcome: ix.ListOutcome, verdict: Verdict) -> None:
        """Pin bookkeeping after the verdict (the transport does this so controls stay pure)."""
        server, name = mctx.server, str(tool.get("name", ""))
        before = self.pins.view_status(server, name) if (server, name) in self.pins.first_seen else None
        pin, cand = self.pins.get(server, name)
        pinned_cfg = bool(getattr(mctx.cfg, "pinned", True))
        new_after_baseline = check.status == "new" and check.baseline
        if not outcome.drop:
            if check.status == "new" and pinned_cfg and pin is None:
                await self.pins.pin(server, tool, approved_by="tofu")
            elif check.status == "quarantined" and check.reason == "poisoned":
                await self.pins.pin(server, tool, approved_by=pin.approved_by if pin else "tofu")
            elif check.status == "match" and cand is not None and cand.reason in ("poisoned", "changed"):
                await self.pins.clear_candidate(server, name)
            elif check.status == "changed":
                diff = diff_tools(pin.definition, tool) if pin else {}
                if cand is None or cand.hash != check.hash:
                    await self.pins.set_candidate(server, tool, reason="changed", diff=diff)
            else:
                await self.pins.touch(server, name)
        else:
            if check.status == "changed":
                diff = diff_tools(pin.definition, tool) if pin else {}
                c = await self.pins.set_candidate(server, tool, reason="changed", diff=diff,
                                                  findings=outcome.findings)
                await self.service.ensure_repin_approval(server, name, c, mctx.identity, cfg=mctx.cfg)
            elif new_after_baseline:
                c = await self.pins.set_candidate(server, tool, reason="new_after_baseline",
                                                  findings=outcome.findings)
                await self.service.ensure_repin_approval(server, name, c, mctx.identity, cfg=mctx.cfg)
            elif check.status == "quarantined" and check.reason == "manual":
                await self.pins.touch(server, name)
            elif cand is None or cand.hash != check.hash or cand.reason != "poisoned":
                await self.pins.quarantine(server, tool, reason="poisoned", findings=outcome.findings)
            else:
                await self.pins.touch(server, name)
        after = self.pins.view_status(server, name)
        if after != before:
            p2, c2 = self.pins.get(server, name)
            reason = outcome.reason if outcome.drop else ("pinned on first use" if after == "approved"
                                                          else "; ".join(self.pins.reasons(server, name)))
            if c2 is not None and c2.reason == "changed":
                reason = f"MCP-03: definition changed ({diff_summary(c2.diff)})"
            await self.service.transition(server, name, before, after, reason,
                                          pinned_hash=p2.hash if p2 else None,
                                          hash_=check.hash, approval_id=c2.approval_id if c2 else None,
                                          actor=mctx.identity)

    def _observe(self, phase: str, t0: float) -> None:
        try:
            self.rt.metrics.observe_overhead("mcp", time.perf_counter() - t0)
        except Exception:
            pass


def _glob(pattern: str, value: str) -> bool:
    try:
        from aegis.core.paths import glob_match  # public surface (core-gateway)

        return bool(glob_match(pattern, value))
    except Exception:  # TODO(integration): drop fallback once aegis.core.paths exists
        import fnmatch

        return pattern == "*" or fnmatch.fnmatchcase(value, pattern)


# ====================================================================== HTTP plumbing
def lower_headers(request: Request) -> dict[str, str]:
    return {k.lower(): v for k, v in request.headers.items()}


def forward_request_headers(request: Request) -> dict[str, str]:
    return {k: v for k, v in lower_headers(request).items()
            if k in FWD_REQUEST or k.startswith("mcp-param-")}


def forward_response_headers(resp: httpx.Response) -> dict[str, str]:
    return {k: v for k, v in resp.headers.items() if k.lower() in FWD_RESPONSE}


def clean_ctx_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k not in SECRET_HEADERS}


def origin_ok(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        return True
    return any(origin == o or origin.startswith(o + ":") or origin.startswith(o + "/")
               for o in LOCAL_ORIGINS)


def upstream_headers(cfg: Any, headers: dict[str, str], settings: Any = None) -> dict[str, str]:
    """Inject per-server credentials from env (`headers_env`: header -> env var)."""
    out = dict(headers)
    for header, env_name in (getattr(cfg, "headers_env", None) or {}).items():
        value = None
        if settings is not None and hasattr(settings, "env"):
            try:
                value = settings.env(env_name)
            except Exception:
                value = None
        if value is None:
            import os

            value = os.environ.get(env_name)
        if value:
            out[header.lower()] = value
    return out


def aegis_headers(mctx: McpCtx, gv: GovVerdict | None, *, t_total: float | None = None,
                  upstream_s: float | None = None) -> dict[str, str]:
    h: dict[str, str] = {}
    if mctx.request_id:
        h["x-aegis-request-id"] = mctx.request_id
    if mctx.snap is not None:
        h["x-aegis-policy-version"] = str(getattr(mctx.snap, "version", 0))
    rctx = mctx.rctx
    if rctx is not None and getattr(rctx, "feed_serial", None) is not None:
        h["x-aegis-feed-serial"] = str(rctx.feed_serial)
    if gv is not None and gv.decision_id:
        h["x-aegis-decision-id"] = gv.decision_id
        h["x-aegis-decision"] = gv.final_action or "allow"
        h["x-aegis-redactions"] = str(gv.redactions)
    if gv is not None and gv.approval_id:
        h["x-aegis-approval-id"] = gv.approval_id
    timing = []
    if t_total is not None:
        aegis_ms = max(0.0, (t_total - (upstream_s or 0.0)) * 1000)
        timing.append(f"aegis;dur={aegis_ms:.2f}")
    if upstream_s is not None:
        timing.append(f"upstream;dur={upstream_s * 1000:.2f}")
    if timing:
        h["server-timing"] = ", ".join(timing)
    return h


def rpc_response(msg: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None
                 ) -> JSONResponse:
    return JSONResponse(msg, status_code=status, headers=headers or {})


async def handle_post(service: McpService, request: Request, server: str) -> Response:
    """POST /mcp/{server}: guards → govern client message → upstream → govern answer → relay."""
    t_start = time.perf_counter()
    rt = service.rt
    if not origin_ok(request):
        return rpc_response(jsonrpc_error(None, INVALID_REQUEST, "[Aegis] origin not allowed"), 403)
    snap = rt.policy.snapshot()
    raw = await request.body()
    max_bytes = int(getattr(getattr(snap.doc, "defaults", None), "max_body_bytes", 8_000_000))
    if len(raw) > max_bytes:
        return rpc_response(jsonrpc_error(None, INVALID_REQUEST,
                                          f"[Aegis] request body exceeds {max_bytes} bytes"), 413)
    try:
        body = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return rpc_response(jsonrpc_error(None, PARSE_ERROR, "Parse error"), 400)
    if isinstance(body, list):
        return rpc_response(jsonrpc_error(None, INVALID_REQUEST,
                                          "[Aegis] JSON-RPC batches are not supported"), 400)
    if not isinstance(body, dict):
        return rpc_response(jsonrpc_error(None, INVALID_REQUEST, "Invalid Request"), 400)

    headers_in = lower_headers(request)
    fwd = forward_request_headers(request)
    era = detect_era(fwd, body)
    mctx = await service.make_ctx(server, headers_in, era=era, transport="http", snap=snap)
    cfg = mctx.cfg
    if cfg is None or getattr(cfg, "transport", "http") != "http" or not getattr(cfg, "url", None):
        return await service.unknown_server(mctx, body)

    schema = None
    if is_request(body) and body.get("method") == "tools/call":
        schema = service.pins.input_schema(server, str((body.get("params") or {}).get("name")))
    if era == MODERN and is_request(body):
        raw_pairs = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in request.headers.raw]
        rejection = check_modern_request(body, headers_in, raw_pairs, schema)
        if rejection is not None:
            await service.record_header_mismatch(mctx, body, rejection.message)
            return rpc_response(jsonrpc_error(body.get("id"), rejection.code,
                                              f"[Aegis] request smuggling defense: {rejection.message}"),
                                400, aegis_headers(mctx, None))

    gv = await service.governor.on_client_message(mctx, body)
    if gv.action == "respond":
        return rpc_response(gv.message, 200, aegis_headers(mctx, gv, t_total=time.perf_counter() - t_start))

    msg_out = gv.message
    content = json.dumps(msg_out, ensure_ascii=False).encode() if gv.rewritten else raw
    if era == MODERN and is_request(msg_out):
        fwd = recompute_routing_headers(fwd, msg_out, gv.input_schema or schema)
    fwd = upstream_headers(cfg, fwd, getattr(rt, "settings", None))
    t_up = time.perf_counter()
    try:
        resp = await service.send_upstream("POST", cfg.url, fwd, content)
    except httpx.HTTPError as e:
        await service.upstream_failed(mctx, f"{type(e).__name__}")
        await service.governor.complete(mctx, gv, Outcome(status_code=502, usage=Usage(requests=0),
                                                          error=type(e).__name__))
        return rpc_response(
            jsonrpc_error(body.get("id"), UPSTREAM_UNREACHABLE,
                          f"[Aegis] upstream MCP server '{server}' unreachable ({type(e).__name__})"),
            502, aegis_headers(mctx, gv))
    service.upstream_ok(server)
    return await relay(service, mctx, resp, msg_out if is_request(msg_out) else None, gv,
                       t_start=t_start, t_up=t_up)


async def relay(service: McpService, mctx: McpCtx, resp: httpx.Response,
                request_msg: dict[str, Any] | None, gv: GovVerdict | None, *,
                t_start: float, t_up: float) -> Response:
    """Relay an upstream answer (JSON or SSE), governing each JSON-RPC message."""
    headers = forward_response_headers(resp)
    mctx.session = resp.headers.get("mcp-session-id") or mctx.session
    governor = service.governor

    async def transform(msg: Any) -> Any:
        answers = request_msg is not None and is_response(msg) and msg.get("id") == request_msg.get("id")
        return await governor.on_server_message(mctx, msg, request_msg if answers else None, gv)

    async def finish(status: int, upstream_s: float) -> None:
        service.observe_upstream(mctx.server, upstream_s)
        if gv is not None:
            await governor.complete(mctx, gv, Outcome(
                status_code=status, usage=Usage(requests=1, tool_calls=1),
                upstream_ms=upstream_s * 1000))

    if "text/event-stream" in resp.headers.get("content-type", ""):
        upstream_s = time.perf_counter() - t_up
        headers.update(aegis_headers(mctx, gv, t_total=time.perf_counter() - t_start,
                                     upstream_s=upstream_s))
        headers.setdefault("x-accel-buffering", "no")
        status = resp.status_code

        async def events() -> AsyncIterator[bytes]:
            try:
                async for ev in iter_sse(resp.aiter_bytes()):
                    msg = ev.json()
                    if msg is not None:
                        new = await transform(msg)
                        if new is not msg:
                            ev.data = json.dumps(new, ensure_ascii=False)
                    yield ev.encode()
            finally:
                await resp.aclose()
                await finish(status, time.perf_counter() - t_up)

        return StreamingResponse(events(), status_code=status, headers=headers)

    data = await resp.aread()
    await resp.aclose()
    upstream_s = time.perf_counter() - t_up
    if data and "application/json" in resp.headers.get("content-type", ""):
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            msg = None
        if msg is not None:
            new = await transform(msg)
            if new is not msg:
                data = json.dumps(new, ensure_ascii=False).encode()
    await finish(resp.status_code, upstream_s)
    headers.update(aegis_headers(mctx, gv, t_total=time.perf_counter() - t_start,
                                 upstream_s=upstream_s))
    headers.pop("content-length", None)
    return Response(content=data, status_code=resp.status_code, headers=headers)


async def handle_get(service: McpService, request: Request, server: str) -> Response:
    """Legacy standalone SSE stream (server->client); relayed with no short read timeout."""
    if not origin_ok(request):
        return rpc_response(jsonrpc_error(None, INVALID_REQUEST, "[Aegis] origin not allowed"), 403)
    snap = service.rt.policy.snapshot()
    headers_in = lower_headers(request)
    fwd = forward_request_headers(request)
    mctx = await service.make_ctx(server, headers_in, era=detect_era(fwd, None), transport="http",
                                  snap=snap)
    if mctx.cfg is None or not getattr(mctx.cfg, "url", None):
        return await service.unknown_server(mctx, {})
    try:
        resp = await service.send_upstream("GET", mctx.cfg.url,
                                           upstream_headers(mctx.cfg, fwd, getattr(service.rt, "settings", None)),
                                           None)
    except httpx.HTTPError as e:
        await service.upstream_failed(mctx, type(e).__name__)
        return rpc_response(jsonrpc_error(None, UPSTREAM_UNREACHABLE,
                                          f"[Aegis] upstream MCP server '{server}' unreachable"), 502)
    t = time.perf_counter()
    return await relay(service, mctx, resp, None, None, t_start=t, t_up=t)


async def handle_delete(service: McpService, request: Request, server: str) -> Response:
    snap = service.rt.policy.snapshot()
    cfg = snap.doc.mcp.servers.get(server)
    if cfg is None or not getattr(cfg, "url", None):
        return rpc_response(jsonrpc_error(None, UNKNOWN_SERVER,
                                          f"[Aegis] unknown MCP server '{server}'"), 404)
    fwd = upstream_headers(cfg, forward_request_headers(request), getattr(service.rt, "settings", None))
    try:
        resp = await service.send_upstream("DELETE", cfg.url, fwd, None)
    except httpx.HTTPError:
        return rpc_response(jsonrpc_error(None, UPSTREAM_UNREACHABLE, "[Aegis] upstream unreachable"), 502)
    data = await resp.aread()
    await resp.aclose()
    return Response(content=data, status_code=resp.status_code, headers=forward_response_headers(resp))


def host_of(url: str | None) -> str | None:
    return urlparse(url).netloc if url else None


__all__ = [
    "FWD_REQUEST", "FWD_RESPONSE", "GovVerdict", "McpCtx", "McpGovernor", "aegis_headers",
    "clean_ctx_headers", "forward_request_headers", "handle_delete", "handle_get", "handle_post",
    "origin_ok", "relay", "upstream_headers",
]
