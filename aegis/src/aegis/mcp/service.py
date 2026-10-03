"""McpService: process-wide MCP proxy state (shared httpx client, PinStore, governor, caches).

Created and started by `aegis.api.routes.mcp.on_startup(rt)`; tests inject their own with
`set_service(McpService(fake_rt, client=httpx.AsyncClient(transport=ASGITransport(mock_app))))`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import OrderedDict
from typing import Any

import httpx

from aegis.core.types import ApprovalDraft, ApprovalRequest, Identity, Outcome, Usage
from aegis.mcp import interactions as ix
from aegis.mcp.events import system_warning, tool_transition
from aegis.mcp.inventory import (
    InventoryState,
    McpServerView,
    McpToolView,
    build_inventory,
    tool_detail,
    tool_view,
)
from aegis.mcp.jsonrpc import (
    LEGACY,
    MODERN,
    UNKNOWN_SERVER,
    detect_era,
    is_request,
    is_response,
    jsonrpc_error,
)
from aegis.mcp.pins import Candidate, PinStore, diff_summary
from aegis.mcp.proxy import (
    GovVerdict,
    McpCtx,
    McpGovernor,
    aegis_headers,
    clean_ctx_headers,
    rpc_response,
    upstream_headers,
)

log = logging.getLogger(__name__)

_SERVICE: McpService | None = None


def get_service() -> McpService | None:
    """The running service, or None before `on_startup` (controls degrade to no-ops)."""
    return _SERVICE


def set_service(service: McpService | None) -> None:
    global _SERVICE
    _SERVICE = service


class McpService:
    def __init__(self, rt: Any, *, client: httpx.AsyncClient | None = None,
                 connect: Any = None, use_db: bool = True) -> None:
        self.rt = rt
        self._owned_client = client is None
        self.client: httpx.AsyncClient | None = client
        if connect is None and use_db and hasattr(rt, "db"):
            connect = rt.db
        self.pins = PinStore(connect)
        self.governor = McpGovernor(self)
        self.state = InventoryState()
        self.list_cache: dict[tuple[Any, ...], ix.ListOutcome] = {}
        self._list_locks: dict[str, asyncio.Lock] = {}
        self._agent_cache: dict[str, tuple[float, Any]] = {}
        self._scan_at: dict[str, float] = {}
        self._unknown_eval_at: dict[str, float] = {}
        self._stdio_pending: OrderedDict[tuple[str, str], dict[Any, tuple[dict[str, Any], GovVerdict]]] = OrderedDict()
        self._stdio_era: dict[tuple[str, str], str] = {}
        self._bg: set[asyncio.Task[Any]] = set()
        self.started = False

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0),
                                            follow_redirects=False)
        await self.pins.load()
        self.pins.on_change(self._invalidate)
        try:
            self.rt.approvals.register_executor("mcp_pin", self.execute_repin)
        except Exception:
            log.warning("mcp_pin executor registration failed", exc_info=True)
        try:
            self.rt.policy.on_change(self.on_policy_change)
        except Exception:
            log.warning("policy on_change registration failed", exc_info=True)
        if not self._test_mode():
            self._spawn(self._deny_watcher())
        self.started = True
        log.info("mcp service started servers=%d pins=%d", len(self._servers_cfg()),
                 sum(len(v) for v in self.pins.pins.values()))

    async def stop(self) -> None:
        for task in list(self._bg):
            task.cancel()
        for task in list(self._bg):
            with contextlib.suppress(BaseException):
                await task
        if self._owned_client and self.client is not None:
            await self.client.aclose()
        self.started = False

    def _spawn(self, coro: Any) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    def _test_mode(self) -> bool:
        return bool(getattr(getattr(self.rt, "settings", None), "test_mode", False))

    def _servers_cfg(self) -> dict[str, Any]:
        try:
            return dict(self.rt.policy.snapshot().doc.mcp.servers)
        except Exception:
            return {}

    # ------------------------------------------------------------------ helpers
    def list_lock(self, server: str) -> asyncio.Lock:
        lock = self._list_locks.get(server)
        if lock is None:
            lock = self._list_locks[server] = asyncio.Lock()
        return lock

    def feed_serial(self) -> int | None:
        try:
            return self.rt.feed.serial
        except Exception:
            return None

    def public_url(self) -> str:
        settings = getattr(self.rt, "settings", None)
        try:
            return str(settings.public_url)  # type: ignore[union-attr]
        except Exception:
            return "http://127.0.0.1:8787"

    def mask(self, text: str, max_len: int = 160) -> str:
        try:
            return str(self.rt.redactor.mask_for_log(text, max_len))
        except Exception:
            from aegis.mcp.detect import snippet

            return snippet(text, max_len)

    def _invalidate(self, server: str, tool: str | None) -> None:
        if server == "*" or tool is None:
            self.list_cache = {k: v for k, v in self.list_cache.items()
                               if server != "*" and k[0] != server}
            return
        self.list_cache = {k: v for k, v in self.list_cache.items()
                           if not (k[0] == server and k[1] == tool)}

    def on_policy_change(self, snap: Any) -> None:
        """Hot reload: drop list-cache entries of old versions (next listing re-evaluates once)."""
        version = getattr(snap, "version", None)
        self.list_cache = {k: v for k, v in self.list_cache.items() if k[3] == version}
        log.info("mcp policy change version=%s servers=%d", version,
                 len(getattr(getattr(getattr(snap, "doc", None), "mcp", None), "servers", {}) or {}))

    async def _result_destination(self, identity: Identity) -> str:
        agent_id = identity.agent_id
        if not agent_id:
            return "remote"
        now = time.monotonic()
        hit = self._agent_cache.get(agent_id)
        if hit is None or now - hit[0] > 60:
            agent = None
            try:
                agent = await self.rt.org.get_agent(agent_id)
            except Exception:
                agent = None
            hit = (now, agent)
            self._agent_cache[agent_id] = hit
        agent = hit[1]
        return "local" if getattr(agent, "max_destination", None) == "local" else "remote"

    async def make_ctx(self, server: str, headers_in: dict[str, str], *, era: str, transport: str,
                       snap: Any, session_id: str | None = None, identity: Identity | None = None,
                       dry_run: bool = False) -> McpCtx:
        rt = self.rt
        if identity is None:
            try:
                identity = await rt.org.resolve_identity(headers_in)
            except Exception:
                log.warning("identity resolution failed; anonymous agent", exc_info=True)
                identity = Identity()
        session = headers_in.get("x-aegis-session") or headers_in.get("mcp-session-id") or session_id
        wait_raw = headers_in.get("x-aegis-wait")
        try:
            wait = float(wait_raw) if wait_raw is not None else float(
                snap.doc.approvals.defaults.hold_s.get("mcp", 30))
        except (TypeError, ValueError, AttributeError):
            wait = 30.0
        rctx = rt.pipeline.new_context(
            source="mcp", identity=identity, session_id=session,
            headers=clean_ctx_headers(headers_in), approval_token=headers_in.get("x-aegis-approval"),
            wait_for_approval_s=max(0.0, wait), dry_run=dry_run)
        rctx.policy = snap
        cfg = snap.doc.mcp.servers.get(server)
        return McpCtx(server=server, transport=transport, era=era, session=session,
                      identity=identity, rctx=rctx, snap=snap, cfg=cfg,
                      result_destination=await self._result_destination(identity),
                      public_url=self.public_url(), dry_run=dry_run,
                      request_id=getattr(rctx, "request_id", None))

    # ------------------------------------------------------------------ transport events
    async def send_upstream(self, method: str, url: str, headers: dict[str, str],
                            content: bytes | None) -> httpx.Response:
        assert self.client is not None, "McpService not started"
        req = self.client.build_request(method, url, headers=headers, content=content)
        return await self.client.send(req, stream=True)

    async def upstream_failed(self, mctx: McpCtx, error: str) -> None:
        self.state.last_error[mctx.server] = (error, time.time())
        with contextlib.suppress(Exception):
            await self.pins.set_server_error(mctx.server, error)
        system_warning(self.rt, mctx.server,
                       f"MCP server '{mctx.server}' unreachable ({error})")
        log.warning("mcp upstream unreachable server=%s error=%s", mctx.server, error)

    def upstream_ok(self, server: str) -> None:
        self.state.last_ok[server] = time.time()

    def observe_upstream(self, server: str, seconds: float) -> None:
        try:
            self.rt.metrics.observe_upstream(f"mcp:{server}", None, seconds)
        except Exception:
            pass

    async def unknown_server(self, mctx: McpCtx, body: Any) -> Any:
        server = mctx.server
        req_id = body.get("id") if isinstance(body, dict) else None
        cfg = mctx.cfg
        if cfg is not None and getattr(cfg, "transport", "http") == "stdio":
            msg = (f"[Aegis] MCP server '{server}' is a stdio server; launch it through "
                   f"`python -m aegis.mcp.stdio --server {server} -- <command>`")
            return rpc_response(jsonrpc_error(req_id, UNKNOWN_SERVER, msg), 404, aegis_headers(mctx, None))
        self.state.unknown_attempts[server] = time.time()
        gv: GovVerdict | None = None
        now = time.monotonic()
        if now - self._unknown_eval_at.get(server, -1e9) > 10.0:
            self._unknown_eval_at[server] = now
            i = ix.init_interaction(mctx.hop(), registered=False, jsonrpc_id=req_id)
            try:
                verdict = await self.governor._evaluate(mctx, i)
                gv = GovVerdict("respond", None, decision_id=verdict.id, final_action=verdict.action,
                                interaction=i, verdict=verdict)
                await self.governor.complete(mctx, gv, Outcome(status_code=404, usage=Usage(requests=0)))
            except Exception:
                log.exception("unknown-server evaluation failed server=%s", server)
        msg = f"[Aegis] Blocked by MCP-01: unknown MCP server '{server}' (not in mcp.servers)"
        data = {"control_id": "MCP-01", "decision_id": gv.decision_id if gv else None}
        return rpc_response(jsonrpc_error(req_id, UNKNOWN_SERVER, msg, data), 404, aegis_headers(mctx, gv))

    async def record_header_mismatch(self, mctx: McpCtx, body: dict[str, Any], message: str) -> None:
        """Evaluate a smuggling attempt as mcp.call so MCP-04 records it (rejected regardless)."""
        if body.get("method") != "tools/call":
            log.info("mcp header mismatch server=%s method=%s", mctx.server, body.get("method"))
            return
        status = self.pins.callable_status(mctx.server, str((body.get("params") or {}).get("name", "")))
        i = ix.call_interaction(mctx.hop(), body, status.as_meta())
        i.meta["mcp.header_mismatch"] = message
        try:
            verdict = await self.governor._evaluate(mctx, i)
            gv = GovVerdict("respond", None, decision_id=verdict.id, final_action=verdict.action,
                            interaction=i, verdict=verdict)
            await self.governor.complete(mctx, gv, Outcome(status_code=400, usage=Usage(requests=0)))
        except Exception:
            log.exception("header-mismatch evaluation failed server=%s", mctx.server)

    async def mark_stale(self, server: str, identity: Identity | None = None) -> None:
        with contextlib.suppress(Exception):
            await self.pins.set_stale(server, True)
        self._invalidate(server, None)
        from aegis.mcp.events import audit_tool_change

        await audit_tool_change(self.rt, server=server, tool="", from_status=None, to_status="stale",
                                reason="server announced notifications/tools/list_changed",
                                actor=identity, event="list_changed")

    # ------------------------------------------------------------------ scanning
    async def scan_server(self, server: str, identity: Identity | None = None, *, snap: Any = None,
                          force: bool = False) -> list[dict[str, Any]] | None:
        """List the upstream's tools through the governance path (vet on first use / manual scan)."""
        from aegis.mcp.client import McpHttpClient

        snap = snap or self.rt.policy.snapshot()
        cfg = snap.doc.mcp.servers.get(server)
        if cfg is None or getattr(cfg, "transport", "http") != "http" or not cfg.url:
            return None
        now = time.monotonic()
        if not force and now - self._scan_at.get(server, -1e9) < 30.0:
            return None
        self._scan_at[server] = now
        headers = upstream_headers(cfg, {}, getattr(self.rt, "settings", None))
        try:
            async with McpHttpClient("", server, headers=headers, url=cfg.url, client=self.client) as c:
                result = await c.request("tools/list", {})
                era = c.era
        except Exception as e:
            self.state.last_error[server] = (type(e).__name__, time.time())
            raise
        self.upstream_ok(server)
        mctx = await self.make_ctx(server, {}, era=era, transport="http", snap=snap,
                                   identity=identity or Identity())
        out = await self.governor.govern_list(mctx, {"jsonrpc": "2.0", "id": "aegis-scan",
                                                     "result": result})
        return list((out.get("result") or {}).get("tools") or [])

    # ------------------------------------------------------------------ approvals
    async def ensure_repin_approval(self, server: str, tool: str, cand: Candidate,
                                    identity: Identity | None, *, cfg: Any = None
                                    ) -> ApprovalRequest | None:
        rt = self.rt
        if cand.approval_id:
            existing = None
            with contextlib.suppress(Exception):
                existing = await rt.approvals.get(cand.approval_id)
            if existing is not None and existing.status == "pending":
                if (existing.payload or {}).get("new_hash") == cand.hash:
                    return existing
                with contextlib.suppress(Exception):
                    await rt.approvals.cancel(existing.id, identity or Identity())
        pin, _ = self.pins.get(server, tool)
        cfg = cfg if cfg is not None else self._servers_cfg().get(server)
        dest = getattr(cfg, "destination", None) or "third_party"
        diff = dict(cand.diff or {})
        if cand.reason == "changed":
            title = f"Re-approve changed MCP tool {server}.{tool}"
            summary = diff_summary(diff)
        else:
            title = f"Approve new MCP tool {server}.{tool}"
            summary = "tool appeared after the server's tool set was pinned"
        masked_diff = {
            "changed_fields": diff.get("changed_fields", []),
            "params_added": diff.get("params_added", []),
            "params_removed": diff.get("params_removed", []),
            "description_diff": [self.mask(line, 240) for line in diff.get("description_diff", [])],
        }
        payload = {
            "server": server, "tool": tool, "reason": cand.reason,
            "pinned_hash": pin.hash if pin else None, "new_hash": cand.hash, "diff": masked_diff,
            "old_description_preview": self.mask(str((pin.definition if pin else {}).get("description") or ""), 240),
            "new_description_preview": self.mask(str(cand.definition.get("description") or ""), 240),
        }
        draft = ApprovalDraft(
            kind="mcp_pin", action_type="mcp.repin", title=title, summary=summary,
            resource=f"mcp:{server}.{tool}",
            labels={"destination": dest, "dest": dest, "server": server, "reason": cand.reason},
            payload=payload)
        try:
            req = await rt.approvals.create_manual(identity or Identity(), draft)
        except Exception:
            log.exception("mcp_pin approval creation failed server=%s tool=%s", server, tool)
            return None
        if req.status == "approved":  # auto route
            await self.execute_repin(req)
            return req
        await self.pins.set_approval(server, tool, req.id)
        return req

    async def execute_repin(self, req: ApprovalRequest) -> dict[str, Any] | None:
        """Approval executor for kind `mcp_pin` (registered in start())."""
        p = req.payload or {}
        server, tool, new_hash = str(p.get("server", "")), str(p.get("tool", "")), p.get("new_hash")
        before = self.pins.view_status(server, tool)
        approved_by = ",".join(req.decided_by) or "approval"
        try:
            rec = await self.pins.approve(server, tool, expected_hash=new_hash, approved_by=approved_by)
        except ValueError:
            return {"error": "candidate changed"}
        except KeyError:
            return {"error": "unknown tool"}
        self._invalidate(server, tool)
        await self.transition(server, tool, before, "approved",
                              f"MCP-03: re-approved by {approved_by} ({req.id})",
                              pinned_hash=rec.hash, hash_=rec.hash, approval_id=req.id)
        return {"server": server, "tool": tool, "hash": rec.hash}

    async def approve_tool(self, server: str, tool: str, viewer: Identity,
                           comment: str | None = None) -> McpToolView:
        """Admin approve: vote on the pending mcp_pin approval if any (PermissionError bubbles up),
        otherwise re-pin directly (audited)."""
        pin, cand = self.pins.get(server, tool)
        if pin is None and cand is None:
            raise KeyError(f"{server}/{tool} is unknown")
        if cand is not None and cand.approval_id:
            req = None
            with contextlib.suppress(Exception):
                req = await self.rt.approvals.get(cand.approval_id)
            if req is not None and req.status == "pending":
                req = await self.rt.approvals.vote(req.id, viewer, "approve", comment)
                _, c2 = self.pins.get(server, tool)
                if req.status == "approved" and c2 is not None and c2.hash == (req.payload or {}).get("new_hash"):
                    await self.execute_repin(req)  # executor did not run (e.g. null approvals)
                return self.tool_view(server, tool)
        await self.repin(server, tool, viewer, comment)
        return self.tool_view(server, tool)

    async def repin(self, server: str, tool: str, actor: Identity, comment: str | None = None) -> None:
        pin, cand = self.pins.get(server, tool)
        before = self.pins.view_status(server, tool)
        who = actor.member_id or actor.principal
        approved_by = f"override:{who}" if cand is not None and cand.reason == "poisoned" else who
        rec = await self.pins.approve(server, tool, approved_by=approved_by)
        if cand is not None and cand.approval_id:
            with contextlib.suppress(Exception):
                await self.rt.approvals.cancel(cand.approval_id, actor)
        self._invalidate(server, tool)
        await self.transition(server, tool, before, "approved",
                              f"MCP-03: re-pinned by {who}" + (f" ({comment})" if comment else ""),
                              pinned_hash=rec.hash, hash_=rec.hash, actor=actor)

    async def quarantine(self, server: str, tool: str, actor: Identity, reason: str | None = None
                         ) -> McpToolView:
        pin, cand = self.pins.get(server, tool)
        if pin is None and cand is None:
            raise KeyError(f"{server}/{tool} is unknown")
        before = self.pins.view_status(server, tool)
        who = actor.member_id or actor.principal
        await self.pins.quarantine(server, tool, reason="manual",
                                   findings=[{"reason": reason or "manual quarantine", "actor": who}])
        self._invalidate(server, tool)
        await self.transition(server, tool, before, "quarantined",
                              f"MCP-03: quarantined by {who}" + (f": {reason}" if reason else ""),
                              actor=actor)
        return self.tool_view(server, tool)

    async def reset(self, server: str | None = None) -> None:
        await self.pins.reset(server)
        self.list_cache.clear()
        self._scan_at.clear()
        if server is None:
            self.state = InventoryState()
        else:
            self.state.unknown_attempts.pop(server, None)
            self.state.last_error.pop(server, None)

    async def transition(self, server: str, tool: str, before: str | None, after: str, reason: str,
                         *, pinned_hash: str | None = None, hash_: str | None = None,
                         approval_id: str | None = None, actor: Identity | None = None) -> None:
        await tool_transition(self.rt, server=server, tool=tool, from_status=before, to_status=after,
                              reason=reason, pinned_hash=pinned_hash, hash_=hash_,
                              approval_id=approval_id, actor=actor)

    async def _deny_watcher(self) -> None:
        """Denied mcp_pin approval -> tool stays blocked, shown as quarantined."""
        try:
            async for msg in self.rt.bus.subscribe({"approval.updated"}):
                data = msg.data or {}
                if data.get("kind") != "mcp_pin" or data.get("status") != "denied":
                    continue
                p = data.get("payload") or {}
                server, tool = p.get("server"), p.get("tool")
                if not server or not tool:
                    continue
                _, cand = self.pins.get(server, tool)
                if cand is not None and cand.approval_id == data.get("id"):
                    await self.pins.quarantine(server, tool, reason="manual",
                                               findings=[{"reason": f"re-pin denied ({data.get('id')})"}])
                    await self.transition(server, tool, "changed", "quarantined",
                                          f"MCP-03: re-pin denied ({data.get('id')})")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("mcp deny watcher stopped", exc_info=True)

    # ------------------------------------------------------------------ views
    def inventory(self, snap: Any = None) -> list[McpServerView]:
        snap = snap or self.rt.policy.snapshot()
        return build_inventory(snap, self.pins, self.state, self.mask)

    def tool_view(self, server: str, tool: str) -> McpToolView:
        return tool_view(self.pins, server, tool, self.mask)

    def tool_detail(self, server: str, tool: str) -> dict[str, Any] | None:
        return tool_detail(self.pins, server, tool, self.mask)

    # ------------------------------------------------------------------ stdio inspection endpoint
    async def handle_stdio(self, server: str, body: dict[str, Any], headers_in: dict[str, str]
                           ) -> dict[str, Any]:
        """`POST /mcp/{server}/_stdio` {direction, message, session_id} -> {action, message, decision_id}."""
        direction = body.get("direction", "out")
        message = body.get("message")
        session_id = str(body.get("session_id") or "stdio")
        key = (server, session_id)
        snap = self.rt.policy.snapshot()
        cfg = snap.doc.mcp.servers.get(server)
        era = self._stdio_era.get(key, LEGACY)
        if is_request(message) and direction == "out" and message.get("method") not in ("initialize", "aegis/launch"):
            era = detect_era({}, message) if era == LEGACY else era
        mctx = await self.make_ctx(server, headers_in, era=era, transport="stdio", snap=snap,
                                   session_id=session_id)
        req_id = message.get("id") if isinstance(message, dict) else None
        if cfg is None or getattr(cfg, "transport", "http") != "stdio":
            if isinstance(message, dict) and message.get("method") == "aegis/launch":
                await self.unknown_server(mctx, message)
            text = f"[Aegis] Blocked by MCP-01: unknown stdio MCP server '{server}' (not in mcp.servers)"
            return {"action": "respond", "message": jsonrpc_error(req_id, UNKNOWN_SERVER, text),
                    "decision_id": None}
        if direction == "out":
            if isinstance(message, dict) and message.get("method") == "aegis/launch":
                command = list(((message.get("params") or {}).get("command")) or [])
                i = ix.init_interaction(mctx.hop(), registered=True, command=command, jsonrpc_id=req_id)
                i.meta["mcp.transport"] = "stdio"
                try:
                    verdict = await self.governor._evaluate(mctx, i)
                except Exception:
                    log.exception("stdio launch check failed server=%s", server)
                    return {"action": "respond", "message": jsonrpc_error(
                        req_id, -32603, "[Aegis] launch check unavailable (fail-closed)"),
                            "decision_id": None}
                gv = GovVerdict("forward", message, decision_id=verdict.id,
                                final_action=verdict.action, interaction=i, verdict=verdict)
                if verdict.action in ("block", "require_approval"):
                    cid, reason = ix.primary_of(verdict)
                    await self.governor.complete(mctx, gv, Outcome(status_code=403, usage=Usage(requests=0)))
                    return {"action": "respond", "message": jsonrpc_error(
                        req_id, UNKNOWN_SERVER, f"[Aegis] Blocked by {cid}: {reason}"),
                            "decision_id": verdict.id}
                await self.governor.complete(mctx, gv, Outcome(status_code=200, usage=Usage(requests=0)))
                return {"action": "forward", "message": message, "decision_id": verdict.id}
            if is_request(message) and message.get("method") == "initialize":
                self._stdio_era[key] = LEGACY
            elif is_request(message):
                self._stdio_era[key] = detect_era({}, message)
                mctx.era = self._stdio_era[key]
            gv = await self.governor.on_client_message(mctx, message)
            if gv.action == "forward" and is_request(gv.message):
                pend = self._stdio_pending.setdefault(key, {})
                pend[gv.message.get("id")] = (gv.message, gv)
                self._stdio_pending.move_to_end(key)
                while len(self._stdio_pending) > 256:
                    self._stdio_pending.popitem(last=False)
                if len(pend) > 1024:
                    pend.pop(next(iter(pend)))
            return {"action": gv.action, "message": gv.message, "decision_id": gv.decision_id}
        # direction "in": server -> client
        request, gv2 = None, None
        if is_response(message):
            pair = self._stdio_pending.get(key, {}).pop(message.get("id"), None)
            if pair is not None:
                request, gv2 = pair
        new = await self.governor.on_server_message(mctx, message, request, gv2)
        if gv2 is not None:
            await self.governor.complete(mctx, gv2, Outcome(status_code=200,
                                                            usage=Usage(requests=1, tool_calls=1)))
        return {"action": "forward", "message": new,
                "decision_id": gv2.decision_id if gv2 else None}


__all__ = ["MODERN", "McpService", "get_service", "set_service"]
