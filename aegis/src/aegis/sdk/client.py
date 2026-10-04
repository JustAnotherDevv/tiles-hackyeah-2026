"""`AegisClient` — the data-plane client used by demo agents, scenes and tests (sync, httpx).

    from aegis.sdk import AegisClient
    c = AegisClient(agent_id="trading-copilot@trading")          # seed key looked up from the cast
    r = c.chat("Draft a reply to Jan Kowalski, PESEL 44051401359", model="mock-sonnet")
    r.action, r.text, r.decision_id                                 # "redact", rehydrated text, dec_…
    m = c.mcp_call("marketpulse", "purchase_subscription",
                   {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50},
                   await_approval_s=120)                            # hold -> wait -> retry (A-23)

Identity: `Authorization: Bearer <agent key>` + `X-Aegis-Agent` (+ `X-Aegis-Member`, `X-Aegis-Team`,
`X-Aegis-Session`). Provider keys are never sent; they live only in the gateway.

Model proxies answer policy blocks / pending approvals with a **synthetic 200** reply, so
`chat()` returns a `ChatResult` whose `action` comes from `X-Aegis-Decision` (no exception unless
`raise_for_policy=True`). 401/402/403/429/5xx map to typed errors (`aegis.sdk.results`).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from typing import Any

import httpx

from aegis.sdk.cast import (
    DEFAULT_VIEWER,
    DEMO_AGENT_SPONSORS,
    DEMO_AGENT_TEAMS,
    agent_key,
    default_url,
)
from aegis.sdk.mcp import AegisMcpBridge, LegacyMcpSession, McpRpcError, iter_sse
from aegis.sdk.results import (
    AegisError,
    ApprovalRequired,
    ChatResult,
    EgressResult,
    GatewayUnavailable,
    GuardResult,
    McpResult,
    NotFound,
    PolicyBlocked,
    approval_from_text,
    control_from_text,
    error_from_response,
    mcp_result_from,
)

_SURFACE_KIND = {
    "prompt.user": "model_call",
    "model.request": "model_call",
    "model.response": "model_call",
    "model.admin": "model_call",
    "tool.input": "tool_call",
    "tool.output": "tool_call",
    "artifact.file": "model_call",
    "mcp.init": "mcp",
    "mcp.list": "mcp",
    "mcp.call": "mcp",
    "mcp.result": "mcp",
    "egress.request": "egress",
    "egress.response": "egress",
    "a2a.message": "a2a",
    "a2a.result": "a2a",
    "config.change": "config_change",
}

_DONE_STATUSES = frozenset({"approved", "denied", "expired", "cancelled"})


def kind_for_surface(surface: str) -> str:
    return _SURFACE_KIND.get(surface, "tool_call")


def _lower(headers: httpx.Headers | dict[str, str]) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


def _json_or_text(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text


class AegisClient:
    """Sync data-plane client (`/v1/guard`, model proxies, `/mcp/*`, `/egress`)."""

    def __init__(
        self,
        base_url: str | None = None,
        agent_id: str | None = None,
        agent_key: str | None = None,
        *,
        session_id: str | None = None,
        member_id: str | None = None,
        team_id: str | None = None,
        timeout: float = 75.0,
        transport: httpx.BaseTransport | None = None,
        headers: dict[str, str] | None = None,
        mcp_impl: str = "auto",
    ) -> None:
        self.base_url = (base_url or default_url()).rstrip("/")
        self.agent_id = agent_id
        self.agent_key = agent_key if agent_key is not None else _seed_key(agent_id)
        self.session_id = session_id
        self.member_id = member_id
        self.team_id = team_id or (DEMO_AGENT_TEAMS.get(agent_id or "") if agent_id else None)
        self.timeout = timeout
        self.extra_headers = dict(headers or {})
        # "auto": aegis.mcp.client (A-46) unless a custom (sync) transport is injected (tests)
        self.mcp_impl = mcp_impl if mcp_impl != "auto" else ("sdk" if transport else "aegis")
        self._transport = transport
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=5.0),
            transport=transport,
            headers={"user-agent": "aegis-sdk/0.1"},
        )
        self._mcp: dict[str, Any] = {}

    # ------------------------------------------------------------------------------ lifecycle
    def __enter__(self) -> AegisClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        for sess in list(self._mcp.values()):
            try:
                sess.close()
            except Exception:
                pass
        self._mcp.clear()
        self._http.close()

    def new_session(self, prefix: str | None = None) -> str:
        """Start a fresh session id (`ses_<agent>_<ts>`) for subsequent calls."""
        name = (prefix or (self.agent_id or "sdk").split("@")[0]).replace("-", "_")
        self.session_id = f"ses_{name}_{int(time.time() * 1000)}"
        return self.session_id

    # ------------------------------------------------------------------------------ headers
    def identity_headers(self, session_id: str | None = None) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.agent_key:
            h["authorization"] = f"Bearer {self.agent_key}"
        if self.agent_id:
            h["x-aegis-agent"] = self.agent_id
        if self.member_id:
            h["x-aegis-member"] = self.member_id
        if self.team_id:
            h["x-aegis-team"] = self.team_id
        sid = session_id or self.session_id
        if sid:
            h["x-aegis-session"] = sid
        h.update(self.extra_headers)
        return h

    def _call_headers(
        self,
        *,
        approval_id: str | None = None,
        wait_s: float | None = None,
        session_id: str | None = None,
    ) -> dict[str, str]:
        h = self.identity_headers(session_id)
        if approval_id:
            h["x-aegis-approval"] = approval_id
        if wait_s is not None:
            h["x-aegis-wait"] = str(wait_s)
        return h

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            return self._http.request(method, path, **kw)
        except httpx.TimeoutException as e:
            raise GatewayUnavailable(0, "unavailable", f"timeout calling {path}: {e}") from e
        except httpx.HTTPError as e:
            raise GatewayUnavailable(
                0, "unavailable", f"gateway unreachable at {self.base_url} ({e})"
            ) from e

    # ------------------------------------------------------------------------------ /v1/guard
    def guard(
        self,
        *,
        kind: str | None = None,
        surface: str = "model.request",
        text: str | None = None,
        destination: str | dict[str, Any] | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        mcp_server: str | None = None,
        url: str | None = None,
        http_method: str | None = None,
        amount_usd: float | None = None,
        resource: str | None = None,
        action_type: str | None = None,
        labels: dict[str, str] | None = None,
        meta: dict[str, Any] | None = None,
        segments: list[dict[str, Any]] | None = None,
        direction: str | None = None,
        dry_run: bool = False,
        wait_s: float | None = None,
        approval_id: str | None = None,
        session_id: str | None = None,
        await_approval_s: float = 0.0,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> GuardResult:
        """`POST /v1/guard` (always 200). `kind` defaults from `surface`."""
        interaction: dict[str, Any] = {
            "kind": kind or kind_for_surface(surface),
            "surface": surface,
        }
        for key, val in (
            ("direction", direction),
            ("destination", destination),
            ("model", model),
            ("tool_name", tool_name),
            ("tool_args", tool_args),
            ("mcp_server", mcp_server),
            ("url", url),
            ("http_method", http_method),
            ("text", text),
            ("segments", segments),
            ("amount_usd", amount_usd),
            ("resource", resource),
            ("action_type", action_type),
            ("labels", labels),
            ("meta", meta),
        ):
            if val is not None:
                interaction[key] = val
        body: dict[str, Any] = {"interaction": interaction, "dry_run": bool(dry_run)}
        ident = {
            k: v
            for k, v in (
                ("agent_id", self.agent_id),
                ("member_id", self.member_id),
                ("team_id", self.team_id),
            )
            if v
        }
        if ident:
            body["identity"] = ident
        sid = session_id or self.session_id
        if sid:
            body["session_id"] = sid
        if wait_s is not None:
            body["wait_s"] = wait_s
        if approval_id:
            body["approval_id"] = approval_id

        t0 = time.perf_counter()
        resp = self._request(
            "POST",
            "/v1/guard",
            json=body,
            headers=self._call_headers(approval_id=approval_id, wait_s=wait_s, session_id=sid),
        )
        elapsed = (time.perf_counter() - t0) * 1000
        headers = _lower(resp.headers)
        if resp.status_code >= 400:
            raise error_from_response(resp.status_code, _json_or_text(resp), headers)
        data = _json_or_text(resp)
        data = data if isinstance(data, dict) else {}
        verdict = dict(data.get("verdict") or {})
        primary = verdict.get("primary") or {}
        result = GuardResult(
            action=str(verdict.get("action") or headers.get("x-aegis-decision") or "allow"),
            decision_id=data.get("decision_id")
            or verdict.get("id")
            or headers.get("x-aegis-decision-id"),
            verdict=verdict,
            text=data.get("text"),
            segments=list(data.get("segments") or verdict.get("segments") or []),
            approval=data.get("approval") or verdict.get("approval"),
            control_id=primary.get("control_id"),
            reason=primary.get("reason"),
            status_code=resp.status_code,
            headers=headers,
            server_timing=headers.get("server-timing"),
            elapsed_ms=elapsed,
            raw=data,
        )
        if result.pending and await_approval_s > 0 and result.approval_id and not dry_run:
            final = self.wait_for_approval(
                result.approval_id, timeout=await_approval_s, on_update=on_update
            )
            if final.get("status") == "approved":
                return self.guard(
                    kind=kind,
                    surface=surface,
                    text=text,
                    destination=destination,
                    model=model,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    mcp_server=mcp_server,
                    url=url,
                    http_method=http_method,
                    amount_usd=amount_usd,
                    resource=resource,
                    action_type=action_type,
                    labels=labels,
                    meta=meta,
                    segments=segments,
                    direction=direction,
                    approval_id=result.approval_id,
                    session_id=sid,
                )
            result.approval = final or result.approval
        return result

    def complete(
        self, decision_id: str, status_code: int = 200, usage: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """`POST /v1/guard/complete` — settle budgets for an externally executed call."""
        resp = self._request(
            "POST",
            "/v1/guard/complete",
            json={"decision_id": decision_id, "status_code": status_code, "usage": usage or {}},
            headers=self.identity_headers(),
        )
        if resp.status_code >= 400:
            raise error_from_response(resp.status_code, _json_or_text(resp), _lower(resp.headers))
        data = _json_or_text(resp)
        return data if isinstance(data, dict) else {"ok": True}

    # ------------------------------------------------------------------------------ model proxies
    def chat(
        self,
        messages: str | list[dict[str, Any]],
        *,
        model: str = "mock-sonnet",
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 512,
        stream: bool = False,
        wire: str = "openai",
        approval_id: str | None = None,
        wait_s: float | None = None,
        system: str | None = None,
        session_id: str | None = None,
        raise_for_policy: bool = False,
        await_approval_s: float = 0.0,
        on_update: Callable[[dict[str, Any]], None] | None = None,
        **extra: Any,
    ) -> ChatResult:
        """Chat through the gateway: `wire="openai"` (/v1/chat/completions), `"anthropic"`
        (/v1/messages) or `"ollama"` (/ollama/api/chat)."""
        msgs = (
            [{"role": "user", "content": messages}] if isinstance(messages, str) else list(messages)
        )
        path, body = _build_chat_body(wire, msgs, model, tools, max_tokens, stream, system, extra)
        headers = self._call_headers(approval_id=approval_id, wait_s=wait_s, session_id=session_id)
        if wire == "anthropic":
            headers.setdefault("anthropic-version", "2023-06-01")
        t0 = time.perf_counter()
        if stream:
            try:
                with self._http.stream("POST", path, json=body, headers=headers) as resp:
                    raw_text = "".join(resp.iter_text())
                    status, rheaders = resp.status_code, _lower(resp.headers)
            except httpx.HTTPError as e:
                raise GatewayUnavailable(0, "unavailable", f"gateway unreachable ({e})") from e
        else:
            resp = self._request("POST", path, json=body, headers=headers)
            raw_text, status, rheaders = resp.text, resp.status_code, _lower(resp.headers)
        elapsed = (time.perf_counter() - t0) * 1000

        if status >= 400:
            try:
                err_body: Any = json.loads(raw_text)
            except ValueError:
                err_body = raw_text
            raise error_from_response(status, err_body, rheaders)

        result = _parse_chat(wire, raw_text, rheaders.get("content-type", ""), stream)
        result.status_code, result.headers, result.elapsed_ms = status, rheaders, elapsed
        result.stream = stream
        result.model = result.model or model
        _apply_aegis_headers(result, rheaders)
        if raise_for_policy and result.blocked:
            raise PolicyBlocked(
                200,
                "policy_blocked",
                result.text,
                {"control_id": result.control_id, "decision_id": result.decision_id},
            )
        if raise_for_policy and result.pending:
            raise ApprovalRequired(
                200,
                "approval_required",
                result.text,
                {"approval_id": result.approval_id, "decision_id": result.decision_id},
            )
        if result.pending and await_approval_s > 0 and result.approval_id:
            final = self.wait_for_approval(
                result.approval_id, timeout=await_approval_s, on_update=on_update
            )
            if final.get("status") == "approved":
                return self.chat(
                    msgs,
                    model=model,
                    tools=tools,
                    max_tokens=max_tokens,
                    stream=stream,
                    wire=wire,
                    approval_id=result.approval_id,
                    system=system,
                    session_id=session_id,
                    **extra,
                )
        return result

    def messages(self, messages: str | list[dict[str, Any]], **kw: Any) -> ChatResult:
        """Anthropic Messages wire (`/v1/messages`)."""
        kw.setdefault("model", "mock-sonnet")
        return self.chat(messages, wire="anthropic", **kw)

    def ollama_chat(self, messages: str | list[dict[str, Any]], **kw: Any) -> ChatResult:
        """Ollama native wire (`/ollama/api/chat`); default model `aegis-judge` (local)."""
        kw.setdefault("model", "aegis-judge")
        return self.chat(messages, wire="ollama", **kw)

    # ------------------------------------------------------------------------------ MCP
    def _mcp_session(self, server: str) -> Any:
        sess = self._mcp.get(server)
        if sess is not None:
            return sess
        headers = self.identity_headers()
        if self.mcp_impl == "aegis":
            try:
                sess = AegisMcpBridge(self.base_url, server, headers, self.timeout)
            except ImportError:  # TODO(integration): aegis.mcp.client missing -> legacy fallback
                self.mcp_impl = "sdk"
        if sess is None:
            sess = LegacyMcpSession(self._http, f"{self.base_url}/mcp/{server}", headers)
        self._mcp[server] = sess
        return sess

    def mcp_list(self, server: str) -> McpResult:
        """`tools/list` through `/mcp/{server}` -> `McpResult.tools`."""
        t0 = time.perf_counter()
        try:
            tools = self._mcp_session(server).list_tools()
        except McpRpcError as e:
            self._mcp.pop(server, None)
            res = mcp_result_from(server, "tools/list", None, error=e.as_dict())
            res.elapsed_ms = (time.perf_counter() - t0) * 1000
            return res
        res = mcp_result_from(server, "tools/list", {"tools": tools})
        res.elapsed_ms = (time.perf_counter() - t0) * 1000
        return res

    def mcp_call(
        self,
        server: str,
        tool: str,
        arguments: dict[str, Any] | None = None,
        *,
        approval_id: str | None = None,
        wait_s: float | None = None,
        await_approval_s: float = 0.0,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> McpResult:
        """`tools/call` through `/mcp/{server}`. `tool` may be `name` or `server.name`.

        Blocked / pending results come back as `isError` results (A-46); the verdict is parsed from
        `_meta["io.aegis/decision"]` or the `[Aegis] ...` text. With `await_approval_s > 0`, a
        pending call waits for a human decision and is retried with `X-Aegis-Approval` (A-23).
        """
        name = tool[len(server) + 1 :] if tool.startswith(f"{server}.") else tool
        t0 = time.perf_counter()
        try:
            result = self._mcp_session(server).call_tool(
                name, arguments or {}, wait_s=wait_s, approval_id=approval_id
            )
            res = mcp_result_from(server, name, result)
        except McpRpcError as e:
            self._mcp.pop(server, None)
            res = mcp_result_from(server, name, None, error=e.as_dict())
        res.elapsed_ms = (time.perf_counter() - t0) * 1000
        if res.pending and await_approval_s > 0 and res.approval_id:
            final = self.wait_for_approval(
                res.approval_id, timeout=await_approval_s, on_update=on_update
            )
            if final.get("status") == "approved":
                return self.mcp_call(server, name, arguments, approval_id=res.approval_id)
            res.decision = {**res.decision, "approval": final}
        return res

    # ------------------------------------------------------------------------------ /egress
    def egress(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        body: str | None = None,
        tool_name: str | None = None,
        wait_s: float | None = None,
        approval_id: str | None = None,
        raise_errors: bool = True,
        await_approval_s: float = 0.0,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> EgressResult:
        """`POST /egress` (third-party HTTP through Aegis). 403/402/429/401 -> typed errors
        (or an `EgressResult` carrying `.error` when `raise_errors=False`)."""
        payload: dict[str, Any] = {"method": method.upper(), "url": url}
        if headers:
            payload["headers"] = headers
        if json is not None:
            payload["json"] = json
        if body is not None:
            payload["body"] = body
        if tool_name:
            payload["tool_name"] = tool_name
        if wait_s is not None:
            payload["wait_s"] = wait_s
        t0 = time.perf_counter()
        resp = self._request(
            "POST",
            "/egress",
            json=payload,
            headers=self._call_headers(approval_id=approval_id, wait_s=wait_s),
        )
        elapsed = (time.perf_counter() - t0) * 1000
        rheaders = _lower(resp.headers)
        data = _json_or_text(resp)
        if resp.status_code >= 400:
            err = error_from_response(resp.status_code, data, rheaders)
            if isinstance(err, ApprovalRequired) and await_approval_s > 0 and err.approval_id:
                final = self.wait_for_approval(
                    err.approval_id, timeout=await_approval_s, on_update=on_update
                )
                if final.get("status") == "approved":
                    return self.egress(
                        method,
                        url,
                        json=json,
                        headers=headers,
                        body=body,
                        tool_name=tool_name,
                        approval_id=err.approval_id,
                        raise_errors=raise_errors,
                    )
            if raise_errors:
                raise err
            return EgressResult(
                action=err.action,
                status_code=resp.status_code,
                decision_id=err.decision_id,
                control_id=err.control_id,
                approval_id=err.approval_id,
                required_role=err.required_role,
                expires_at=err.expires_at,
                error=err,
                raw=data,
                elapsed_ms=elapsed,
            )
        data = data if isinstance(data, dict) else {"body": data}
        return EgressResult(
            action=rheaders.get("x-aegis-decision") or "allow",
            status=data.get("status"),
            status_code=resp.status_code,
            headers=dict(data.get("headers") or {}),
            body=data.get("body"),
            decision_id=data.get("decision_id") or rheaders.get("x-aegis-decision-id"),
            redactions=data.get("redactions"),
            raw=data,
            elapsed_ms=elapsed,
        )

    # ------------------------------------------------------------------------------ approvals
    def approval(self, approval_id: str, *, view_as: str | None = None) -> dict[str, Any]:
        resp = self._request(
            "GET", f"/api/approvals/{approval_id}", headers=self._viewer_headers(view_as)
        )
        if resp.status_code >= 400:
            raise error_from_response(resp.status_code, _json_or_text(resp), _lower(resp.headers))
        data = _json_or_text(resp)
        return data if isinstance(data, dict) else {}

    def _viewer_headers(self, view_as: str | None) -> dict[str, str]:
        viewer = (
            view_as
            or self.member_id
            or DEMO_AGENT_SPONSORS.get(self.agent_id or "")
            or DEFAULT_VIEWER
        )
        return {"x-aegis-view-as": viewer}

    def wait_for_approval(
        self,
        approval_id: str,
        timeout: float = 120.0,
        poll_s: float = 1.0,
        on_update: Callable[[dict[str, Any]], None] | None = None,
        *,
        view_as: str | None = None,
    ) -> dict[str, Any]:
        """Block until approval `approval_id` is decided (or `timeout`). Returns the last
        `ApprovalRequest` JSON seen. Uses the long-poll `GET /api/approvals/{id}/wait` (A-23),
        falling back to polling `GET /api/approvals/{id}` when the route is missing."""
        deadline = time.monotonic() + max(0.0, timeout)
        last: dict[str, Any] = {"id": approval_id, "status": "pending"}
        long_poll = True
        while True:
            remaining = deadline - time.monotonic()
            if long_poll:
                chunk = max(1, min(25, int(remaining))) if remaining > 0 else 1
                try:
                    resp = self._http.get(
                        f"/api/approvals/{approval_id}/wait",
                        params={"timeout_s": chunk},
                        headers=self._viewer_headers(view_as),
                        timeout=httpx.Timeout(chunk + 10, connect=5.0),
                    )
                except httpx.HTTPError as e:
                    raise GatewayUnavailable(0, "unavailable", f"gateway unreachable ({e})") from e
                body = _json_or_text(resp)
                if resp.status_code in (404, 405) and not (
                    isinstance(body, dict) and isinstance(body.get("error"), dict)
                ):
                    long_poll = False  # TODO(integration): /wait missing -> poll
                    continue
                if resp.status_code >= 400:
                    err = error_from_response(resp.status_code, body, _lower(resp.headers))
                    if isinstance(err, NotFound):
                        raise err
                    raise err
                data = body if isinstance(body, dict) else {}
            else:
                data = self.approval(approval_id, view_as=view_as)
            if data:
                changed = data.get("status") != last.get("status") or data.get("votes") != last.get(
                    "votes"
                )
                last = data
                if on_update is not None and changed:
                    on_update(data)
            if last.get("status") in _DONE_STATUSES:
                return last
            if time.monotonic() >= deadline:
                return last
            if not long_poll:
                time.sleep(min(poll_s, max(0.05, deadline - time.monotonic())))


# ---------------------------------------------------------------------------------------- helpers
def _seed_key(agent_id: str | None) -> str | None:
    return agent_key(agent_id)


def _openai_tools(tools: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools:
        if "function" in t or t.get("type") == "function":
            out.append(t)
        else:
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name"),
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema")
                        or t.get("parameters")
                        or {"type": "object", "properties": {}},
                    },
                }
            )
    return out


def _anthropic_tools(tools: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools:
        fn = t.get("function")
        if isinstance(fn, dict):
            out.append(
                {
                    "name": fn.get("name"),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        else:
            out.append(
                {
                    "name": t.get("name"),
                    "description": t.get("description", ""),
                    "input_schema": t.get("input_schema")
                    or t.get("parameters")
                    or {"type": "object", "properties": {}},
                }
            )
    return out


def _build_chat_body(
    wire: str,
    msgs: list[dict[str, Any]],
    model: str,
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    stream: bool,
    system: str | None,
    extra: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if wire == "anthropic":
        sys_parts = [system] if system else []
        conv = []
        for m in msgs:
            if m.get("role") == "system":
                sys_parts.append(str(m.get("content") or ""))
            else:
                conv.append(m)
        body: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": conv}
        if sys_parts:
            body["system"] = "\n\n".join(sys_parts)
        if tools:
            body["tools"] = _anthropic_tools(tools)
        if stream:
            body["stream"] = True
        body.update(extra)
        return "/v1/messages", body
    if wire == "ollama":
        conv = ([{"role": "system", "content": system}] if system else []) + msgs
        options = dict(extra.pop("options", {}) or {})
        options.setdefault("num_predict", max_tokens)
        body = {"model": model, "messages": conv, "stream": bool(stream), "options": options}
        if tools:
            body["tools"] = _openai_tools(tools)
        body.update(extra)
        return "/ollama/api/chat", body
    if wire != "openai":
        raise ValueError(f"unknown wire {wire!r} (openai | anthropic | ollama)")
    conv = ([{"role": "system", "content": system}] if system else []) + msgs
    body = {"model": model, "messages": conv, "max_tokens": max_tokens}
    if tools:
        body["tools"] = _openai_tools(tools)
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    body.update(extra)
    return "/v1/chat/completions", body


def _parse_chat(wire: str, text: str, content_type: str, stream: bool) -> ChatResult:
    if wire == "anthropic":
        if stream or "text/event-stream" in content_type:
            return _parse_anthropic_sse(text)
        return _parse_anthropic_json(_loads(text))
    if wire == "ollama":
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if stream or len(lines) > 1:
            return _parse_ollama_ndjson(lines)
        return _parse_ollama_ndjson(lines[:1])
    if stream or "text/event-stream" in content_type:
        return _parse_openai_sse(text)
    return _parse_openai_json(_loads(text))


def _loads(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {"_text": text}
    return data if isinstance(data, dict) else {"_data": data}


def _parse_anthropic_json(data: dict[str, Any]) -> ChatResult:
    texts, tools = [], []
    for block in data.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            texts.append(str(block.get("text") or ""))
        elif block.get("type") == "tool_use":
            tools.append(
                {
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "input": block.get("input") or {},
                }
            )
    return ChatResult(
        wire="anthropic",
        model=data.get("model"),
        text="".join(texts) or str(data.get("_text") or ""),
        tool_calls=tools,
        stop_reason=data.get("stop_reason"),
        usage=dict(data.get("usage") or {}),
        raw=data,
    )


def _parse_anthropic_sse(text: str) -> ChatResult:
    blocks: dict[int, dict[str, Any]] = {}
    usage: dict[str, Any] = {}
    model, stop_reason, events = None, None, []
    for ev, data in iter_sse(text):
        try:
            obj = json.loads(data)
        except ValueError:
            continue
        events.append(obj)
        typ = obj.get("type", ev)
        if typ == "message_start":
            msg = obj.get("message") or {}
            model = msg.get("model")
            usage.update(msg.get("usage") or {})
        elif typ == "content_block_start":
            cb = dict(obj.get("content_block") or {})
            cb["_json"] = ""
            blocks[int(obj.get("index", len(blocks)))] = cb
        elif typ == "content_block_delta":
            cb = blocks.setdefault(
                int(obj.get("index", 0)), {"type": "text", "text": "", "_json": ""}
            )
            d = obj.get("delta") or {}
            if d.get("type") == "text_delta":
                cb["text"] = str(cb.get("text") or "") + str(d.get("text") or "")
            elif d.get("type") == "input_json_delta":
                cb["_json"] += str(d.get("partial_json") or "")
        elif typ == "message_delta":
            stop_reason = (obj.get("delta") or {}).get("stop_reason") or stop_reason
            usage.update(obj.get("usage") or {})
        elif typ == "error":
            err = obj.get("error") or {}
            blocks[len(blocks)] = {
                "type": "text",
                "text": str(err.get("message") or ""),
                "_json": "",
            }
    texts, tools = [], []
    for _i, cb in sorted(blocks.items()):
        if cb.get("type") == "text":
            texts.append(str(cb.get("text") or ""))
        elif cb.get("type") == "tool_use":
            try:
                inp = json.loads(cb["_json"]) if cb.get("_json") else (cb.get("input") or {})
            except ValueError:
                inp = {"_raw": cb.get("_json")}
            tools.append({"id": cb.get("id"), "name": cb.get("name"), "input": inp})
    return ChatResult(
        wire="anthropic",
        model=model,
        text="".join(texts),
        tool_calls=tools,
        stop_reason=stop_reason,
        usage=usage,
        raw=events,
    )


def _parse_openai_json(data: dict[str, Any]) -> ChatResult:
    choice = (data.get("choices") or [{}])[0] or {}
    msg = choice.get("message") or {}
    tools = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            args = {"_raw": fn.get("arguments")}
        tools.append({"id": tc.get("id"), "name": fn.get("name"), "input": args})
    return ChatResult(
        wire="openai",
        model=data.get("model"),
        text=str(msg.get("content") or data.get("_text") or ""),
        tool_calls=tools,
        stop_reason=choice.get("finish_reason"),
        usage=dict(data.get("usage") or {}),
        raw=data,
    )


def _parse_openai_sse(text: str) -> ChatResult:
    parts: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    usage: dict[str, Any] = {}
    model, finish, chunks = None, None, []
    for _ev, data in iter_sse(text):
        if data.strip() == "[DONE]":
            continue
        try:
            obj = json.loads(data)
        except ValueError:
            continue
        chunks.append(obj)
        model = obj.get("model") or model
        if obj.get("usage"):
            usage = dict(obj["usage"])
        if isinstance(obj.get("error"), dict):
            parts.append(str(obj["error"].get("message") or ""))
        for ch in obj.get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("content"):
                parts.append(str(d["content"]))
            for tc in d.get("tool_calls") or []:
                slot = calls.setdefault(
                    int(tc.get("index", 0)), {"id": None, "name": None, "args": ""}
                )
                slot["id"] = tc.get("id") or slot["id"]
                fn = tc.get("function") or {}
                slot["name"] = fn.get("name") or slot["name"]
                slot["args"] += str(fn.get("arguments") or "")
            finish = ch.get("finish_reason") or finish
    tools = []
    for _i, slot in sorted(calls.items()):
        try:
            args = json.loads(slot["args"] or "{}")
        except ValueError:
            args = {"_raw": slot["args"]}
        tools.append({"id": slot["id"], "name": slot["name"], "input": args})
    return ChatResult(
        wire="openai",
        model=model,
        text="".join(parts),
        tool_calls=tools,
        stop_reason=finish,
        usage=usage,
        raw=chunks,
    )


def _parse_ollama_ndjson(lines: list[str]) -> ChatResult:
    parts, objs, usage = [], [], {}
    model, done_reason, tools = None, None, []
    for ln in lines:
        try:
            obj = json.loads(ln)
        except ValueError:
            continue
        objs.append(obj)
        model = obj.get("model") or model
        msg = obj.get("message") or {}
        if msg.get("content"):
            parts.append(str(msg["content"]))
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            tools.append({"id": tc.get("id"), "name": fn.get("name"), "input": fn.get("arguments")})
        if isinstance(obj.get("error"), str):
            parts.append(obj["error"])
        if obj.get("done"):
            done_reason = obj.get("done_reason") or "stop"
            for k in (
                "prompt_eval_count",
                "eval_count",
                "total_duration",
                "load_duration",
                "prompt_eval_duration",
                "eval_duration",
            ):
                if k in obj:
                    usage[k] = obj[k]
    return ChatResult(
        wire="ollama",
        model=model,
        text="".join(parts),
        tool_calls=tools,
        stop_reason=done_reason,
        usage=usage,
        raw=objs if len(objs) != 1 else objs[0],
    )


def _apply_aegis_headers(result: ChatResult, h: dict[str, str]) -> None:
    result.decision_id = h.get("x-aegis-decision-id")
    result.response_decision_id = h.get("x-aegis-response-decision-id")
    result.request_id = h.get("x-aegis-request-id")
    result.approval_id = h.get("x-aegis-approval-id") or None
    result.downgraded_from = h.get("x-aegis-downgraded-from")
    result.budget_remaining = h.get("x-aegis-budget-remaining")
    result.policy_version = h.get("x-aegis-policy-version")
    result.feed_serial = h.get("x-aegis-feed-serial")
    result.server_timing = h.get("server-timing")
    try:
        result.redaction_count = int(h.get("x-aegis-redactions") or 0)
    except ValueError:
        result.redaction_count = 0
    action = h.get("x-aegis-decision")
    is_aegis = result.text.lstrip().startswith("[Aegis]")
    if not action:
        if is_aegis and approval_from_text(result.text):
            action = "require_approval"
        elif is_aegis:
            action = "block"
        else:
            action = "allow"
    result.action = action
    if is_aegis or action in ("block", "require_approval"):
        result.control_id = control_from_text(result.text)
        result.approval_id = result.approval_id or approval_from_text(result.text)


__all__ = ["AegisClient", "AegisError", "kind_for_surface"]
