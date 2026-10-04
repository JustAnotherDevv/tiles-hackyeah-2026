"""ApprovalDraft construction (kind ``action``) + anti-flooding + route preview.

Payload (CONTRACTS A-24 "action" shape, rendered by the approval card): ``facts`` (key/value),
``checks`` (``[{name, ok, detail}]`` + our extras ``id/value/limit/param``), ``agent_note``
(agent-supplied justification, masked, UNTRUSTED), ``explain`` (the Decision.meta explain dict),
plus ``tool``, ``args`` (masked string leaves), ``reason`` and ``control_id``. Capped at ~4 KB;
never carries raw PII or secrets.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from aegis.actions import runtime as art
from aegis.actions.explain import mask
from aegis.core.types import ApprovalDraft, Interaction, RequestContext

log = logging.getLogger(__name__)

PAYLOAD_MAX_BYTES = 4096
NOTE_ARGS = ("justification", "reason", "rationale", "note", "why")


def masked_args(args: Any, *, depth: int = 0, budget: list[int] | None = None) -> Any:
    """Copy of ``args`` with every string leaf masked (numbers/bools kept; capped)."""
    budget = budget if budget is not None else [60]
    if budget[0] <= 0 or depth > 4:
        return "…"
    budget[0] -= 1
    if isinstance(args, str):
        return mask(args, 120)
    if isinstance(args, bool | int | float) or args is None:
        return args
    if isinstance(args, dict):
        return {
            str(k): masked_args(v, depth=depth + 1, budget=budget)
            for k, v in list(args.items())[:30]
        }
    if isinstance(args, list | tuple):
        return [masked_args(v, depth=depth + 1, budget=budget) for v in list(args)[:20]]
    return mask(str(args), 80)


def agent_note(interaction: Interaction) -> str | None:
    args = interaction.tool_args or {}
    for key in NOTE_ARGS:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return mask(val, 200)
    return None


def payload_check(c: dict[str, Any]) -> dict[str, Any]:
    """Explain check -> A-24 ``{name, ok, detail}`` (keeping id/value/limit/param)."""
    detail = c.get("detail")
    if detail is None:
        value, limit = c.get("value"), c.get("limit")
        if value is not None and limit is not None:
            detail = f"{value} vs limit {limit}"
        elif value is not None:
            detail = str(value)
    return {
        "name": c.get("label") or c.get("id"),
        "ok": c.get("result") != "fail",
        "detail": detail,
        "id": c.get("id"),
        "value": c.get("value"),
        "limit": c.get("limit"),
        "param": c.get("param"),
    }


def _cap(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        size = len(json.dumps(payload, default=str))
    except Exception:
        return {k: payload.get(k) for k in ("tool", "explain", "control_id")}
    if size <= PAYLOAD_MAX_BYTES:
        return payload
    slim = dict(payload)
    slim["args"] = {"_truncated": True}
    if len(json.dumps(slim, default=str)) <= PAYLOAD_MAX_BYTES:
        return slim
    slim["checks"] = slim.get("checks", [])[:6]
    slim["explain"] = {"summary": (slim.get("explain") or {}).get("summary")}
    slim["facts"] = {k: v for k, v in list((slim.get("facts") or {}).items())[:12]}
    return slim


def build_draft(
    *,
    control_id: str,
    interaction: Interaction,
    action_type: str,
    title: str,
    summary: str | None = None,
    amount_usd: float | None = None,
    resource: str | None = None,
    labels: dict[str, str] | None = None,
    facts: dict[str, Any] | None = None,
    checks: list[dict[str, Any]] | None = None,
    reason: str = "",
    explain: dict[str, Any] | None = None,
) -> ApprovalDraft:
    """ApprovalDraft with ``labels = interaction.labels ∪ own`` and a redacted payload."""
    merged = {str(k): str(v) for k, v in interaction.labels.items()}
    for k, v in (labels or {}).items():
        if v is not None:
            merged[str(k)] = str(v).lower() if isinstance(v, bool) else str(v)
    payload = _cap(
        {
            "tool": interaction.tool_name
            or (f"http.{(interaction.http_method or 'get').lower()}" if interaction.url else None),
            "args": masked_args(interaction.tool_args or {}),
            "facts": facts or {},
            "checks": [payload_check(c) for c in (checks or [])],
            "agent_note": agent_note(interaction),
            "explain": explain or {"summary": reason},
            "reason": reason,
            "control_id": control_id,
        }
    )
    return ApprovalDraft(
        kind="action",
        action_type=action_type,
        title=title[:200],
        summary=summary,
        amount_usd=amount_usd,
        resource=resource,
        labels=merged,
        payload=payload,
    )


# ------------------------------------------------------------------ anti-flooding
_PENDING: dict[str, tuple[float, list[Any]]] = {}
PENDING_TTL_S = 2.0


async def _pending(rt: Any) -> list[Any]:
    key = str(id(rt))
    now = time.monotonic()
    hit = _PENDING.get(key)
    if hit is not None and now - hit[0] < PENDING_TTL_S:
        return hit[1]
    try:
        reqs = list(await rt.approvals.list_requests(status="pending"))
    except Exception as exc:
        log.debug("flood check skipped error=%s", exc)
        reqs = []
    _PENDING[key] = (now, reqs)
    return reqs


def clear_cache() -> None:
    _PENDING.clear()


async def flood_check(
    ctx: RequestContext, interaction: Interaction, max_pending: int
) -> str | None:
    """Reason string when the principal already has >= ``max_pending`` OTHER pending approvals."""
    if max_pending <= 0:
        return None
    rt = art.current_rt()
    if rt is None or getattr(rt, "approvals", None) is None:
        return None
    principal = ctx.identity.principal
    if not ctx.identity.agent_id:
        return (
            None  # humans are not throttled here (approvals-engine has max_pending_per_principal)
        )
    try:
        fp = rt.approvals.fingerprint(ctx.identity, interaction)
    except Exception:
        fp = None
    reqs = await _pending(rt)
    others = [
        r
        for r in reqs
        if getattr(getattr(r, "requester", None), "principal", None) == principal
        and getattr(r, "fingerprint", None) != fp
        and getattr(r, "kind", "action") == "action"
    ]
    if len(others) >= max_pending:
        return (
            f"too many pending approvals ({len(others)} ≥ {max_pending}) for "
            f"{ctx.identity.agent_id}; resolve them before requesting more"
        )
    return None


def preview_route(ctx: RequestContext, draft: ApprovalDraft) -> dict[str, Any] | None:
    """Who would approve (``rt.approvals.route``) -> ``{required_role, rule_id, two_person}``."""
    rt = art.current_rt()
    if rt is None or getattr(rt, "approvals", None) is None:
        return None
    try:
        route = rt.approvals.route(
            kind=draft.kind,
            action_type=draft.action_type,
            requester=ctx.identity,
            amount_usd=draft.amount_usd,
            resource=draft.resource,
            labels=draft.labels,
        )
    except Exception:
        return None
    try:
        return {
            "required_role": route.required_role,
            "rule_id": route.rule_id,
            "two_person": route.two_person,
        }
    except Exception:
        return None


__all__ = [
    "agent_note",
    "build_draft",
    "clear_cache",
    "flood_check",
    "masked_args",
    "preview_route",
]
