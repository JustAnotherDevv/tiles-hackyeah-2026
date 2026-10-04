"""Minimal MCP Streamable-HTTP clients for the SDK.

Two implementations behind one sync interface (`list_tools()`, `call_tool()`, `close()`):

- `AegisMcpBridge` (default): mcp-proxy's public `aegis.mcp.client.McpHttpClient` (modern era with
  legacy fallback, Addendum A-46), driven from a private background event loop so the sync SDK
  can keep one MCP session per server.
- `LegacyMcpSession` (fallback / tests): raw JSON-RPC, legacy era (`initialize` ->
  `notifications/initialized` -> `tools/*`, `Mcp-Session-Id`, DELETE on close). Accepts JSON or SSE
  replies (staging/spikes/mcp FINDINGS gotchas 1, 8, 9, 12). `isError` results are results, not
  JSON-RPC errors.

Both raise `McpRpcError` for JSON-RPC errors and `GatewayUnavailable` for transport failures.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import threading
from collections.abc import Coroutine
from typing import Any

import httpx

from aegis.sdk.results import GatewayUnavailable

LEGACY_PROTOCOL = "2025-11-25"


class McpRpcError(Exception):
    def __init__(self, code: int | None, message: str, *, status: int | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "http_status": self.status}


def iter_sse(text: str) -> list[tuple[str, str]]:
    """Parse an SSE body into (event, data) pairs (multi-line data joined with \\n)."""
    out: list[tuple[str, str]] = []
    event, data = "message", []
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line:
            if data:
                out.append((event, "\n".join(data)))
            event, data = "message", []
            continue
        if line.startswith(":"):
            continue
        key, _, val = line.partition(":")
        val = val[1:] if val.startswith(" ") else val
        if key == "event":
            event = val
        elif key == "data":
            data.append(val)
    if data:
        out.append((event, "\n".join(data)))
    return out


def extract_jsonrpc(text: str, content_type: str, rid: Any) -> dict[str, Any] | None:
    """The JSON-RPC response with id `rid` from a JSON or SSE body."""
    if "text/event-stream" in (content_type or ""):
        for _ev, data in iter_sse(text):
            try:
                msg = json.loads(data)
            except ValueError:
                continue
            if (
                isinstance(msg, dict)
                and msg.get("id") == rid
                and ("result" in msg or "error" in msg)
            ):
                return msg
        return None
    try:
        msg = json.loads(text) if text else None
    except ValueError:
        return None
    if isinstance(msg, list):  # batch
        msg = next((m for m in msg if isinstance(m, dict) and m.get("id") == rid), None)
    return msg if isinstance(msg, dict) else None


class LegacyMcpSession:
    """Sync legacy-era JSON-RPC session against `<url>` (one per server)."""

    def __init__(self, http: httpx.Client, url: str, headers: dict[str, str] | None = None) -> None:
        self.http = http
        self.url = url
        self.headers = dict(headers or {})
        self.session_id: str | None = None
        self.initialized = False
        self._ids = itertools.count(1)
        self.last_status: int | None = None

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            **self.headers,
        }
        if self.initialized:
            h["mcp-protocol-version"] = LEGACY_PROTOCOL
        if self.session_id:
            h["mcp-session-id"] = self.session_id
        h.update(extra or {})
        return h

    def _post(self, body: dict[str, Any], extra: dict[str, str] | None = None) -> httpx.Response:
        try:
            return self.http.post(self.url, content=json.dumps(body), headers=self._headers(extra))
        except httpx.HTTPError as e:
            raise GatewayUnavailable(0, "unavailable", f"MCP transport error: {e}") from e

    def _rpc(
        self, method: str, params: dict[str, Any], extra: dict[str, str] | None = None
    ) -> dict[str, Any]:
        rid = next(self._ids)
        resp = self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}, extra)
        self.last_status = resp.status_code
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        msg = extract_jsonrpc(resp.text, resp.headers.get("content-type", ""), rid)
        if msg is None:
            raise McpRpcError(
                None, f"HTTP {resp.status_code}: {resp.text[:200]}", status=resp.status_code
            )
        if "error" in msg:
            err = msg.get("error") or {}
            raise McpRpcError(err.get("code"), str(err.get("message")), status=resp.status_code)
        return dict(msg.get("result") or {})

    def ensure(self) -> None:
        if self.initialized:
            return
        self._rpc(
            "initialize",
            {
                "protocolVersion": LEGACY_PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "aegis-sdk", "version": "0.1"},
            },
        )
        self.initialized = True
        try:
            self.http.post(
                self.url,
                content=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                headers=self._headers(),
            )
        except httpx.HTTPError as e:
            raise GatewayUnavailable(0, "unavailable", f"MCP transport error: {e}") from e

    def list_tools(self) -> list[dict[str, Any]]:
        self.ensure()
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(50):
            result = self._rpc("tools/list", {"cursor": cursor} if cursor else {})
            tools += list(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        wait_s: float | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        self.ensure()
        extra: dict[str, str] = {}
        params: dict[str, Any] = {"name": name, "arguments": arguments or {}}
        if wait_s is not None:
            extra["x-aegis-wait"] = str(wait_s)
        if approval_id:
            extra["x-aegis-approval"] = approval_id
            params["_meta"] = {"io.aegis/approval_id": approval_id}
        return self._rpc("tools/call", params, extra)

    def close(self) -> None:
        if self.session_id:
            try:
                self.http.delete(self.url, headers=self._headers())
            except httpx.HTTPError:
                pass
        self.session_id = None
        self.initialized = False


class _LoopThread:
    """A private asyncio loop in a daemon thread (sync -> async bridge)."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self.loop.run_forever, name="aegis-sdk-mcp", daemon=True
        )
        self.thread.start()

    def run(self, coro: Coroutine[Any, Any, Any], timeout: float | None = None) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def stop(self) -> None:
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)
        if not self.loop.is_running():
            self.loop.close()


class AegisMcpBridge:
    """Sync facade over `aegis.mcp.client.McpHttpClient` (one client per server)."""

    def __init__(self, base_url: str, server: str, headers: dict[str, str], timeout: float) -> None:
        from aegis.mcp.client import McpHttpClient  # public surface (A-46); ImportError -> fallback

        self._loop = _LoopThread()
        self.timeout = timeout

        async def _make() -> Any:
            return McpHttpClient(
                base_url, server, headers=headers, timeout=timeout, client_name="aegis-sdk"
            )

        self._client = self._loop.run(_make())

    def _call(self, coro: Coroutine[Any, Any, Any]) -> Any:
        try:
            return self._loop.run(coro, timeout=self.timeout + 5)
        except httpx.HTTPError as e:
            raise GatewayUnavailable(0, "unavailable", f"MCP transport error: {e}") from e
        except Exception as e:  # McpClientError -> McpRpcError
            if type(e).__name__ == "McpClientError":
                raise McpRpcError(
                    getattr(e, "code", None),
                    str(getattr(e, "message", e)),
                    status=getattr(e, "status", None),
                ) from e
            raise

    def list_tools(self) -> list[dict[str, Any]]:
        return self._call(self._client.list_tools())

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        wait_s: float | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        return self._call(
            self._client.call_tool(name, arguments or {}, wait_s=wait_s, approval_id=approval_id)
        )

    def close(self) -> None:
        try:
            self._loop.run(self._client.close(), timeout=5)
        except Exception:
            pass
        self._loop.stop()


__all__ = [
    "LEGACY_PROTOCOL",
    "AegisMcpBridge",
    "LegacyMcpSession",
    "McpRpcError",
    "extract_jsonrpc",
    "iter_sse",
]
