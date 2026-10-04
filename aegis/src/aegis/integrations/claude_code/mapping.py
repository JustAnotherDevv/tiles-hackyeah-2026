"""Claude Code hook event -> `Interaction` (pure functions; CONTRACTS sections 3.4-3.5).

| Hook event          | Interaction                                                        |
|---------------------|--------------------------------------------------------------------|
| UserPromptSubmit    | kind=model_call, surface=prompt.user, one segment `prompt`         |
| PreToolUse built-in | kind=tool_call, surface=tool.input, tool_name = Claude Code name   |
| PreToolUse MCP      | kind=mcp, surface=tool.input, tool_name="<server>.<tool>"          |
| PostToolUse         | same kind/tool, surface=tool.output, direction=in, untrusted text  |

Segments carry string paths (`tool_args.edits[0].old_string`) for the pipeline; the exact key
tuples are kept in `Mapped.leaves` so the response writer never has to re-parse a path (tool
argument keys may contain dots or brackets).
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from aegis.core.policy_schema import PolicyDoc
from aegis.core.types import Agent, Destination, Interaction, TextSegment, new_id

from .schema import PostToolUseEvent, PreToolUseEvent, UserPromptSubmitEvent

#: Bash/Agent arguments that change between retries of the "same" call; stripped from
#: `tool_args` (approval fingerprints stay stable) but still scanned as segments.
VOLATILE_KEYS: frozenset[str] = frozenset({"description", "timeout", "run_in_background"})

#: Shape-carrying keys of tool results (MCP content blocks, Read results): never scanned or
#: rewritten, so `updatedToolOutput` keeps a valid structure.
STRUCTURAL_KEYS: frozenset[str] = frozenset({"type", "mimeType", "mime_type", "encoding"})

#: Total text budget per interaction (bytes of str, approximated by len()).
MAX_TEXT_CHARS = 256 * 1024

DEFAULT_LOCAL_TOOLS: tuple[str, ...] = (
    "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "LS", "NotebookEdit", "Bash",
    "TodoWrite", "BashOutput", "KillShell", "Task", "Agent", "Skill", "SlashCommand",
    "ExitPlanMode", "AskUserQuestion", "NotebookRead",
)
DEFAULT_THIRD_PARTY_TOOLS: tuple[str, ...] = ("WebFetch", "WebSearch")

Key = str | int
KeyPath = tuple[Key, ...]

_FALLBACK_KEY = os.urandom(32)


@dataclass
class Mapped:
    """Result of mapping one hook event."""

    interaction: Interaction
    #: root object the segments point into ("tool_input" | "tool_response" | "prompt")
    root: str
    #: segment path -> key path relative to the root object (() = the root itself is a string)
    leaves: dict[str, KeyPath] = field(default_factory=dict)
    #: segment path -> original text (used to write back only what changed)
    original: dict[str, str] = field(default_factory=dict)
    #: segment paths whose text was truncated (never written back)
    truncated: set[str] = field(default_factory=set)
    routed_mcp: bool = False


# ---------------------------------------------------------------- small helpers
def cwd_hash(cwd: str | None) -> str | None:
    """Keyed hash of the working directory (the raw cwd is never stored)."""
    if not cwd:
        return None
    try:
        from aegis.core.crypto import hmac_hex

        return hmac_hex(cwd, purpose="cwd")[:16]
    except Exception:  # TODO(integration): core crypto unavailable -> per-process key
        return hmac.new(_FALLBACK_KEY, cwd.encode(), hashlib.sha256).hexdigest()[:16]


def normalize_tool_name(raw: str | None, mcp_server: Any = None) -> tuple[str, str | None]:
    """`mcp__acme-db__query` -> (`acme-db.query`, `acme-db`); built-ins keep their name.

    `mcp_server` (hook input >= 2.1.274) wins when present: `{"name": "acme-db"}` or a string.
    """
    name = raw or ""
    server_hint: str | None = None
    if isinstance(mcp_server, dict):
        server_hint = mcp_server.get("name") or mcp_server.get("server") or None
    elif isinstance(mcp_server, str) and mcp_server:
        server_hint = mcp_server
    if name.startswith("mcp__"):
        rest = name[len("mcp__"):]
        if server_hint and rest.startswith(server_hint + "__"):
            return f"{server_hint}.{rest[len(server_hint) + 2:]}", server_hint
        server, sep, tool = rest.partition("__")
        if sep and server and tool:
            return f"{server}.{tool}", server
        return rest or name, server_hint or (rest or None)
    if server_hint:
        return f"{server_hint}.{name}", server_hint
    return name, None


def _fmt_path(prefix: str, keys: KeyPath) -> str:
    out = prefix
    for k in keys:
        if isinstance(k, int):
            out += f"[{k}]"
        else:
            out = f"{out}.{k}" if out else str(k)
    return out


def iter_string_leaves(obj: Any, keys: KeyPath = ()) -> Iterator[tuple[KeyPath, str]]:
    """Yield (key path, text) for every string leaf, depth-first, in insertion order."""
    if isinstance(obj, str):
        yield keys, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_string_leaves(v, (*keys, str(k)))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from iter_string_leaves(v, (*keys, i))


def get_by_keys(obj: Any, keys: KeyPath) -> Any:
    cur = obj
    for k in keys:
        cur = cur[k]
    return cur


def set_by_keys(obj: Any, keys: KeyPath, value: Any) -> Any:
    """Set a leaf in place; returns the (possibly replaced) root."""
    if not keys:
        return value
    cur = obj
    for k in keys[:-1]:
        cur = cur[k]
    cur[keys[-1]] = value
    return obj


def _segments(
    root_obj: Any,
    prefix: str,
    *,
    role: str,
    trusted: bool,
    mapped: Mapped,
    budget: list[int],
    skip_structural: bool = False,
) -> list[TextSegment]:
    segs: list[TextSegment] = []
    for keys, text in iter_string_leaves(root_obj):
        if not text:
            continue
        if skip_structural and keys and keys[-1] in STRUCTURAL_KEYS:
            continue
        path = _fmt_path(prefix, keys)
        redactable = True
        if budget[0] <= 0:
            mapped.interaction.meta["truncated"] = True
            continue
        if len(text) > budget[0]:
            text = text[: budget[0]]
            redactable = False
            mapped.truncated.add(path)
            mapped.interaction.meta["truncated"] = True
        budget[0] -= len(text)
        mapped.leaves[path] = keys
        mapped.original[path] = text
        segs.append(
            TextSegment(path=path, text=text, role=role, trusted=trusted, redactable=redactable)  # type: ignore[arg-type]
        )
    return segs


def _doc(doc: PolicyDoc | None) -> PolicyDoc:
    return doc if doc is not None else PolicyDoc()


def model_context_destination(agent: Agent | None) -> Destination:
    """Where content coming back to the agent goes next: its model context."""
    if agent is not None and agent.max_destination == "local":
        return Destination(name="model-context:local", dest_class="local")
    return Destination(name="anthropic", dest_class="remote", provider="anthropic")


def tool_destination(
    tool_name: str,
    tool_input: Any,
    doc: PolicyDoc | None,
    mcp_server: str | None,
) -> tuple[Destination, str | None, bool]:
    """(destination, url, routed_mcp) for a tool call (CONTRACTS section 3.4)."""
    d = _doc(doc)
    if mcp_server:
        cfg = d.mcp.servers.get(mcp_server)
        dest_class = cfg.destination if cfg is not None else "third_party"
        return (
            Destination(name=f"mcp:{mcp_server}", dest_class=dest_class, provider="mcp"),
            None,
            cfg is not None,
        )
    third = set(d.destinations.third_party_tools or DEFAULT_THIRD_PARTY_TOOLS)
    if tool_name in third:
        url = tool_input.get("url") if isinstance(tool_input, dict) else None
        url = url if isinstance(url, str) and url else None
        host = None
        if url:
            try:
                host = urlsplit(url).hostname
            except ValueError:
                host = None
        label = host or tool_name.lower()
        return (
            Destination(name=f"egress:{label}", dest_class="third_party", host=host, url=url),
            url,
            False,
        )
    return Destination(name=f"local:{tool_name}", dest_class="local"), None, False


def _cc_meta(ev: Any, *, raw_tool_name: str | None, routed_mcp: bool) -> dict[str, Any]:
    return {
        "session_id": ev.session_id,
        "request_class": None,
        "hook_event": ev.hook_event_name,
        "tool_use_id": getattr(ev, "tool_use_id", None),
        "raw_tool_name": raw_tool_name,
        "permission_mode": ev.permission_mode,
        "agent_id": ev.agent_id,
        "agent_type": ev.agent_type,
        "prompt_id": ev.prompt_id,
        "routed_mcp": routed_mcp,
        "cwd_hash": cwd_hash(ev.cwd),
    }


def _meta(ev: Any, *, raw_tool_name: str | None, routed_mcp: bool) -> dict[str, Any]:
    """Addendum A-13: `meta.client`, `meta.claude_code{...}` and hook `cwd` -> `meta.cwd`."""
    out: dict[str, Any] = {
        "client": "claude-code",
        "claude_code": _cc_meta(ev, raw_tool_name=raw_tool_name, routed_mcp=routed_mcp),
    }
    if ev.cwd:
        out["cwd"] = ev.cwd
    return out


# ---------------------------------------------------------------- public mappers
def map_tool_input(
    ev: PreToolUseEvent, doc: PolicyDoc | None = None, agent: Agent | None = None
) -> Mapped:
    """PreToolUse -> `tool.input` interaction."""
    raw_name = ev.tool_name or ""
    tool_name, server = normalize_tool_name(raw_name, ev.mcp_server)
    tool_input = ev.tool_input if ev.tool_input is not None else {}
    dest, url, routed = tool_destination(tool_name, tool_input, doc, server)
    if isinstance(tool_input, dict):
        tool_args = {k: copy.deepcopy(v) for k, v in tool_input.items() if k not in VOLATILE_KEYS}
    else:
        tool_args = {"input": copy.deepcopy(tool_input)}
    interaction = Interaction(
        id=new_id("int"),
        kind="mcp" if server else "tool_call",
        surface="tool.input",
        direction="out",
        destination=dest,
        tool_name=tool_name,
        tool_args=tool_args,
        mcp_server=server,
        mcp_method="tools/call" if server else None,
        http_method="GET" if url else None,
        url=url,
        raw=tool_input,
        meta=_meta(ev, raw_tool_name=raw_name, routed_mcp=routed),
    )
    mapped = Mapped(interaction=interaction, root="tool_input", routed_mcp=routed)
    prefix = "tool_args" if isinstance(tool_input, dict) else "tool_args.input"
    interaction.segments = _segments(
        tool_input, prefix, role="tool_args", trusted=True, mapped=mapped, budget=[MAX_TEXT_CHARS]
    )
    return mapped


def map_tool_output(
    ev: PostToolUseEvent,
    doc: PolicyDoc | None = None,
    agent: Agent | None = None,
    *,
    parent_id: str | None = None,
) -> Mapped:
    """PostToolUse -> `tool.output` interaction (untrusted segments, direction in)."""
    raw_name = ev.tool_name or ""
    tool_name, server = normalize_tool_name(raw_name, ev.mcp_server)
    _, _, routed = tool_destination(tool_name, ev.tool_input or {}, doc, server)
    response = ev.tool_response
    tool_args = None
    if isinstance(ev.tool_input, dict):
        tool_args = {k: v for k, v in ev.tool_input.items() if k not in VOLATILE_KEYS}
    interaction = Interaction(
        id=new_id("int"),
        kind="mcp" if server else "tool_call",
        surface="tool.output",
        direction="in",
        destination=model_context_destination(agent),
        tool_name=tool_name,
        tool_args=tool_args,
        mcp_server=server,
        mcp_method="tools/call" if server else None,
        parent_id=parent_id,
        raw=response,
        meta=_meta(ev, raw_tool_name=raw_name, routed_mcp=routed),
    )
    mapped = Mapped(interaction=interaction, root="tool_response", routed_mcp=routed)
    interaction.segments = _segments(
        response, "tool_response", role="tool_result", trusted=False, mapped=mapped,
        budget=[MAX_TEXT_CHARS], skip_structural=True,
    )
    return mapped


def map_prompt(
    ev: UserPromptSubmitEvent, doc: PolicyDoc | None = None, agent: Agent | None = None
) -> Mapped:
    """UserPromptSubmit -> `prompt.user` interaction (the hook can block, not rewrite)."""
    interaction = Interaction(
        id=new_id("int"),
        kind="model_call",
        surface="prompt.user",
        direction="out",
        destination=model_context_destination(agent),
        raw=ev.prompt,
        meta=_meta(ev, raw_tool_name=None, routed_mcp=False),
    )
    mapped = Mapped(interaction=interaction, root="prompt")
    interaction.segments = _segments(
        ev.prompt or "", "prompt", role="user", trusted=True, mapped=mapped,
        budget=[MAX_TEXT_CHARS],
    )
    return mapped


def map_config_change(
    ev: Any, info: dict[str, Any] | None = None, *, problem: str | None = None
) -> Mapped:
    """ConfigChange -> `config.change` interaction for GOV-06 (no segments: the settings file
    content never enters the pipeline; only the guarded key names that changed)."""
    data = dict(info or {})
    interaction = Interaction(
        id=new_id("int"),
        kind="config_change",
        surface="config.change",
        direction="out",
        destination=Destination(name="local:claude-code-settings", dest_class="local"),
        tool_name="claude_code.settings",
        tool_args={"source": data.get("source"), "file": data.get("file"),
                   "changed_keys": list(data.get("changed_keys") or [])},
        meta={
            **_meta(ev, raw_tool_name=None, routed_mcp=False),
            "config_change": {
                "source": data.get("source") or getattr(ev, "source", None) or "unknown",
                "file": data.get("file"),
                "changed_keys": list(data.get("changed_keys") or []),
                "problem": problem,
            },
        },
    )
    return Mapped(interaction=interaction, root="config")


__all__ = [
    "MAX_TEXT_CHARS",
    "STRUCTURAL_KEYS",
    "VOLATILE_KEYS",
    "Mapped",
    "cwd_hash",
    "get_by_keys",
    "iter_string_leaves",
    "map_config_change",
    "map_prompt",
    "map_tool_input",
    "map_tool_output",
    "model_context_destination",
    "normalize_tool_name",
    "set_by_keys",
    "tool_destination",
]
