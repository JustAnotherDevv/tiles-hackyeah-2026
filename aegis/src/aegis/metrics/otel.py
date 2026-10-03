"""OpenTelemetry GenAI semantic-convention attributes (semconv v1.41 names, research 04 section 4.2).

Used for `data.otel` in decision/outcome audit records and reused by OCSF `unmapped.otel`.
Content attributes (`gen_ai.input.messages`, ...) are never emitted (OTel privacy-first default).
"""

from __future__ import annotations

from typing import Any

SEMCONV_VERSION = "1.41.0"

_MCP_METHOD = {
    "mcp.init": "initialize",
    "mcp.list": "tools/list",
    "mcp.call": "tools/call",
    "mcp.result": "tools/call",
}


def operation_name(kind: str | None, surface: str | None) -> str | None:
    if kind == "model_call":
        return "chat"
    if kind in {"tool_call", "mcp"} and surface not in {"mcp.init", "mcp.list"}:
        return "execute_tool"
    if kind == "a2a":
        return "invoke_agent"
    return None


def genai_attributes(
    summary: dict[str, Any] | None,
    usage: dict[str, Any] | None = None,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = summary or {}
    attrs: dict[str, Any] = {}
    kind, surface = s.get("kind"), s.get("surface")
    op = operation_name(kind, surface)
    if op:
        attrs["gen_ai.operation.name"] = op
    dest = s.get("destination") or {}
    provider = dest.get("provider") or dest.get("name")
    if provider and kind in {"model_call", None}:
        attrs["gen_ai.provider.name"] = provider
    if s.get("model"):
        attrs["gen_ai.request.model"] = s["model"]
    out = outcome or {}
    if out.get("model_used"):
        attrs["gen_ai.response.model"] = out["model_used"]
    if out.get("provider") and "gen_ai.provider.name" not in attrs:
        attrs["gen_ai.provider.name"] = out["provider"]
    u = usage or {}
    for key, attr in (
        ("input_tokens", "gen_ai.usage.input_tokens"),
        ("output_tokens", "gen_ai.usage.output_tokens"),
        ("cache_read_tokens", "gen_ai.usage.cache_read.input_tokens"),
        ("cache_write_tokens", "gen_ai.usage.cache_creation.input_tokens"),
    ):
        if u.get(key):
            attrs[attr] = u[key]
    if s.get("session_id"):
        attrs["gen_ai.conversation.id"] = s["session_id"]
    ident = s.get("identity") or {}
    if ident.get("agent_id"):
        attrs["gen_ai.agent.id"] = ident["agent_id"]
        if ident.get("display_name"):
            attrs["gen_ai.agent.name"] = ident["display_name"]
    if s.get("tool_name"):
        attrs["gen_ai.tool.name"] = s["tool_name"]
        attrs["gen_ai.tool.type"] = "extension" if kind == "mcp" else "function"
    if surface in _MCP_METHOD:
        attrs["mcp.method.name"] = _MCP_METHOD[surface]
    if s.get("error_type"):
        attrs["error.type"] = s["error_type"]
    attrs["aegis.decision.action"] = s.get("action")
    if s.get("control_id"):
        attrs["aegis.control.id"] = s["control_id"]
    if surface:
        attrs["aegis.surface"] = surface
    if dest.get("dest_class"):
        attrs["aegis.dest_class"] = dest["dest_class"]
    if s.get("policy_version") is not None:
        attrs["aegis.policy.version"] = s.get("policy_version")
    if s.get("feed_serial") is not None:
        attrs["aegis.feed.serial"] = s.get("feed_serial")
    attrs["aegis.redaction.count"] = int(s.get("redaction_count") or 0)
    attrs["aegis.semconv.version"] = SEMCONV_VERSION
    return {k: v for k, v in attrs.items() if v is not None}


__all__ = ["SEMCONV_VERSION", "genai_attributes", "operation_name"]
