"""`review` block of an approval as served to the dashboard / SSE (ASI09 human-agent trust).

Additive, derived only from the already-masked stored request (never raw args), so the approval
card can render — independently of any agent prose —

* ``bound``: exactly what the grant authorizes (tool, masked args, amount, destination, surface)
  plus the HMAC parameter fingerprint the grant is bound to (``params_hash`` = first 16 hex);
* ``agent_text``: every piece of agent-written free text (``agent_note``, ``justification`` /
  ``reason`` / … args), flagged ``untrusted`` so the UI labels it "Written by the agent";
* ``risk``: why Aegis held the call — control id, Aegis's reason, routing rule matched (+ its
  human ``when``), failed checks, flood cap / replay markers;
* ``destructive`` (+ ``destructive_reason``): the UI requires a typed confirm before approving;
* ``title_agent_fields``: arg keys whose (masked) value is interpolated into the title, i.e.
  the title is partly agent-controlled.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Agent-written free-text args (superset of aegis.actions.drafts.NOTE_ARGS).
AGENT_TEXT_ARGS = (
    "justification", "reason", "rationale", "note", "notes", "why", "explanation",
    "comment", "message_to_approver", "context",
)
DEST_ARGS = (
    "to", "recipient", "recipients", "email", "destination", "dest", "url", "host", "channel",
    "account", "iban", "payee", "vendor", "bucket", "target", "repo", "environment", "env",
)
_DESTRUCTIVE_RX = re.compile(
    r"(delete|drop|destroy|purge|wipe|truncate|terminate|revoke|remove|rm_|"
    r"export|transfer|wire|deploy|kill|reset|disable)",
    re.I,
)
_DESTRUCTIVE_SQL_RX = re.compile(r"\b(delete\s+from|drop\s+(table|database|schema)|truncate|alter\s+table|update\s+\w+\s+set)\b", re.I)
MAX_AGENT_TEXT = 600


def _rec(v: Any) -> dict[str, Any]:
    return v if isinstance(v, Mapping) else {}  # type: ignore[return-value]


def _str(v: Any) -> str | None:
    return v if isinstance(v, str) and v.strip() else None


def _destination(args: Mapping[str, Any], bound: Mapping[str, Any], labels: Mapping[str, Any]) -> str | None:
    for k in DEST_ARGS:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return f"{k}: {v}"
        if isinstance(v, list) and v and all(isinstance(x, str) for x in v):
            return f"{k}: {', '.join(v[:5])}{' …' if len(v) > 5 else ''}"
    if _str(bound.get("url")):
        return f"url: {bound['url']}"
    if _str(bound.get("resource")):
        return f"resource: {bound['resource']}"
    if _str(labels.get("dest")):
        return f"dest: {labels['dest']}"
    return None


def _destructive(kind: str, action_type: str, tool: str | None, args: Mapping[str, Any],
                 labels: Mapping[str, Any]) -> str | None:
    if str(labels.get("loosening", "")).lower() == "true":
        return "loosens a security control"
    if kind == "action":
        for name in (tool, action_type):
            m = _DESTRUCTIVE_RX.search(name or "")
            if m:
                return f"{'tool' if name == tool else 'action'} '{name}' is irreversible or high-impact ({m.group(1).lower()})"
        for v in args.values():
            if isinstance(v, str) and _DESTRUCTIVE_SQL_RX.search(v):
                return "SQL statement modifies or deletes data"
    if str(labels.get("env", "")).lower() == "prod" and kind == "action":
        return "targets production"
    return None


def review_block(data: Mapping[str, Any]) -> dict[str, Any]:
    """Build the `review` block from a JSON-dumped (already masked) ApprovalRequest."""
    payload = _rec(data.get("payload"))
    bound = _rec(payload.get("bound"))
    labels = _rec(data.get("labels"))
    routing = _rec(payload.get("routing"))
    explain = _rec(payload.get("explain"))
    kind = str(data.get("kind") or "action")
    action_type = str(data.get("action_type") or "")

    tool = _str(bound.get("tool_name")) or _str(payload.get("tool")) or _str(payload.get("tool_name"))
    args_src = bound.get("args_masked") if "args_masked" in bound else (
        payload.get("args") if "args" in payload else payload.get("tool_args"))
    args = _rec(args_src)
    amount = bound.get("amount_usd")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        amount = data.get("amount_usd")

    agent_text: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(field: str, text: Any, source: str) -> None:
        t = _str(text)
        if t is None or t in seen:
            return
        seen.add(t)
        agent_text.append({"field": field, "text": t[:MAX_AGENT_TEXT], "source": source,
                           "untrusted": True})

    _add("agent_note", payload.get("agent_note"), "payload.agent_note")
    _add("justification", payload.get("justification"), "payload.justification")
    for k in AGENT_TEXT_ARGS:
        _add(k, args.get(k), "bound.args" if "args_masked" in bound else "payload.args")

    checks = [c for c in (payload.get("checks") or explain.get("checks") or []) if isinstance(c, Mapping)]
    failed = [
        {"name": c.get("name") or c.get("label") or c.get("id"), "detail": c.get("detail"),
         "value": c.get("value"), "limit": c.get("limit"), "param": c.get("param")}
        for c in checks if c.get("ok") is False or c.get("result") == "fail"
    ][:8]
    aegis_reason = _str(explain.get("summary")) or (
        _str(payload.get("reason")) if kind == "action" else None) or _str(data.get("summary"))

    title = str(data.get("title") or "")
    title_fields = sorted(
        k for k, v in args.items()
        if isinstance(v, str) and len(v.strip()) >= 3 and v.strip() in title
        and k not in ("amount_usd",)
    )

    fp = str(data.get("fingerprint") or "")
    reason = _destructive(kind, action_type, tool, args, labels)
    return {
        "bound": {
            "present": bool(bound),
            "tool": tool,
            "args": args_src if isinstance(args_src, (Mapping, list)) else None,
            "amount_usd": amount,
            "destination": _destination(args, bound, labels),
            "resource": bound.get("resource") or data.get("resource"),
            "surface": bound.get("surface"),
            "mcp_server": bound.get("mcp_server"),
            "method": bound.get("method"),
            "url": bound.get("url"),
            "fingerprint": fp if fp and fp != "-" else None,
            "params_hash": fp[:16] if fp and fp != "-" else None,
            "max_uses": data.get("max_uses"),
            "grant_ttl_s": routing.get("grant_ttl_s"),
        },
        "agent_text": agent_text,
        "risk": {
            "control_id": data.get("control_id") or payload.get("control_id"),
            "reason": aegis_reason,
            "rule_id": data.get("rule_id"),
            "rule_when": routing.get("when"),
            "rule_description": routing.get("description"),
            "failed_checks": failed,
            "flood_cap": routing.get("flood_cap"),
            "replay_of": payload.get("replay_of"),
        },
        "destructive": reason is not None,
        "destructive_reason": reason,
        "title_agent_fields": title_fields,
    }


__all__ = ["AGENT_TEXT_ARGS", "review_block"]
