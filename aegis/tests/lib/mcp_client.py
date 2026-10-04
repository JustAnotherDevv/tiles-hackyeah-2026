"""Minimal MCP Streamable-HTTP JSON-RPC client (initialize, tools/list, tools/call).

Parses both `application/json` and `text/event-stream` replies; keeps `Mcp-Session-Id`.
"""

from __future__ import annotations

import itertools
import json
from typing import Any

import httpx

PROTOCOL = "2025-06-18"


def parse_reply(resp: httpx.Response) -> dict[str, Any] | None:
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        last = None
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                try:
                    last = json.loads(line[5:].strip())
                except ValueError:
                    continue
        return last
    try:
        return resp.json()
    except ValueError:
        return None


class McpClient:
    def __init__(self, gw: Any, server: str, *, who: str | None = None, session: str | None = None):
        self.gw = gw
        self.server = server
        self.who = who
        self.session = session
        self.mcp_session: str | None = None
        self._ids = itertools.count(1)

    def _post(self, payload: dict[str, Any]) -> tuple[httpx.Response, dict[str, Any] | None]:
        h = self.gw.headers(self.who, self.session, 0)
        h["Accept"] = "application/json, text/event-stream"
        h["MCP-Protocol-Version"] = PROTOCOL
        if self.mcp_session:
            h["Mcp-Session-Id"] = self.mcp_session
        r = self.gw.request("POST", f"/mcp/{self.server}", json=payload, headers=h)
        sid = r.headers.get("mcp-session-id")
        if sid:
            self.mcp_session = sid
        return r, parse_reply(r)

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        r, msg = self._post(
            {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or {}}
        )
        return {"status": r.status_code, "message": msg or {}, "headers": dict(r.headers)}

    def initialize(self) -> dict[str, Any]:
        out = self.rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "aegis-selftest", "version": "1"},
            },
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return out

    def list_tools(self) -> dict[str, Any]:
        return self.rpc("tools/list")

    def call(self, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.rpc("tools/call", {"name": tool, "arguments": args or {}})


__all__ = ["McpClient", "parse_reply"]
