"""Lenient pydantic models for Claude Code hook inputs (one per event).

Every model keeps unknown fields (`extra="allow"`) because hook inputs drift between Claude Code
versions (2.1.271 vs 2.1.286: `mcp_server`, `prompt_id`, `agent_id`, ...). Parsing never
fails on a missing optional field; only a non-object body is rejected by `parse_event`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

#: Events this integration understands (anything else -> `{}`).
HOOK_EVENTS: tuple[str, ...] = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "ConfigChange",
    "Stop",
    "SubagentStop",
    "SessionEnd",
    "Notification",
    "PreCompact",
)

#: Events whose failure must DENY (fail-closed). Mirrors scripts/aegis-hook.
BLOCKING_EVENTS: frozenset[str] = frozenset(
    {"PreToolUse", "UserPromptSubmit", "ConfigChange", "PermissionRequest"}
)


class HookBase(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    session_id: str | None = None
    transcript_path: str | None = None
    cwd: str | None = None
    permission_mode: str | None = None
    hook_event_name: str | None = ""
    prompt_id: str | None = None
    agent_id: str | None = None
    agent_type: str | None = None


class PreToolUseEvent(HookBase):
    tool_name: str | None = ""
    tool_input: Any = None
    tool_use_id: str | None = None
    mcp_server: Any = None  # >= 2.1.274: {"name": "..."} (or a plain string)


class PostToolUseEvent(PreToolUseEvent):
    tool_response: Any = None
    duration_ms: float | None = None


class PostToolUseFailureEvent(PreToolUseEvent):
    error: Any = None
    is_interrupt: bool | None = None


class UserPromptSubmitEvent(HookBase):
    prompt: str | None = ""


class SessionStartEvent(HookBase):
    source: str | None = None
    model: Any = None


class ConfigChangeEvent(HookBase):
    source: str | None = None
    file_path: str | None = None


class GenericEvent(HookBase):
    pass


_MODELS: dict[str, type[HookBase]] = {
    "PreToolUse": PreToolUseEvent,
    "PermissionRequest": PreToolUseEvent,
    "PostToolUse": PostToolUseEvent,
    "PostToolUseFailure": PostToolUseFailureEvent,
    "UserPromptSubmit": UserPromptSubmitEvent,
    "SessionStart": SessionStartEvent,
    "ConfigChange": ConfigChangeEvent,
}


def parse_event(body: dict[str, Any], event: str | None = None) -> HookBase:
    """Parse a hook body into its event model. `event` overrides `hook_event_name` when the
    body lacks it. Raises `ValueError` for bodies that are not objects or fail validation."""
    if not isinstance(body, dict):
        raise ValueError("hook body must be a JSON object")
    name = str(body.get("hook_event_name") or event or "")
    model = _MODELS.get(name, GenericEvent)
    data = dict(body)
    data["hook_event_name"] = name
    try:
        return model.model_validate(data)
    except ValidationError as exc:  # pragma: no cover - lenient models rarely fail
        raise ValueError(f"invalid {name} hook body: {exc.error_count()} errors") from exc


__all__ = [
    "BLOCKING_EVENTS",
    "HOOK_EVENTS",
    "ConfigChangeEvent",
    "GenericEvent",
    "HookBase",
    "PostToolUseEvent",
    "PostToolUseFailureEvent",
    "PreToolUseEvent",
    "SessionStartEvent",
    "UserPromptSubmitEvent",
    "parse_event",
]
