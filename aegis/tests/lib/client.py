"""Synchronous gateway client used by every e2e suite (hermetic and live modes)."""

from __future__ import annotations

import secrets
import time
from typing import Any

import httpx

from tests.lib.identities import OWNER, headers_for

OUT_DIRECTION_IN = {
    "model.response",
    "tool.output",
    "mcp.result",
    "mcp.list",
    "egress.response",
    "artifact.file",
}

KIND_BY_SURFACE = {
    "prompt.user": "model_call",
    "model.request": "model_call",
    "model.response": "model_call",
    "model.admin": "model_call",
    "tool.input": "tool_call",
    "tool.output": "tool_call",
    "mcp.call": "mcp",
    "mcp.result": "mcp",
    "mcp.list": "mcp",
    "mcp.init": "mcp",
    "egress.request": "egress",
    "egress.response": "egress",
    "config.change": "config_change",
    "artifact.file": "model_call",
}


def new_session(prefix: str = "t") -> str:
    return f"{prefix}-{secrets.token_hex(2)}"


class Gateway:
    """Thin wrapper over httpx.Client with identity + session helpers."""

    def __init__(self, base_url: str, mode: str = "hermetic", timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.mode = mode
        self.http = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.errors_seen: list[tuple[str, int, str]] = []  # (path, status, body excerpt)

    def close(self) -> None:
        self.http.close()

    # ------------------------------------------------------------------ low level
    def headers(
        self,
        who: str | None = None,
        session: str | None = None,
        wait: int | None = 0,
        extra: dict[str, str] | None = None,
    ) -> dict[str, str]:
        h = dict(headers_for(who))
        if session:
            h["X-Aegis-Session"] = session
        if wait is not None:
            h["X-Aegis-Wait"] = str(wait)
        if extra:
            h.update(extra)
        return h

    def request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            self.errors_seen.append((path, r.status_code, r.text[:400]))
        return r

    def healthz(self) -> httpx.Response:
        return self.http.get("/healthz")

    # ------------------------------------------------------------------ data plane
    def guard(
        self,
        interaction: dict[str, Any],
        *,
        who: str | None = None,
        session: str | None = None,
        dry_run: bool = False,
        approval_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        surface = interaction.get("surface", "model.request")
        interaction.setdefault("kind", KIND_BY_SURFACE.get(surface, "model_call"))
        interaction.setdefault("direction", "in" if surface in OUT_DIRECTION_IN else "out")
        body: dict[str, Any] = {"interaction": interaction, "wait_s": 0, "dry_run": dry_run}
        if session:
            body["session_id"] = session
        if approval_id:
            body["approval_id"] = approval_id
        return self.request(
            "POST", "/v1/guard", json=body, headers=self.headers(who, session, 0, headers)
        )

    def anthropic(
        self,
        text: str,
        *,
        model: str = "mock-echo",
        who: str | None = None,
        session: str | None = None,
        stream: bool = False,
        max_tokens: int = 256,
        headers: dict[str, str] | None = None,
        body_extra: dict[str, Any] | None = None,
    ) -> httpx.Response:
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "stream": stream,
            "messages": [{"role": "user", "content": text}],
            **(body_extra or {}),
        }
        return self.request(
            "POST",
            "/v1/messages",
            json=body,
            headers={"anthropic-version": "2023-06-01", **self.headers(who, session, 0, headers)},
        )

    def openai(
        self,
        text: str,
        *,
        model: str = "mock-echo",
        who: str | None = None,
        session: str | None = None,
        stream: bool = False,
        max_tokens: int = 256,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "stream": stream,
            "messages": [{"role": "user", "content": text}],
        }
        return self.request(
            "POST",
            "/v1/chat/completions",
            json=body,
            headers=self.headers(who, session, 0, headers),
        )

    def ollama(
        self, path: str, body: dict[str, Any], *, who: str | None = None, session: str | None = None
    ) -> httpx.Response:
        return self.request(
            "POST", f"/ollama/{path.lstrip('/')}", json=body, headers=self.headers(who, session, 0)
        )

    def hook(
        self,
        payload: dict[str, Any],
        *,
        who: str | None = "claude-code@platform",
        session: str | None = None,
    ) -> httpx.Response:
        h = self.headers(who, session, 0)
        if payload.get("hook_event_name"):
            h["X-Aegis-Hook-Event"] = payload["hook_event_name"]
        return self.request("POST", "/v1/hooks/claude-code", json=payload, headers=h)

    def egress(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
        body: str | None = None,
        tool_name: str | None = None,
        who: str | None = None,
        session: str | None = None,
    ) -> httpx.Response:
        payload: dict[str, Any] = {"method": method, "url": url, "wait_s": 0}
        if json_body is not None:
            payload["json"] = json_body
        if body is not None:
            payload["body"] = body
        if tool_name:
            payload["tool_name"] = tool_name
        return self.request("POST", "/egress", json=payload, headers=self.headers(who, session, 0))

    # ------------------------------------------------------------------ dashboard API
    def api(
        self,
        method: str,
        path: str,
        *,
        view_as: str | None = OWNER,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        h = dict(headers or {})
        if view_as:
            h["X-Aegis-View-As"] = view_as
        return self.request(method, path, json=json, params=params, headers=h)

    def decision(self, decision_id: str) -> dict[str, Any] | None:
        if not decision_id:
            return None
        r = self.api("GET", f"/api/decisions/{decision_id}")
        return r.json() if r.status_code == 200 else None

    def policy(self) -> dict[str, Any]:
        r = self.api("GET", "/api/policy")
        return r.json() if r.status_code == 200 else {}

    def controls(self) -> dict[str, dict[str, Any]]:
        r = self.api("GET", "/api/controls")
        if r.status_code != 200:
            return {}
        return {c["id"]: c for c in r.json().get("items", [])}

    def approvals(self, status: str = "pending") -> list[dict[str, Any]]:
        r = self.api("GET", "/api/approvals", params={"status": status})
        return r.json().get("items", []) if r.status_code == 200 else []

    def approve(self, approval_id: str, as_member: str, comment: str = "test") -> httpx.Response:
        return self.api(
            "POST",
            f"/api/approvals/{approval_id}/approve",
            view_as=as_member,
            json={"comment": comment},
        )

    def deny(self, approval_id: str, as_member: str, comment: str = "test") -> httpx.Response:
        return self.api(
            "POST",
            f"/api/approvals/{approval_id}/deny",
            view_as=as_member,
            json={"comment": comment},
        )

    def cancel(self, approval_id: str, as_member: str = OWNER) -> httpx.Response:
        return self.api("POST", f"/api/approvals/{approval_id}/cancel", view_as=as_member, json={})

    def budgets(self) -> dict[str, Any]:
        r = self.api("GET", "/api/budgets")
        return r.json() if r.status_code == 200 else {}

    def feed_status(self) -> dict[str, Any]:
        r = self.api("GET", "/api/feed/status")
        return r.json() if r.status_code == 200 else {}

    def wait_version(self, version: int, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (self.policy().get("version") or 0) >= version:
                return True
            time.sleep(0.05)
        return False


__all__ = ["KIND_BY_SURFACE", "OUT_DIRECTION_IN", "Gateway", "new_session"]
