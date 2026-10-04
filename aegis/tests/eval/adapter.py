"""CorpusRow -> EvalCase (frozen `aegis.core.types` Interaction + /v1/guard body).

Mapping (plan 19 §2.4):
- user_prompt  -> model_call / model.request (or prompt.user), destination remote mock-openai
- tool_result  -> tool_call / tool.output, direction in, untrusted segment `tool_response`
- tool_input   -> overlay invocation (tool.input or mcp.call); tool_args string leaves -> segments
- mcp_tool_description -> overlay -> mcp.list with `raw` tool definition + untrusted description
- model_output -> model_call / model.response, untrusted assistant segment
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from aegis.core.types import Destination, Interaction, TextSegment
from tests.corpora.loader import CorpusRow

OVERLAY_PATH = Path(__file__).resolve().parent.parent / "corpora" / "overlays" / "invocations.yaml"
DEFAULT_AGENT = "chaos-agent@platform"
MOCK_REMOTE = Destination(name="mock-openai", dest_class="remote", provider="mock-openai")

# Fallbacks if no policy snapshot is supplied (values mirror config/policy.yaml `destinations`).
_LOCAL_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "LS", "NotebookEdit", "Bash", "TodoWrite"}
_THIRD_PARTY_TOOLS = {"WebFetch", "WebSearch"}
_LOCAL_MCP = {"acme-db", "acme-crm"}


@dataclass
class EvalCase:
    row: CorpusRow
    interaction: Interaction
    guard_body: dict[str, Any]
    agent_id: str = DEFAULT_AGENT
    http_supported: bool = True
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.row.id

    def session_id(self, profile: str) -> str:
        return f"eval-{profile}-{self.row.id}"

    def fresh_interaction(self) -> Interaction:
        """A deep copy (the pipeline may mutate ids/meta); `raw` is preserved."""
        i = self.interaction.model_copy(deep=True)
        i.raw = copy.deepcopy(self.interaction.raw)
        return i


@lru_cache(maxsize=1)
def load_overlays(path: str = str(OVERLAY_PATH)) -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {str(k): dict(v) for k, v in data.items()}


def tool_arg_segments(args: Any, prefix: str = "tool_args") -> list[TextSegment]:
    """Same rule as core's guard builder: every non-empty string leaf -> a `tool_args` segment."""
    try:  # prefer core's implementation so the shapes can never drift
        from aegis.api.routes.guard import tool_arg_segments as core_impl

        return core_impl(args, prefix)
    except Exception:  # pragma: no cover - TODO(integration) fallback only
        out: list[TextSegment] = []

        def walk(value: Any, path: str) -> None:
            if isinstance(value, str):
                if value:
                    out.append(TextSegment(path=path, text=value, role="tool_args"))
            elif isinstance(value, dict):
                for k, v in value.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(value, (list, tuple)):
                for n, v in enumerate(value):
                    walk(v, f"{path}[{n}]")

        walk(args, prefix)
        return out


def _subst(value: Any, text: str) -> Any:
    if value == "$text":
        return text
    if isinstance(value, dict):
        return {k: _subst(v, text) for k, v in value.items()}
    if isinstance(value, list):
        return [_subst(v, text) for v in value]
    return value


def _policy_attr(doc: Any, *path: str) -> Any:
    cur = doc
    for p in path:
        if cur is None:
            return None
        cur = cur.get(p) if isinstance(cur, dict) else getattr(cur, p, None)
    return cur


def tool_destination(tool: str | None, mcp_server: str | None, doc: Any = None) -> Destination:
    if mcp_server:
        servers = _policy_attr(doc, "mcp", "servers") or {}
        cfg = servers.get(mcp_server) if isinstance(servers, dict) else None
        dc = _policy_attr(cfg, "destination") or ("local" if mcp_server in _LOCAL_MCP else "third_party")
        return Destination(name=f"mcp:{mcp_server}", dest_class=dc)
    local = set(_policy_attr(doc, "destinations", "local_tools") or _LOCAL_TOOLS)
    third = set(_policy_attr(doc, "destinations", "third_party_tools") or _THIRD_PARTY_TOOLS)
    if tool in local:
        return Destination(name=f"tool:{tool}", dest_class="local")
    if tool in third:
        return Destination(name=f"tool:{tool}", dest_class="third_party")
    return Destination(name=f"tool:{tool or 'unknown'}", dest_class="third_party")


def _guard_body(i: Interaction, agent_id: str, raw: Any = None) -> dict[str, Any]:
    gi: dict[str, Any] = {
        "kind": i.kind,
        "surface": i.surface,
        "direction": i.direction,
        "destination": i.destination.dest_class,
        "segments": [s.model_dump() for s in i.segments],
        "meta": dict(i.meta),
    }
    for k in ("model", "tool_name", "tool_args", "mcp_server", "mcp_method", "est_input_tokens",
              "max_output_tokens"):
        v = getattr(i, k)
        if v is not None:
            gi[k] = v
    if raw is not None:
        gi["meta"]["raw_result"] = raw  # Addendum A-12
    return {"interaction": gi, "identity": {"agent_id": agent_id}, "dry_run": True}


def to_case(
    row: CorpusRow,
    *,
    prompt_surface: str = "model.request",
    agent_id: str = DEFAULT_AGENT,
    doc: Any = None,
    overlays: dict[str, dict[str, Any]] | None = None,
) -> EvalCase:
    """Map one corpus row to an EvalCase. Raises KeyError if a non-default row has no overlay."""
    ov = (overlays if overlays is not None else load_overlays()).get(row.id)
    surface = row.surface or "user_prompt"
    meta = {"source": "eval", "eval_case": row.id}
    raw: Any = None

    if surface == "user_prompt" and ov is None:
        kind, surf = "model_call", prompt_surface
        if surf == "prompt.user":
            meta["wire"] = "claude-code"
        else:
            meta["wire"] = "openai"
        seg_path = "prompt" if surf == "prompt.user" else "messages[0].content"
        i = Interaction(
            kind=kind, surface=surf, direction="out", destination=MOCK_REMOTE, model="mock-echo",
            segments=[TextSegment(path=seg_path, text=row.text, role="user", trusted=True)],
            est_input_tokens=max(1, len(row.text) // 4), max_output_tokens=256, meta=meta,
        )
    elif surface == "tool_result" and ov is None:
        tool = row.get("tool") or "WebFetch"
        if row.get("user_task"):
            meta["user_task"] = row.get("user_task")
        i = Interaction(
            kind="tool_call", surface="tool.output", direction="in", tool_name=tool,
            destination=Destination(name="agent-context", dest_class="remote"),
            segments=[TextSegment(path="tool_response", text=row.text, role="tool_result", trusted=False)],
            meta=meta,
        )
    elif surface == "model_output" or (ov and ov.get("surface") == "model.response"):
        i = Interaction(
            kind="model_call", surface="model.response", direction="in", destination=MOCK_REMOTE,
            model="mock-echo",
            segments=[TextSegment(path="choices[0].message.content", text=row.text, role="assistant",
                                  trusted=False)],
            meta=meta,
        )
    else:
        if ov is None:
            raise KeyError(f"{row.id}: surface {surface!r} needs an entry in overlays/invocations.yaml")
        surf = ov["surface"]
        if surf == "mcp.list":
            server = ov["mcp_server"]
            tool = ov["tool"]
            raw = {"name": tool, "description": row.text, "inputSchema": {"type": "object"}}
            meta.update({"mcp.list_index": 0})
            i = Interaction(
                kind="mcp", surface="mcp.list", direction="in", mcp_server=server,
                mcp_method="tools/list", tool_name=f"{server}.{tool}",
                destination=tool_destination(None, server, doc),
                segments=[TextSegment(path="result.tools[0].description", text=row.text,
                                      role="tool_description", trusted=False)],
                meta=meta,
            )
            i.raw = raw
        else:
            args = _subst(ov.get("tool_args") or {}, row.text)
            server = ov.get("mcp_server")
            tool = ov["tool_name"]
            i = Interaction(
                kind=ov.get("kind", "tool_call"), surface=surf, direction="out", tool_name=tool,
                tool_args=args, mcp_server=server, mcp_method="tools/call" if server else None,
                destination=tool_destination(tool, server, doc),
                segments=tool_arg_segments(args), meta=meta,
            )
    http_ok = True
    return EvalCase(row=row, interaction=i, guard_body=_guard_body(i, agent_id, raw), agent_id=agent_id,
                    http_supported=http_ok)


def to_cases(rows: list[CorpusRow], **kw: Any) -> list[EvalCase]:
    return [to_case(r, **kw) for r in rows]


__all__ = ["DEFAULT_AGENT", "EvalCase", "load_overlays", "to_case", "to_cases", "tool_destination"]
