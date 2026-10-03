"""Approval fingerprints: HMAC over canonical JSON of the exact parameters (CONTRACTS section 3.5).

A grant is bound to these parameters: the same call (hook or MCP proxy, retried) yields the same
fingerprint, a call with other parameters never does. Volatile keys (request ids, nonces,
timestamps, ...) are removed first; numbers are normalized so `50 == 50.0`.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from aegis.approvals.compat import hmac_hex
from aegis.core.types import ApprovalDraft, Identity, Interaction

#: removed at every depth of tool arguments / payloads before fingerprinting
VOLATILE_KEYS: frozenset[str] = frozenset(
    {
        "request_id", "idempotency_key", "nonce", "timestamp", "ts", "_meta", "session_id",
        "trace_id", "cache_control",
    }
)
#: removed at the top level of built-in tool args only (Claude Code Bash `description`,
#: `timeout`, `run_in_background`; the hook strips them too). Never stripped for MCP tools,
#: where e.g. `description` can be the substance of the call.
BUILTIN_VOLATILE_KEYS: frozenset[str] = frozenset({"description", "timeout", "run_in_background"})

PURPOSE = "approval"


def _norm(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        if value.is_integer():
            return int(value)
        return round(value, 6)
    if isinstance(value, Mapping):
        return {str(k): _norm(v) for k, v in value.items() if str(k) not in VOLATILE_KEYS}
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    if hasattr(value, "model_dump"):
        return _norm(value.model_dump(mode="json"))
    return str(value)


def canonical_json(obj: Any) -> str:
    """Sorted keys, compact separators, normalized numbers, volatile keys removed."""
    return json.dumps(_norm(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _amount(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def strip_args(tool_name: str | None, args: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if args is None:
        return None
    out = dict(args)
    if tool_name and "." not in tool_name:  # built-in tool (Bash, Read, ...)
        for key in BUILTIN_VOLATILE_KEYS:
            out.pop(key, None)
    return out


def interaction_material(identity: Identity, interaction: Interaction) -> dict[str, Any]:
    """The exact parameters an action approval is bound to."""
    op = interaction.tool_name or interaction.action_type or (
        f"{interaction.kind}:{interaction.surface}"
    )
    material: dict[str, Any] = {
        "org": identity.org_id,
        "principal": identity.principal,
        "op": op,
        "args": strip_args(interaction.tool_name, interaction.tool_args),
        "resource": interaction.resource,
        "amount_usd": _amount(interaction.amount_usd),
    }
    if interaction.tool_args is None:
        # egress / model hops have no tool args: bind URL, method and the content digest
        if interaction.url:
            material["url"] = interaction.url
        if interaction.http_method:
            material["method"] = interaction.http_method.upper()
        if interaction.segments:
            material["text"] = interaction.text()
    if interaction.kind == "config_change":
        material["changes"] = interaction.meta.get("changes")
    return material


def fp_interaction(identity: Identity, interaction: Interaction) -> str:
    return hmac_hex(canonical_json(interaction_material(identity, interaction)), purpose=PURPOSE)


def draft_material(identity: Identity, draft: ApprovalDraft) -> dict[str, Any]:
    """Binding material for non-action drafts (budget raise, config change, MCP re-pin) and for
    manual requests. Budget raises deduplicate per principal+scope (the proposed value changes
    every time the agent retries); MCP re-pins per tool hash, whoever triggered them."""
    payload = draft.payload or {}
    base: dict[str, Any] = {"org": identity.org_id, "kind": draft.kind, "action": draft.action_type}
    if draft.kind == "budget_raise":
        base |= {
            "principal": identity.principal,
            "resource": draft.resource,
            "scope": payload.get("scope") or draft.labels.get("scope"),
            "window": payload.get("window") or draft.labels.get("window"),
            "dimension": payload.get("dimension") or draft.labels.get("dimension"),
        }
    elif draft.kind == "mcp_pin":
        base |= {
            "resource": draft.resource,
            "server": payload.get("server"),
            "tool": payload.get("tool"),
            "new_hash": payload.get("new_hash"),
        }
    elif draft.kind == "config_change":
        proposal = payload.get("proposal") if isinstance(payload.get("proposal"), Mapping) else {}
        base |= {
            "principal": identity.principal,
            "resource": draft.resource,
            "changes": payload.get("changes"),
            "sha256": (proposal or {}).get("sha256"),
            "patch": payload.get("patch") or (proposal or {}).get("patch"),
        }
    else:
        base |= {
            "principal": identity.principal,
            "resource": draft.resource,
            "amount_usd": _amount(draft.amount_usd),
            "labels": dict(draft.labels),
            "payload": payload,
        }
    return base


def fp_draft(identity: Identity, draft: ApprovalDraft) -> str:
    return hmac_hex(canonical_json(draft_material(identity, draft)), purpose=PURPOSE)


__all__ = [
    "BUILTIN_VOLATILE_KEYS", "PURPOSE", "VOLATILE_KEYS", "canonical_json", "draft_material",
    "fp_draft", "fp_interaction", "interaction_material", "strip_args",
]
