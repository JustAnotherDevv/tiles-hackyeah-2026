"""Error envelopes (public surface, CONTRACTS sections 3.3 and 5.3).

- `api_error(status, type, message, **fields) -> JSONResponse` — the dashboard / `/api/*` envelope
  `{"error": {"type", "message", "control_id", "decision_id", "approval_id", "required_role",
  "expires_at", "scope", "retry_after_s"}}`.
- `AegisHTTPError(status, type, message, **fields)` — raise anywhere inside a route; the app's
  exception handler renders it with `api_error` (or the wire format on data-plane paths).
- `wire_error(wire, status, type, message, **fields) -> JSONResponse` — the same inner object in
  the Anthropic / OpenAI / Ollama error format (model proxies).
- `block_status(decision, wire=..., claude_code=...)` — the HTTP status/type/headers a blocking
  decision must be rendered with *regardless* of `defaults.block_response` (budget / rate / kill
  / credential stops, Addendum A-07), or None for an ordinary policy block.
- `decision_headers(*verdicts)` — control-requested response headers (`Decision.meta
  ["response_headers"]`, Addendum A-06) merged for a data-plane response.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi.responses import JSONResponse

from aegis.core.types import Decision, Verdict

log = logging.getLogger(__name__)

INNER_FIELDS = (
    "control_id",
    "decision_id",
    "approval_id",
    "required_role",
    "expires_at",
    "scope",
    "retry_after_s",
)

#: error type -> default HTTP status
ERROR_STATUS: dict[str, int] = {
    "invalid_request": 400,
    "unauthorized": 401,
    "unauthenticated": 401,
    "budget_exceeded": 402,
    "policy_blocked": 403,
    "approval_required": 403,
    "killed": 429,  # Addendum A-07: never 403
    "forbidden": 403,
    "not_found": 404,
    "conflict": 409,
    "payload_too_large": 413,
    "rate_limited": 429,
    "internal_error": 500,
    "upstream_error": 502,
    "unavailable": 503,
}

#: Anthropic wire error types (what SDKs / Claude Code understand) for our types
_ANTHROPIC_TYPE: dict[str, str] = {
    "invalid_request": "invalid_request_error",
    "unauthorized": "authentication_error",
    "unauthenticated": "authentication_error",
    "forbidden": "permission_error",
    "not_found": "not_found_error",
    "payload_too_large": "request_too_large",
    "rate_limited": "rate_limit_error",
    "internal_error": "api_error",
    "upstream_error": "api_error",
    "unavailable": "overloaded_error",
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


def error_inner(type_: str, message: str, **fields: Any) -> dict[str, Any]:
    """The shared inner object (all INNER_FIELDS present, None when unknown) + extra fields."""
    inner: dict[str, Any] = {"type": type_, "message": message}
    for key in INNER_FIELDS:
        inner[key] = _jsonable(fields.pop(key, None))
    for key, value in fields.items():
        inner[key] = _jsonable(value)
    return inner


def api_error(
    status: int, type: str, message: str, headers: dict[str, str] | None = None, **fields: Any
) -> JSONResponse:
    """Dashboard / `/api/*` / `/egress` error envelope (CONTRACTS section 5.3)."""
    return JSONResponse(
        {"error": error_inner(type, message, **fields)}, status_code=status, headers=headers
    )


class AegisHTTPError(Exception):
    """Raise inside a route to answer with the standard envelope."""

    def __init__(
        self,
        status: int,
        type: str,
        message: str,
        headers: dict[str, str] | None = None,
        **fields: Any,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.type = type
        self.message = message
        self.headers = headers
        self.fields = fields

    def response(self, wire: str | None = None) -> JSONResponse:
        if wire:
            return wire_error(
                wire, self.status, self.type, self.message, headers=self.headers, **self.fields
            )
        return api_error(self.status, self.type, self.message, headers=self.headers, **self.fields)


def wire_body(wire: str, type_: str, message: str, **fields: Any) -> dict[str, Any]:
    """Error body in the given wire format (anthropic | openai | ollama | api)."""
    inner = error_inner(type_, message, **fields)
    if wire == "anthropic":
        return {
            "type": "error",
            "error": {"type": _ANTHROPIC_TYPE.get(type_, type_), "message": message},
            "aegis": inner,
        }
    if wire == "openai":
        return {"error": {**inner, "code": type_}}
    if wire == "ollama":
        return {"error": message if message.startswith("[Aegis]") else f"[Aegis] {message}",
                "aegis": inner}
    return {"error": inner}


def wire_error(
    wire: str,
    status: int,
    type: str,
    message: str,
    headers: dict[str, str] | None = None,
    **fields: Any,
) -> JSONResponse:
    """Wire-format error response (model proxies). `wire` in {anthropic, openai, ollama}."""
    return JSONResponse(wire_body(wire, type, message, **fields), status_code=status,
                        headers=headers)


def wire_for_path(path: str) -> str | None:
    """Which wire format a data-plane path answers errors in (None = API envelope)."""
    if path.startswith("/v1/messages"):
        return "anthropic"
    if path.startswith(("/v1/chat", "/openai/", "/v1/models", "/v1/completions",
                        "/v1/embeddings")):
        return "openai"
    if path.startswith("/ollama"):
        return "ollama"
    return None


# ------------------------------------------------------------------ blocking stops
#: error types always rendered as wire errors (never a synthetic 200), Addendum A-07
STOP_TYPES = {"budget_exceeded", "rate_limited", "killed", "unauthenticated", "forbidden"}
_STOP_DEFAULT_STATUS = {
    "budget_exceeded": 402,
    "rate_limited": 429,
    "killed": 429,
    "unauthenticated": 401,
    "forbidden": 403,
}


def block_status(
    decision: Decision | None,
    *,
    wire: str | None = None,
    claude_code: bool = False,
) -> tuple[int, str, dict[str, str]] | None:
    """(status, error_type, headers) for budget / rate / kill / credential stops, else None.

    Addendum A-07 (same codes for every client and wire): 402 `budget_exceeded` +
    `x-should-retry: false`; 429 `rate_limited` + `retry-after: n`; 429 `killed` +
    `retry-after: 3600` + `x-should-retry: false` (never 403); 401 `unauthenticated`;
    403 `forbidden`. `decision.http_status` overrides the default status (A-06).
    `wire` / `claude_code` are accepted for compatibility and do not change the result.
    """
    if decision is None:
        return None
    etype = decision.error_type or ""
    status = decision.http_status
    if etype not in STOP_TYPES:
        if status == 402:
            etype = "budget_exceeded"
        elif status == 429:
            etype = "rate_limited"
        elif status == 401:
            etype = "unauthenticated"
        else:
            return None
    status = int(status or _STOP_DEFAULT_STATUS[etype])
    headers: dict[str, str] = {}
    if etype == "budget_exceeded":
        headers["x-should-retry"] = "false"
    elif etype == "rate_limited":
        headers["retry-after"] = str(decision.retry_after_s or 60)
        if decision.retry_after_s and decision.retry_after_s > 60:
            headers["x-should-retry"] = "false"
    elif etype == "killed":
        headers["retry-after"] = str(decision.retry_after_s or 3600)
        headers["x-should-retry"] = "false"
    return status, etype, headers


# ------------------------------------------------------------------ control headers (A-06)
_ALLOWED_HEADER_PREFIX = "x-aegis-"
_ALLOWED_HEADERS = {"retry-after", "x-should-retry"}
_warned_headers: set[str] = set()


def _priority_lookup() -> Callable[[str], int]:
    try:
        from aegis.core.runtime import get_runtime

        controls = get_runtime().controls
    except Exception:
        return lambda cid: 100

    def lookup(cid: str) -> int:
        try:
            c = controls.get(cid)
            return int(getattr(c, "priority", 100)) if c is not None else 100
        except Exception:
            return 100

    return lookup


def decision_headers(
    *verdicts: Verdict | None, priority: Callable[[str], int] | None = None
) -> dict[str, str]:
    """Merge `Decision.meta["response_headers"]` of all enforce-mode decisions (A-06).

    Allowed names: `x-aegis-*`, `retry-after`, `x-should-retry` (others dropped, one WARNING per
    name). Conflicts: primary decision wins, then lower control priority, then control_id;
    earlier verdicts (the request hop) win over later ones. Adds `retry-after` from
    `primary.retry_after_s` when set and not already present.
    """
    prio = priority or _priority_lookup()
    out: dict[str, str] = {}
    for verdict in verdicts:
        if verdict is None:
            continue
        primary = verdict.primary
        enforce = [d for d in verdict.decisions if d.mode == "enforce"]
        ranked = sorted(
            enforce,
            key=lambda d: (0 if primary is not None and d is primary else 1,
                           prio(d.control_id), d.control_id),
        )
        for d in ranked:
            hdrs = d.meta.get("response_headers") if isinstance(d.meta, dict) else None
            if not isinstance(hdrs, dict):
                continue
            for name, value in hdrs.items():
                key = str(name).lower()
                if not (key.startswith(_ALLOWED_HEADER_PREFIX) or key in _ALLOWED_HEADERS):
                    if key not in _warned_headers:
                        _warned_headers.add(key)
                        log.warning("control response header dropped name=%s control=%s",
                                    key, d.control_id)
                    continue
                if value is None:
                    continue
                out.setdefault(key, str(value))
        if primary is not None and primary.retry_after_s and "retry-after" not in out:
            out["retry-after"] = str(primary.retry_after_s)
    return out


def verdict_error_fields(verdict: Verdict) -> dict[str, Any]:
    """Inner-object fields for an error derived from a verdict (decision/approval ids, role…)."""
    primary = verdict.primary
    approval = verdict.approval
    fields: dict[str, Any] = {
        "control_id": primary.control_id if primary else None,
        "decision_id": verdict.id,
        "approval_id": (approval.id if approval else (primary.approval_id if primary else None)),
        "required_role": approval.required_role if approval else None,
        "expires_at": approval.expires_at if approval else None,
        "scope": (primary.meta.get("scope") if primary else None),
        "retry_after_s": primary.retry_after_s if primary else None,
    }
    return fields


def verdict_error(verdict: Verdict, *, wire: str | None = None,
                  claude_code: bool = False) -> JSONResponse:
    """Render a blocking / pending verdict as an error response (API envelope or wire format).

    Stops (budget/rate/kill/credential) use `block_status`; pending approval → 403
    `approval_required` + `x-aegis-approval-id`; other blocks → 403 `policy_blocked`
    (or `primary.http_status`). Control headers (A-06) are merged in.
    """
    primary = verdict.primary
    stop = block_status(primary, wire=wire, claude_code=claude_code)
    fields = verdict_error_fields(verdict)
    reason = (primary.reason if primary else "") or "blocked by policy"
    cid = primary.control_id if primary else "policy"
    if stop is not None:
        status, etype, headers = stop
        msg = f"[Aegis] {cid}: {reason}"
    elif verdict.action == "require_approval":
        status, etype, headers = 403, "approval_required", {}
        msg = f"[Aegis] Approval required ({cid}): {reason}"
        if fields.get("approval_id"):
            headers["x-aegis-approval-id"] = str(fields["approval_id"])
    else:
        status = int(primary.http_status) if primary and primary.http_status else 403
        etype, headers = (primary.error_type if primary and primary.error_type
                          else "policy_blocked"), {}
        msg = f"[Aegis] Blocked by {cid}: {reason}"
    merged = decision_headers(verdict)
    merged.update(headers)
    if wire:
        return wire_error(wire, status, etype, msg, headers=merged, **fields)
    return api_error(status, etype, msg, headers=merged, **fields)


__all__ = [
    "ERROR_STATUS",
    "INNER_FIELDS",
    "STOP_TYPES",
    "AegisHTTPError",
    "api_error",
    "block_status",
    "decision_headers",
    "error_inner",
    "verdict_error",
    "verdict_error_fields",
    "wire_body",
    "wire_error",
    "wire_for_path",
]
