"""Stop semantics toward clients (CONTRACTS Addendum A-07; staging Claude Code FINDINGS).

Budget stops are 402 `budget_exceeded` + `x-should-retry: false`; throttles are 429 + Retry-After;
the kill switch is **never 403**: 429 `killed` + `retry-after: 3600` + `x-should-retry: false` for
every client (403 renders as "Failed to authenticate" in Claude Code). `claude_code_stop` is
obsolete (ignored); `is_claude_code` is kept for messages/telemetry only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

from aegis.core.types import RequestContext

NO_RETRY = {"x-should-retry": "false"}


@dataclass
class StopFields:
    http_status: int | None
    error_type: str | None
    retry_after_s: int | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def kwargs(self) -> dict[str, Any]:
        return {
            "http_status": self.http_status,
            "error_type": self.error_type,
            "retry_after_s": self.retry_after_s,
        }


def is_claude_code(ctx: RequestContext, params: Any = None) -> bool:
    agents = list(getattr(params, "claude_code_agents", None) or ["claude-code@*"])
    agent = ctx.identity.agent_id
    if agent and any(fnmatchcase(agent, g) for g in agents):
        return True
    headers = ctx.headers or {}
    if headers.get("x-claude-code-session-id"):
        return True
    return str(headers.get("user-agent", "")).lower().startswith("claude-cli")


def hard_stop(
    kind: str, ctx: RequestContext, params: Any = None, *, retry_after_s: int | None = None
) -> StopFields:
    """kind: budget | step_cap | rate | cooldown | killed."""
    if kind in ("budget", "step_cap"):
        return StopFields(402, "budget_exceeded", None, dict(NO_RETRY))
    if kind == "rate":
        n = int(retry_after_s or 1)
        return StopFields(429, "rate_limited", n, {"retry-after": str(n)})
    if kind == "cooldown":
        n = int(retry_after_s or 30)
        return StopFields(429, "rate_limited", n, {"retry-after": str(n), **NO_RETRY})
    if kind == "killed":
        return StopFields(429, "killed", 3600, {"retry-after": "3600", **NO_RETRY})
    return StopFields(None, None, None, {})


__all__ = ["StopFields", "hard_stop", "is_claude_code"]
