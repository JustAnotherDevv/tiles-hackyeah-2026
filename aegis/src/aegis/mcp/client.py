"""Raw JSON-RPC MCP client over Streamable HTTP (public import surface `aegis.mcp.client`).

    async with McpHttpClient("http://127.0.0.1:8787", "marketpulse",
                             headers={"X-Aegis-Agent": "trading-copilot@trading"}) as c:
        tools = await c.list_tools()
        result = await c.call_tool("purchase_subscription",
                                   {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50},
                                   wait_s=30)

Speaks the 2026-07-28 ("modern") era by default: `params._meta` envelope plus the mirrored
routing headers `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`, `Mcp-Param-*` (from the tool's
input schema, learned via `list_tools`). Falls back to the legacy era (initialize handshake +
`Mcp-Session-Id` + DELETE) when the server rejects the modern envelope, or when `era="legacy"`.
A bare `tools/call` without the era headers / `_meta` fails upstream - always use this client
(or the official SDK) to talk MCP.
"""

from __future__ import annotations

import itertools
import json
import logging
from typing import Any

import httpx

from aegis.mcp.jsonrpc import (
    LEGACY,
    LEGACY_VERSION,
    MODERN,
    MODERN_VERSION,
    NAME_BEARING_METHODS,
    encode_header_value,
    modern_meta,
    param_headers_for,
    parse_sse_text,
)

log = logging.getLogger(__name__)


class McpClientError(Exception):
    """JSON-RPC error (or non-JSON-RPC HTTP failure) returned by the server/gateway."""

    def __init__(
        self, code: int | None, message: str, *, status: int | None = None, data: Any = None
    ) -> None:
        super().__init__(f"{code}: {message}" if code is not None else message)
        self.code = code
        self.message = message
        self.status = status
        self.data = data


class McpHttpClient:
    """Minimal Streamable HTTP MCP client (both eras). Not thread-safe; one per task."""

    def __init__(
        self,
        base_url: str,
        server: str,
        headers: dict[str, str] | None = None,
        *,
        url: str | None = None,
        client: httpx.AsyncClient | None = None,
        era: str = "auto",
        timeout: float = 120.0,
        client_name: str = "aegis-mcp-client",
    ) -> None:
        self.server = server
        self.url = url or f"{base_url.rstrip('/')}/mcp/{server}"
        self.headers = {k: v for k, v in (headers or {}).items() if v is not None}
        self._owned = client is None
        self._http = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0))
        self.era = MODERN if era in ("auto", MODERN, MODERN_VERSION) else LEGACY
        self._auto = era == "auto"
        self.session_id: str | None = None
        self._initialized = False
        self._ids = itertools.count(1)
        self.schemas: dict[str, dict[str, Any]] = {}
        self.client_name = client_name
        self.last_status: int | None = None
        self.last_headers: dict[str, str] = {}

    async def __aenter__(self) -> McpHttpClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self.era == LEGACY and self.session_id:
            try:
                await self._http.delete(self.url, headers=self._base_headers(None))
            except httpx.HTTPError:
                pass
            self.session_id = None
        if self._owned:
            await self._http.aclose()

    # ------------------------------------------------------------------ public API
    async def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(50):  # pagination guard
            params: dict[str, Any] = {"cursor": cursor} if cursor else {}
            result = await self.request("tools/list", params)
            page = list(result.get("tools") or [])
            tools += page
            cursor = result.get("nextCursor")
            if not cursor:
                break
        self.schemas = {str(t.get("name")): t.get("inputSchema") or {} for t in tools}
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        wait_s: float | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        """Return the tool result dict (`content`, `isError`, `structuredContent`, `_meta`)."""
        extra: dict[str, str] = {}
        if wait_s is not None:
            extra["X-Aegis-Wait"] = str(wait_s)
        if approval_id:
            extra["X-Aegis-Approval"] = approval_id
        return await self.request("tools/call", {"name": name, "arguments": arguments or {}}, extra)

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        params = dict(params or {})
        if self.era == MODERN:
            try:
                return await self._modern(method, params, extra_headers)
            except McpClientError as e:
                if (
                    not self._auto
                    or e.code in (-32001, -32002, -32020)
                    or e.status in (403, 404, 502)
                ):
                    raise
                log.debug("modern era rejected (%s); falling back to legacy", e)
                self.era = LEGACY
        await self._ensure_initialized()
        return await self._legacy(method, params, extra_headers)

    # ------------------------------------------------------------------ eras
    def _base_headers(self, version: str | None) -> dict[str, str]:
        h = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            **self.headers,
        }
        if version:
            h["mcp-protocol-version"] = version
        if self.session_id:
            h["mcp-session-id"] = self.session_id
        return h

    async def _modern(
        self, method: str, params: dict[str, Any], extra: dict[str, str] | None
    ) -> dict[str, Any]:
        rid = next(self._ids)
        body = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": {**params, "_meta": modern_meta(self.client_name)},
        }
        headers = self._base_headers(MODERN_VERSION)
        headers["mcp-method"] = method
        if (key := NAME_BEARING_METHODS.get(method)) and params.get(key) is not None:
            headers["mcp-name"] = encode_header_value(str(params[key]))
        if method == "tools/call":
            schema = self.schemas.get(str(params.get("name")))
            headers.update(param_headers_for(schema, params.get("arguments") or {}))
        headers.update(extra or {})
        return await self._post(body, headers, rid)

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        rid = next(self._ids)
        body = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": "initialize",
            "params": {
                "protocolVersion": LEGACY_VERSION,
                "capabilities": {},
                "clientInfo": {"name": self.client_name, "version": "0.1"},
            },
        }
        await self._post(body, self._base_headers(None), rid)
        sid = self.last_headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        resp = await self._http.post(
            self.url, json=note, headers=self._base_headers(LEGACY_VERSION)
        )
        await resp.aread()
        self._initialized = True

    async def _legacy(
        self, method: str, params: dict[str, Any], extra: dict[str, str] | None
    ) -> dict[str, Any]:
        rid = next(self._ids)
        body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        headers = self._base_headers(LEGACY_VERSION)
        headers.update(extra or {})
        return await self._post(body, headers, rid)

    async def _post(
        self, body: dict[str, Any], headers: dict[str, str], rid: Any
    ) -> dict[str, Any]:
        resp = await self._http.post(self.url, content=json.dumps(body).encode(), headers=headers)
        text = (await resp.aread()).decode("utf-8", errors="replace")
        self.last_status = resp.status_code
        self.last_headers = {k.lower(): v for k, v in resp.headers.items()}
        msg = self._extract(text, resp.headers.get("content-type", ""), rid)
        if msg is None:
            raise McpClientError(
                None, f"HTTP {resp.status_code}: {text[:200]}", status=resp.status_code
            )
        if "error" in msg:
            err = msg["error"] or {}
            raise McpClientError(
                err.get("code"),
                str(err.get("message")),
                status=resp.status_code,
                data=err.get("data"),
            )
        return dict(msg.get("result") or {})

    @staticmethod
    def _extract(text: str, content_type: str, rid: Any) -> dict[str, Any] | None:
        if "text/event-stream" in content_type:
            for ev in parse_sse_text(text):
                msg = ev.json()
                if (
                    isinstance(msg, dict)
                    and msg.get("id") == rid
                    and ("result" in msg or "error" in msg)
                ):
                    return msg
            return None
        try:
            msg = json.loads(text) if text else None
        except json.JSONDecodeError:
            return None
        return msg if isinstance(msg, dict) else None


def result_text(result: dict[str, Any]) -> str:
    """Concatenated text content of a tool result."""
    return "\n".join(
        str(c.get("text", "")) for c in result.get("content") or [] if isinstance(c, dict)
    )


def aegis_decision(result: dict[str, Any]) -> dict[str, Any]:
    """`_meta["io.aegis/decision"]` of a tool result (empty dict if absent)."""
    return dict((result.get("_meta") or {}).get("io.aegis/decision") or {})


__all__ = ["McpClientError", "McpHttpClient", "aegis_decision", "result_text"]
