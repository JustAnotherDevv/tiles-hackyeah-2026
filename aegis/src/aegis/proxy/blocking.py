"""Shared block / approval / error semantics for the three wire adapters.

Owner: core-gateway (bundle B02). Implements CONTRACTS §5.3 as amended by **Addendum A-06/A-07**
(the addendum wins):

| situation              | error_type          | model proxies                                  |
|------------------------|---------------------|------------------------------------------------|
| policy block           | `policy_blocked`    | 200 synthetic reply (`block_response: error` -> 403 wire error) |
| approval pending       | `approval_required` | 200 synthetic reply with apr id + link (`error` -> 403)          |
| budget hard limit      | `budget_exceeded`   | **402** + `x-should-retry: false`              |
| rate limit / loop      | `rate_limited`      | **429** + `retry-after: n`                     |
| kill switch / loop kill| `killed`            | **429** + `retry-after: 3600` + `x-should-retry: false` (never 403) |
| GOV-01 bad credential  | `unauthenticated`   | **401** wire error                             |
| GOV-01 disabled        | `forbidden`         | **403** wire error                             |

`primary.http_status` overrides the default status of its error type. Stop codes are wire errors
regardless of `style`. Controls add response headers via `Decision.meta["response_headers"]`
(allowed names: `x-aegis-*`, `retry-after`, `x-should-retry`), merged from every enforce-mode
decision (primary wins, then lower priority, then control id) - see `decision_headers`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from aegis.core.types import Verdict

log = logging.getLogger(__name__)

__all__ = [
    "STOP_STATUS",
    "BlockInfo",
    "block_info",
    "block_message",
    "decision_headers",
    "error_inner",
    "public_base_url",
]

#: forced wire-error statuses (rendered as errors regardless of `defaults.block_response`)
STOP_STATUS: dict[str, int] = {
    "budget_exceeded": 402,
    "rate_limited": 429,
    "killed": 429,
    "unauthenticated": 401,
    "forbidden": 403,
}
_ALLOWED_HEADER = ("x-aegis-", "retry-after", "x-should-retry")
_warned_headers: set[str] = set()


def public_base_url() -> str:
    """Base URL for approval links (`Settings.public_url` if present, else host:port)."""
    try:
        from aegis.settings import get_settings

        s = get_settings()
        url = getattr(s, "public_url", None)
        if isinstance(url, str) and url:
            return url.rstrip("/")
        host = getattr(s, "host", "127.0.0.1") or "127.0.0.1"
        port = getattr(s, "port", 8787) or 8787
        if host in {"0.0.0.0", "::"} or not port:
            host, port = "127.0.0.1", port or 8787
        return f"http://{host}:{port}"
    except Exception:  # pragma: no cover - settings broken
        return "http://127.0.0.1:8787"


def _primary(verdict: Verdict) -> Any:
    if verdict.primary is not None:
        return verdict.primary
    for d in verdict.decisions:
        if d.mode == "enforce" and d.action == verdict.action:
            return d
    return None


def decision_headers(verdicts: Iterable[Verdict | None]) -> dict[str, str]:
    """A-06: merge `meta.response_headers` of every enforce-mode decision.

    Precedence on conflicting names: the verdict's primary decision, then earlier decisions
    (the pipeline orders them by priority, then id), then earlier verdicts (request hop first).
    Adds `retry-after` from `primary.retry_after_s` when set and not already present.
    """
    out: dict[str, str] = {}
    for v in verdicts:
        if v is None:
            continue
        p = v.primary
        ordered = ([p] if p is not None else []) + [d for d in v.decisions if d is not p]
        for d in ordered:
            if d is None or d.mode != "enforce":
                continue
            hdrs = (d.meta or {}).get("response_headers") or {}
            if not isinstance(hdrs, dict):
                continue
            for name, value in hdrs.items():
                lk = str(name).lower()
                if not lk.startswith(_ALLOWED_HEADER):
                    if lk not in _warned_headers:
                        _warned_headers.add(lk)
                        log.warning("response header dropped name=%s control=%s", lk,
                                    d.control_id)
                    continue
                if value is None:
                    continue
                out.setdefault(lk, str(value))
        if p is not None and p.mode == "enforce" and p.retry_after_s and \
                v.action in ("block", "require_approval"):
            out.setdefault("retry-after", str(int(p.retry_after_s)))
    return out


def block_message(verdict: Verdict) -> str:
    """Human text for the synthetic assistant reply / error message."""
    p = _primary(verdict)
    cid = getattr(p, "control_id", None) or "AEGIS"
    reason = (getattr(p, "reason", "") or "").strip()
    pv = verdict.policy_version
    if verdict.action == "require_approval":
        apr = verdict.approval
        apr_id = getattr(apr, "id", None) or getattr(p, "approval_id", None) or "apr_?"
        role = getattr(apr, "required_role", None) or "approval"
        title = getattr(apr, "title", None) or reason or "this action"
        base = public_base_url()
        return (
            f"[Aegis] Approval required ({apr_id}, needs {role}): {title}. "
            f"Approve at {base}/ui/governance/approvals?id={apr_id} "
            f"then retry with header X-Aegis-Approval: {apr_id}"
        )
    text = f"[Aegis] Blocked by {cid}"
    text += f": {reason.rstrip('.')}." if reason else "."
    text += f" ({verdict.id}, policy v{pv})"
    return text


def error_inner(
    verdict: Verdict, error_type: str, message: str, retry_after_s: int | None = None
) -> dict[str, Any]:
    p = _primary(verdict)
    apr = verdict.approval
    meta = getattr(p, "meta", None) or {}
    expires = getattr(apr, "expires_at", None)
    return {
        "type": error_type,
        "message": message,
        "control_id": getattr(p, "control_id", None),
        "decision_id": verdict.id,
        "approval_id": getattr(apr, "id", None) or getattr(p, "approval_id", None),
        "required_role": getattr(apr, "required_role", None),
        "expires_at": expires.isoformat() if hasattr(expires, "isoformat") else expires,
        "scope": meta.get("scope"),
        "retry_after_s": retry_after_s,
    }


@dataclass(slots=True)
class BlockInfo:
    """How a non-allow verdict is rendered on a wire."""

    error_type: str
    status: int | None  # forced wire-error status or None (style decides: 200 message / 403)
    message: str
    headers: dict[str, str] = field(default_factory=dict)
    inner: dict[str, Any] = field(default_factory=dict)

    @property
    def forced_error(self) -> bool:
        return self.status is not None


def block_info(verdict: Verdict, *, wire: str = "anthropic") -> BlockInfo:
    """Classify a block / require_approval verdict (identical on every wire, A-07)."""
    p = _primary(verdict)
    status = getattr(p, "http_status", None)
    etype = (getattr(p, "error_type", None) or "").strip()
    retry = getattr(p, "retry_after_s", None)
    if etype == "kill_switch":
        etype = "killed"
    if etype not in STOP_STATUS:
        if status == 402:
            etype = "budget_exceeded"
        elif status == 429:
            etype = "rate_limited"
        elif status == 401:
            etype = "unauthenticated"
        elif verdict.action == "require_approval":
            etype = "approval_required"
        else:
            etype = "policy_blocked"
    headers: dict[str, str] = {}
    forced: int | None = None
    if etype in STOP_STATUS:
        forced = STOP_STATUS[etype]
        if etype == "budget_exceeded":
            headers["x-should-retry"] = "false"
        elif etype == "rate_limited":
            retry = retry or 60
            headers["retry-after"] = str(int(retry))
        elif etype == "killed":
            retry = retry or 3600
            headers["retry-after"] = str(int(retry))
            headers["x-should-retry"] = "false"
        # primary.http_status overrides the default status - except a 403 for the kill switch
        if isinstance(status, int) and 400 <= status < 600 and not (
                etype == "killed" and status == 403):
            forced = status
    elif isinstance(status, int) and status in (401, 402, 429):
        forced = status
    msg = block_message(verdict)
    # control-requested headers (A-06) win over the defaults above
    headers.update(decision_headers([verdict]))
    inner = error_inner(verdict, etype, msg, int(retry) if retry else None)
    return BlockInfo(error_type=etype, status=forced, message=msg, headers=headers, inner=inner)
