"""Result dataclasses, the typed error hierarchy and envelope parsers for `aegis.sdk`.

Error envelopes (CONTRACTS section 5.3 + Addendum A-07 / A-18 / A-31):
- API / OpenAI wire: `{"error": {"type", "message", "control_id", "decision_id", "approval_id",
  "required_role", "expires_at", "scope", "retry_after_s"}}`
- Anthropic wire: `{"type": "error", "error": {"type", "message"}, "aegis": {<inner>}}`
- Ollama: `{"error": "[Aegis] Blocked by <ID>: ...", "aegis": {<inner>}}`
- 409 policy conflict: `{"error": {"type": "conflict", "message", "current_version", "result"}}`
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: `[Aegis] Blocked by DLP-02: ...`, hook reasons `[Aegis] EXE-01: ...`, feed ids `AEGIS-TI-022`
CONTROL_RE = re.compile(
    r"\[Aegis\]\s*(?:Blocked by\s+|Approval required by\s+|)"
    r"((?:AEGIS-TI-\d{3})|(?:[A-Z]{2,4}-\d{2}))\b"
)
ANY_CONTROL_RE = re.compile(
    r"\b((?:AEGIS-TI-\d{3})|(?:(?:DLP|INJ|EXE|ACT|GOV|BUD|MCP|SIG|CUS)-\d{2}))\b"
)
APPROVAL_RE = re.compile(r"\bapr_[0-9a-f]{26}\b")
DECISION_RE = re.compile(r"\bdec_[0-9a-f]{26}\b")

PENDING_ACTIONS = frozenset({"require_approval"})
BLOCKING_ACTIONS = frozenset({"block"})


def control_from_text(text: str | None) -> str | None:
    """Control id from an `[Aegis] ...` message (None when absent)."""
    if not text:
        return None
    m = CONTROL_RE.search(text)
    if m:
        return m.group(1)
    if "[Aegis]" in text:
        m = ANY_CONTROL_RE.search(text)
        if m:
            return m.group(1)
    return None


def approval_from_text(text: str | None) -> str | None:
    if not text:
        return None
    m = APPROVAL_RE.search(text)
    return m.group(0) if m else None


# ------------------------------------------------------------------------------------------ errors
class AegisError(Exception):
    """Any non-success answer from the gateway (or the gateway being unreachable: status 0)."""

    type = "error"

    def __init__(
        self,
        status: int,
        type: str | None = None,
        message: str = "",
        envelope: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.type = type or self.type
        self.message = message or self.type
        self.envelope: dict[str, Any] = dict(envelope or {})
        self.headers: dict[str, str] = dict(headers or {})
        env = self.envelope
        self.control_id: str | None = env.get("control_id") or control_from_text(message)
        self.decision_id: str | None = env.get("decision_id") or self.headers.get(
            "x-aegis-decision-id"
        )
        self.approval_id: str | None = (
            env.get("approval_id")
            or self.headers.get("x-aegis-approval-id")
            or approval_from_text(message)
        )
        self.required_role: str | None = env.get("required_role")
        self.expires_at: str | None = env.get("expires_at")
        self.scope: str | None = env.get("scope")
        ra = env.get("retry_after_s")
        if ra is None:
            ra = self.headers.get("retry-after")
        try:
            self.retry_after_s: float | None = float(ra) if ra not in (None, "") else None
        except (TypeError, ValueError):
            self.retry_after_s = None
        self.should_retry = str(self.headers.get("x-should-retry", "")).lower() != "false"
        super().__init__(f"{status} {self.type}: {self.message}")

    @property
    def action(self) -> str:
        if self.type == "approval_required":
            return "require_approval"
        return "block"


class PolicyBlocked(AegisError):
    type = "policy_blocked"


class ApprovalRequired(AegisError):
    type = "approval_required"


class BudgetExceeded(AegisError):
    type = "budget_exceeded"


class RateLimited(AegisError):
    type = "rate_limited"


class Killed(AegisError):
    type = "killed"


class Forbidden(AegisError):
    type = "forbidden"


class Unauthenticated(AegisError):
    type = "unauthenticated"


class NotFound(AegisError):
    type = "not_found"


class Conflict(AegisError):
    type = "conflict"


class InvalidRequest(AegisError):
    type = "invalid_request"


class UpstreamError(AegisError):
    type = "upstream_error"


class GatewayUnavailable(AegisError):
    """Connection refused / timeout talking to the gateway (status 0)."""

    type = "unavailable"


ERROR_TYPES: dict[str, type[AegisError]] = {
    "policy_blocked": PolicyBlocked,
    "approval_required": ApprovalRequired,
    "budget_exceeded": BudgetExceeded,
    "rate_limited": RateLimited,
    "killed": Killed,
    "forbidden": Forbidden,
    "unauthenticated": Unauthenticated,
    "not_found": NotFound,
    "conflict": Conflict,
    "invalid_request": InvalidRequest,
    "upstream_error": UpstreamError,
    "unavailable": GatewayUnavailable,
}

_STATUS_TYPES: dict[int, str] = {
    400: "invalid_request",
    401: "unauthenticated",
    402: "budget_exceeded",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "invalid_request",
    429: "rate_limited",
}


def parse_envelope(body: Any) -> tuple[str | None, str, dict[str, Any]]:
    """(type, message, inner) from any of the error body shapes (tolerant of junk)."""
    if not isinstance(body, dict):
        text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body or "")
        return None, text[:500], {}
    aegis_inner = body.get("aegis") if isinstance(body.get("aegis"), dict) else {}
    err = body.get("error")
    if isinstance(err, dict):
        inner = {**aegis_inner, **err}
        return inner.get("type") or aegis_inner.get("type"), str(inner.get("message") or ""), inner
    if isinstance(err, str):  # Ollama
        return aegis_inner.get("type"), err, {**aegis_inner, "message": err}
    if "detail" in body:  # FastAPI default (e.g. route missing)
        detail = body["detail"]
        return None, detail if isinstance(detail, str) else str(detail), {"detail": detail}
    if aegis_inner:
        return aegis_inner.get("type"), str(aegis_inner.get("message") or ""), aegis_inner
    return None, "", {}


def error_from_response(
    status: int, body: Any, headers: dict[str, str] | None = None
) -> AegisError:
    """Typed error for a non-2xx answer."""
    etype, message, inner = parse_envelope(body)
    if not etype:
        etype = _STATUS_TYPES.get(status, "upstream_error" if status >= 500 else "error")
    cls = ERROR_TYPES.get(etype, AegisError)
    return cls(status, etype, message or etype, inner, headers=headers)


# ----------------------------------------------------------------------------------------- results
@dataclass
class _ActionMixin:
    action: str = "allow"

    @property
    def blocked(self) -> bool:
        return self.action in BLOCKING_ACTIONS

    @property
    def pending(self) -> bool:
        return self.action in PENDING_ACTIONS

    @property
    def allowed(self) -> bool:
        return self.action in ("allow", "log", "redact")

    @property
    def redacted(self) -> bool:
        return self.action == "redact"


@dataclass
class GuardResult(_ActionMixin):
    """`POST /v1/guard` answer (always HTTP 200)."""

    decision_id: str | None = None
    verdict: dict[str, Any] = field(default_factory=dict)
    text: str | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    approval: dict[str, Any] | None = None
    control_id: str | None = None
    reason: str | None = None
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    server_timing: str | None = None
    elapsed_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def approval_id(self) -> str | None:
        if self.approval:
            return self.approval.get("id")
        primary = self.verdict.get("primary") or {}
        return primary.get("approval_id") or self.headers.get("x-aegis-approval-id")

    @property
    def required_role(self) -> str | None:
        return (self.approval or {}).get("required_role")

    @property
    def controls(self) -> list[str]:
        """Control ids of the non-allow decisions (enforce + monitor)."""
        return [
            d.get("control_id")
            for d in self.verdict.get("decisions") or []
            if d.get("action") not in (None, "allow")
        ]

    @property
    def redactions(self) -> list[dict[str, Any]]:
        return list(self.verdict.get("redactions") or [])

    @property
    def latency_ms(self) -> float:
        return float(self.verdict.get("latency_ms") or 0.0)


@dataclass
class ChatResult(_ActionMixin):
    """Model-proxy answer (Anthropic / OpenAI / Ollama wire), incl. synthetic policy replies."""

    wire: str = "openai"
    model: str | None = None
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    decision_id: str | None = None
    response_decision_id: str | None = None
    request_id: str | None = None
    approval_id: str | None = None
    control_id: str | None = None
    downgraded_from: str | None = None
    budget_remaining: str | None = None
    policy_version: str | None = None
    feed_serial: str | None = None
    redaction_count: int = 0
    server_timing: str | None = None
    status_code: int = 200
    stream: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    raw: Any = None
    elapsed_ms: float = 0.0

    @property
    def input_tokens(self) -> int:
        u = self.usage
        return int(
            u.get("input_tokens") or u.get("prompt_tokens") or u.get("prompt_eval_count") or 0
        )

    @property
    def output_tokens(self) -> int:
        u = self.usage
        return int(u.get("output_tokens") or u.get("completion_tokens") or u.get("eval_count") or 0)


@dataclass
class McpResult(_ActionMixin):
    """`tools/call` (or `tools/list`) answer through `/mcp/{server}`."""

    server: str = ""
    tool: str = ""
    content: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    is_error: bool = False
    structured: Any = None
    meta: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    control_id: str | None = None
    approval_id: str | None = None
    decision_id: str | None = None
    required_role: str | None = None
    expires_at: str | None = None
    error: dict[str, Any] | None = None  # JSON-RPC error (e.g. -32001 unknown server)
    tools: list[dict[str, Any]] = field(default_factory=list)  # tools/list
    raw: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.is_error and self.error is None


@dataclass
class EgressResult(_ActionMixin):
    """`POST /egress` answer: allowed -> upstream status/headers/body; else the error fields."""

    status: int | None = None  # upstream status (allowed)
    status_code: int = 200  # gateway HTTP status
    headers: dict[str, str] = field(default_factory=dict)  # upstream headers
    body: Any = None
    decision_id: str | None = None
    redactions: Any = None
    control_id: str | None = None
    approval_id: str | None = None
    required_role: str | None = None
    expires_at: str | None = None
    error: AegisError | None = None
    raw: Any = None
    elapsed_ms: float = 0.0

    def json(self) -> Any:
        """Upstream body parsed as JSON when it is a JSON string (else the body as-is)."""
        if isinstance(self.body, str):
            import json as _json

            try:
                return _json.loads(self.body)
            except ValueError:
                return self.body
        return self.body


def mcp_result_from(
    server: str, tool: str, result: dict[str, Any] | None, *, error: dict[str, Any] | None = None
) -> McpResult:
    """Build an `McpResult` from a JSON-RPC `result` (or `error`), parsing Aegis verdicts.

    Verdict sources: `_meta["io.aegis/decision"]` (A-46) else the `[Aegis] ...` text.
    """
    if error is not None:
        msg = str(error.get("message") or "")
        return McpResult(
            action="block",
            server=server,
            tool=tool,
            text=msg,
            is_error=True,
            error=dict(error),
            control_id=control_from_text(msg)
            or ("MCP-01" if error.get("code") == -32001 else None),
            raw={"error": error},
        )
    result = dict(result or {})
    content = [c for c in result.get("content") or [] if isinstance(c, dict)]
    text = "\n".join(str(c.get("text", "")) for c in content if c.get("type", "text") == "text")
    meta = dict(result.get("_meta") or {})
    decision = dict(meta.get("io.aegis/decision") or {})
    is_error = bool(result.get("isError"))
    aegis_text = "[Aegis]" in text
    if decision.get("action"):
        action = str(decision["action"])
    elif is_error and aegis_text:
        low = text.lower()
        action = "require_approval" if ("approval" in low and "pending" in low) else "block"
    else:
        action = "allow"
    return McpResult(
        action=action,
        server=server,
        tool=tool,
        content=content,
        text=text,
        is_error=is_error,
        structured=result.get("structuredContent"),
        meta=meta,
        decision=decision,
        control_id=decision.get("control_id") or (control_from_text(text) if aegis_text else None),
        approval_id=decision.get("approval_id")
        or (approval_from_text(text) if aegis_text else None),
        decision_id=decision.get("decision_id"),
        required_role=decision.get("required_role"),
        expires_at=decision.get("expires_at"),
        tools=list(result.get("tools") or []),
        raw=result,
    )


__all__ = [
    "ERROR_TYPES",
    "AegisError",
    "ApprovalRequired",
    "BudgetExceeded",
    "ChatResult",
    "Conflict",
    "EgressResult",
    "Forbidden",
    "GatewayUnavailable",
    "GuardResult",
    "InvalidRequest",
    "Killed",
    "McpResult",
    "NotFound",
    "PolicyBlocked",
    "RateLimited",
    "Unauthenticated",
    "UpstreamError",
    "approval_from_text",
    "control_from_text",
    "error_from_response",
    "mcp_result_from",
    "parse_envelope",
]
