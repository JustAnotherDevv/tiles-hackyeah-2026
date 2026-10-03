"""`AegisAdmin` — the dashboard API (`/api/*`) as a "view as" member (sync, httpx).

    admin = AegisAdmin(view_as="u_emily")                    # admin
    for apr in admin.approvals("pending"):
        admin.approve(apr["id"], "ok for the trading desk")
    admin.as_("u_katarzyna").killswitch("agent:chaos-agent@platform", True, "runaway")

Viewer: `X-Aegis-View-As` (+ `Authorization: Bearer $AEGIS_ADMIN_TOKEN` when set). Every non-2xx
raises a typed `AegisError` (403 forbidden, 404 not_found, 409 conflict, ...).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from typing import Any

import httpx

from aegis.sdk.cast import DEFAULT_VIEWER, default_url, resolve_member
from aegis.sdk.mcp import iter_sse
from aegis.sdk.results import GatewayUnavailable, error_from_response


def _lower(headers: httpx.Headers) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


def _items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "approvals", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


class AegisAdmin:
    """Dashboard API client acting as member `view_as`."""

    def __init__(
        self,
        base_url: str | None = None,
        view_as: str = DEFAULT_VIEWER,
        admin_token: str | None = None,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or default_url()).rstrip("/")
        self.view_as = resolve_member(view_as) or DEFAULT_VIEWER
        self.admin_token = (
            admin_token if admin_token is not None else os.environ.get("AEGIS_ADMIN_TOKEN")
        )
        self.timeout = timeout
        self._transport = transport
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=5.0),
            transport=transport,
            headers={"user-agent": "aegis-sdk-admin/0.1"},
        )

    def __enter__(self) -> AegisAdmin:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def as_(self, member: str) -> AegisAdmin:
        """A sibling client viewing as another member (shares nothing mutable)."""
        return AegisAdmin(
            self.base_url, member, self.admin_token, timeout=self.timeout, transport=self._transport
        )

    # ------------------------------------------------------------------------------ plumbing
    def headers(self) -> dict[str, str]:
        h = {"x-aegis-view-as": self.view_as}
        if self.admin_token:
            h["authorization"] = f"Bearer {self.admin_token}"
        return h

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        kw: dict[str, Any] = {"headers": self.headers(), "params": clean or None}
        if json_body is not None:
            kw["json"] = json_body
        if timeout is not None:
            kw["timeout"] = httpx.Timeout(timeout, connect=5.0)
        try:
            resp = self._http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise GatewayUnavailable(
                0, "unavailable", f"gateway unreachable at {self.base_url} ({e})"
            ) from e
        try:
            data = resp.json()
        except ValueError:
            data = resp.text
        if resp.status_code >= 400:
            raise error_from_response(resp.status_code, data, _lower(resp.headers))
        return data

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, json_body=body if body is not None else {})

    # ------------------------------------------------------------------------------ health / org
    def healthz(self) -> dict[str, Any]:
        return self.get("/healthz")

    def whoami(self) -> dict[str, Any]:
        return self.get("/api/whoami")

    def org(self) -> dict[str, Any]:
        return self.get("/api/org")

    def members(self) -> list[dict[str, Any]]:
        return _items(self.get("/api/members"))

    def agents(self) -> list[dict[str, Any]]:
        return _items(self.get("/api/agents"))

    # ------------------------------------------------------------------------------ approvals
    def approvals(
        self,
        status: str = "pending",
        *,
        kind: str | None = None,
        mine: bool | None = None,
        actionable: bool | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return _items(
            self.get(
                "/api/approvals",
                status=status,
                kind=kind,
                mine=str(mine).lower() if mine is not None else None,
                actionable=str(actionable).lower() if actionable is not None else None,
                limit=limit,
            )
        )

    def approval(self, approval_id: str) -> dict[str, Any]:
        return self.get(f"/api/approvals/{approval_id}")

    def approve(self, approval_id: str, comment: str | None = None) -> dict[str, Any]:
        return self.post(f"/api/approvals/{approval_id}/approve", {"comment": comment})

    def deny(self, approval_id: str, comment: str | None = None) -> dict[str, Any]:
        return self.post(f"/api/approvals/{approval_id}/deny", {"comment": comment})

    def cancel(self, approval_id: str) -> dict[str, Any]:
        return self.post(f"/api/approvals/{approval_id}/cancel", {})

    def wait(self, approval_id: str, timeout_s: int = 25) -> dict[str, Any]:
        """Long-poll `GET /api/approvals/{id}/wait` (A-23)."""
        return self.request(
            "GET",
            f"/api/approvals/{approval_id}/wait",
            params={"timeout_s": timeout_s},
            timeout=timeout_s + 10,
        )

    def approvals_simulate(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.post("/api/approvals/simulate", body)

    # ------------------------------------------------------------------------------ policy
    def policy(self) -> dict[str, Any]:
        return self.get("/api/policy")

    def policy_validate(self, yaml: str, *, selftest: bool = True) -> dict[str, Any]:
        return self.post("/api/policy/validate", {"yaml": yaml, "selftest": selftest})

    def policy_diff(self, yaml: str) -> dict[str, Any]:
        return self.post("/api/policy/diff", {"yaml": yaml})

    def policy_apply(
        self, yaml: str, base_version: int | None = None, reason: str | None = None
    ) -> dict[str, Any]:
        """`POST /api/policy/apply` (fetches the current version when `base_version` is None).
        Stale base -> `Conflict` (409)."""
        if base_version is None:
            base_version = int(self.policy().get("version") or 0)
        return self.post(
            "/api/policy/apply", {"yaml": yaml, "base_version": base_version, "reason": reason}
        )

    def policy_rollback(self, version: int, reason: str | None = None) -> dict[str, Any]:
        return self.post("/api/policy/rollback", {"version": version, "reason": reason})

    def policy_history(self) -> list[dict[str, Any]]:
        return _items(self.get("/api/policy/history"))

    def policy_version(self, version: int) -> dict[str, Any]:
        return self.get(f"/api/policy/versions/{version}")

    def policy_reload(self) -> dict[str, Any]:
        return self.post("/api/policy/reload", {})

    def controls(self) -> list[dict[str, Any]]:
        return _items(self.get("/api/controls"))

    def coverage(self) -> dict[str, Any]:
        return self.get("/api/coverage")

    # ------------------------------------------------------------------------------ budgets
    def budgets(self) -> dict[str, Any]:
        return self.get("/api/budgets")

    def budgets_raise(
        self,
        scope: str,
        window: str,
        dimension: str,
        new_limit: float,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self.post(
            "/api/budgets/raise",
            {
                "scope": scope,
                "window": window,
                "dimension": dimension,
                "new_limit": new_limit,
                "reason": reason,
            },
        )

    def budgets_reset(
        self, scope: str | None = None, *, reseed: bool | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if scope:
            body["scope"] = scope
        if reseed is not None:
            body["reseed"] = reseed
        return self.post("/api/budgets/reset", body)

    def killswitch(self, scope: str, active: bool, reason: str | None = None) -> dict[str, Any]:
        return self.post(
            "/api/killswitch", {"scope": scope, "active": bool(active), "reason": reason or ""}
        )

    # ------------------------------------------------------------------------------ decisions & stats
    def decisions(self, **filters: Any) -> list[dict[str, Any]]:
        return _items(self.get("/api/decisions", **filters))

    def decision(self, decision_id: str) -> dict[str, Any]:
        return self.get(f"/api/decisions/{decision_id}")

    def stats(self, window: str = "1h") -> dict[str, Any]:
        return self.get("/api/stats", window=window)

    def perf(self) -> dict[str, Any]:
        return self.get("/api/perf")

    def audit_verify(self) -> dict[str, Any]:
        return self.get("/api/audit/verify")

    # ------------------------------------------------------------------------------ MCP & feed
    def mcp_servers(self) -> list[dict[str, Any]]:
        return _items(self.get("/api/mcp/servers"))

    def mcp_approve(self, server: str, tool: str, comment: str | None = None) -> dict[str, Any]:
        return self.post(f"/api/mcp/servers/{server}/tools/{tool}/approve", {"comment": comment})

    def mcp_reset(self) -> dict[str, Any]:
        return self.post("/api/mcp/reset", {})

    def feed_status(self) -> dict[str, Any]:
        return self.get("/api/feed/status")

    def feed_refresh(self) -> dict[str, Any]:
        return self.post("/api/feed/refresh", {})

    # ------------------------------------------------------------------------------ SSE
    def events(
        self,
        names: Iterable[str] | None = None,
        replay: int | None = None,
        *,
        timeout: float | None = None,
    ) -> Iterator[tuple[str, Any]]:
        """Iterate `(event, data)` from `GET /api/events` (SSE) until the stream ends or the
        consumer stops. `timeout` = read timeout per chunk (None = wait forever)."""
        params: dict[str, Any] = {"view_as": self.view_as}
        if names:
            params["events"] = ",".join(names)
        if replay:
            params["replay"] = replay
        try:
            with self._http.stream(
                "GET",
                "/api/events",
                params=params,
                headers={**self.headers(), "accept": "text/event-stream"},
                timeout=httpx.Timeout(timeout, connect=5.0),
            ) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    raise error_from_response(resp.status_code, resp.text, _lower(resp.headers))
                buf = ""
                for chunk in resp.iter_text():
                    buf += chunk.replace("\r\n", "\n")
                    while "\n\n" in buf:
                        block, buf = buf.split("\n\n", 1)
                        for ev, data in iter_sse(block + "\n\n"):
                            try:
                                yield ev, json.loads(data)
                            except ValueError:
                                yield ev, data
        except httpx.HTTPError as e:
            raise GatewayUnavailable(0, "unavailable", f"event stream failed ({e})") from e


__all__ = ["AegisAdmin"]
