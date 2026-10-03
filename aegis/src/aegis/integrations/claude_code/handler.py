"""Claude Code hook orchestration (plan 12 §2.5): one entry point, `handle_hook`.

    out = await handle_hook(rt, raw_body, headers, base_url)   # always a dict (never raises)

Per event:
- PreToolUse        -> pipeline `tool.input` (hold for approvals), pending registry, deny/allow/
                       updatedInput (redact or DLP-08 local rehydration)
- PostToolUse       -> `complete()` of the PreToolUse, then pipeline `tool.output` ->
                       updatedToolOutput (neutralised) or withheld output
- PostToolUseFailure-> `complete()` with status 500
- UserPromptSubmit  -> budget pre-check, then pipeline `prompt.user` -> block / user note
- SessionStart      -> session registration, audit + bus `system`, banner + status line
- ConfigChange      -> tamper guard (guards.config_change), audit + bus
- Stop / SessionEnd -> sweep this session's pending entries (`complete()` with 499)

Fail-closed: malformed bodies for blocking events, a missing runtime, or any exception produce
`respond.fail_closed_output(event)`; non-blocking events answer `{}`.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
import time
from collections import Counter, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from aegis.core.policy_schema import PolicySnapshot
from aegis.core.types import (
    Agent,
    AuditEvent,
    Identity,
    Interaction,
    Outcome,
    RequestContext,
    Usage,
    Verdict,
    new_id,
    utcnow,
)

from . import guards, mapping, respond, selfcheck
from .pending import PendingEntry, PendingRegistry
from .schema import BLOCKING_EVENTS, parse_event

log = logging.getLogger(__name__)

DEFAULT_AGENT = "claude-code@platform"
DEFAULT_BASE_URL = "http://127.0.0.1:8787"
DEFAULT_DEADLINE_S = 110.0
MAX_BODY_BYTES = 2 * 1024 * 1024
METRIC = "aegis_claude_code_hook_events_total"
_SECRET_HEADERS = {"authorization", "x-api-key", "x-aegis-agent-key", "cookie", "proxy-authorization"}
_PLACEHOLDER = re.compile(r"\[[A-Z][A-Z0-9_]*_\d+\]")


# ---------------------------------------------------------------- per-runtime state
@dataclass
class HookState:
    pending: PendingRegistry = field(default_factory=PendingRegistry)
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    rtt_ms: deque[float] = field(default_factory=lambda: deque(maxlen=500))
    events: Counter[str] = field(default_factory=Counter)
    last_event: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        rtts = sorted(self.rtt_ms)
        p50 = statistics.median(rtts) if rtts else None
        p95 = rtts[min(len(rtts) - 1, int(len(rtts) * 0.95))] if rtts else None
        return {
            "sessions": [
                {"session_id": sid, **{k: v for k, v in s.items() if k != "cwd_hash"}}
                for sid, s in sorted(
                    self.sessions.items(), key=lambda kv: kv[1].get("last_seen", ""), reverse=True
                )[:50]
            ],
            "events": dict(self.events),
            "last_event": self.last_event,
            "pending": len(self.pending),
            "hook_rtt_ms": {"p50": p50, "p95": p95, "n": len(rtts)},
        }


_STATES: dict[int, HookState] = {}


def state_for(rt: Any) -> HookState:
    """HookState attached to the runtime (falls back to a module dict for frozen objects)."""
    st = getattr(rt, "_aegis_claude_code_state", None)
    if isinstance(st, HookState):
        return st
    st = HookState()
    try:
        rt._aegis_claude_code_state = st
    except Exception:
        st = _STATES.setdefault(id(rt), st)
    return st


# ---------------------------------------------------------------- call context
@dataclass
class _Call:
    rt: Any
    event: str
    body: dict[str, Any]
    hdr: dict[str, str]
    base_url: str
    state: HookState
    snap: PolicySnapshot | None
    params: guards.IntegrationParams
    identity: Identity
    agent: Agent | None
    agent_id: str
    session_id: str
    deadline_s: float
    safe_headers: dict[str, str]
    pipeline_s: float = 0.0


def _parse_body(raw: bytes | str | None) -> dict[str, Any]:
    if raw is None or len(raw) == 0:
        raise ValueError("empty body")
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError("body too large")
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise ValueError("body is not a JSON object")
    return body


def _float(v: str | None, default: float) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _snapshot(rt: Any) -> PolicySnapshot | None:
    try:
        return rt.policy.snapshot()
    except Exception:
        log.warning("policy snapshot unavailable for claude code hook")
        return None


async def _resolve(rt: Any, hdr: dict[str, str], body: dict[str, Any]) -> tuple[Identity, Agent | None, str]:
    agent_hint = hdr.get("x-aegis-agent") or DEFAULT_AGENT
    try:
        identity = await rt.org.resolve_identity(hdr, hints={"agent_id": agent_hint})
    except Exception:
        log.warning("identity resolution failed; using header identity agent=%s", agent_hint)
        identity = Identity(agent_id=agent_hint, role="agent")
    agent_id = identity.agent_id or agent_hint
    agent: Agent | None = None
    try:
        agent = await rt.org.get_agent(agent_id)
    except Exception:
        agent = None
    return identity, agent, agent_id


def _control_name(c: _Call, control_id: str | None) -> str | None:
    if not control_id:
        return None
    try:
        ctl = c.rt.controls.get(control_id)
        name = getattr(ctl, "name", None)
        if name:
            return str(name)
    except Exception:
        pass
    if c.snap is not None:
        cfg = c.snap.controls.get(control_id)
        if cfg is not None and cfg.name:
            return cfg.name
    return None


def _primary_id(v: Verdict) -> str | None:
    return v.primary.control_id if v.primary else None


# ---------------------------------------------------------------- side-effect helpers
async def _audit(c: _Call, data: dict[str, Any]) -> None:
    try:
        await c.rt.audit.record(
            AuditEvent(
                event_id=new_id("evt"),
                event_type="system",
                actor=c.identity,
                session_id=c.session_id,
                data={"component": "claude-code", **data},
            )
        )
    except Exception:
        log.warning("audit record failed event=%s", data.get("event"))


def _bus(c: _Call, level: str, message: str) -> None:
    try:
        c.rt.bus.publish("system", {"level": level, "message": message, "component": "claude-code"})
    except Exception:
        log.debug("bus publish failed")


async def _complete(
    rt: Any, ctx: RequestContext, interaction: Interaction, verdict: Verdict, outcome: Outcome
) -> None:
    try:
        await rt.pipeline.complete(ctx, interaction, verdict, outcome)
    except Exception:
        log.exception("pipeline complete failed interaction=%s", interaction.id)


async def _complete_abandoned(rt: Any, entries: list[PendingEntry], why: str) -> None:
    for e in entries:
        await _complete(
            rt, e.ctx, e.interaction, e.verdict,
            Outcome(status_code=499, error=why, usage=Usage(requests=0)),
        )


async def _evaluate(c: _Call, ctx: RequestContext, interaction: Interaction) -> Verdict:
    t = time.perf_counter()
    try:
        return await c.rt.pipeline.evaluate(ctx, interaction)
    finally:
        c.pipeline_s += time.perf_counter() - t


def _new_ctx(c: _Call, *, hold: float = 0.0) -> RequestContext:
    return c.rt.pipeline.new_context(
        source="hook",
        identity=c.identity,
        session_id=c.session_id,
        headers=c.safe_headers,
        approval_token=c.hdr.get("x-aegis-approval") or None,
        wait_for_approval_s=hold,
    )


def _session_data(c: _Call) -> dict[str, Any]:
    """`rt.sessions.get(sid).data["claude_code"]` (falls back to the local state)."""
    local = c.state.sessions.setdefault(
        c.session_id,
        {"first_seen": utcnow().isoformat(), "prompts": 0, "tool_calls": 0, "denied": 0,
         "redactions": 0, "events": 0},
    )
    try:
        ss = c.rt.sessions.get(c.session_id)
        data = ss.data.setdefault("claude_code", local)
        if data is not local:
            for k, v in local.items():
                data.setdefault(k, v)
            c.state.sessions[c.session_id] = data
        return data
    except Exception:
        return local


def _bump(c: _Call, **inc: int) -> None:
    data = _session_data(c)
    for k, v in inc.items():
        data[k] = int(data.get(k, 0)) + v
    data["last_seen"] = utcnow().isoformat()
    data["last_event"] = c.event
    data["agent_id"] = c.agent_id


def _label_pre(out: dict[str, Any]) -> str:
    hso = out.get("hookSpecificOutput") or {}
    d = hso.get("permissionDecision")
    if d == "deny":
        reason = str(hso.get("permissionDecisionReason", ""))
        return "pending" if reason.startswith("AEGIS-APPROVAL-REQUIRED") else "deny"
    if d == "allow":
        return "modify" if "updatedInput" in hso else "allow"
    return d or "noop"


# ---------------------------------------------------------------- event handlers
async def _pre_tool_use(c: _Call) -> tuple[dict[str, Any], str]:
    ev = parse_event(c.body, "PreToolUse")
    g = guards.bypass_mode(ev.permission_mode, c.params)
    if g is not None and g.blocks:
        await _audit(c, {"event": "claude_code.bypass_denied", "tool": ev.tool_name})
        _bus(c, "warning", "Claude Code tool call denied: bypassPermissions mode (GOV-06)")
        _bump(c, tool_calls=1, denied=1)
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": g.reason}}, "deny"
    doc = c.snap.doc if c.snap is not None else None
    mapped = mapping.map_tool_input(ev, doc, c.agent)
    hold = selfcheck.hold_seconds(c.snap, c.params, c.deadline_s)
    ctx = _new_ctx(c, hold=hold)
    verdict = await _evaluate(c, ctx, mapped.interaction)

    rehydrated: tuple[Any, int] | None = None
    if (
        verdict.action in ("allow", "log")
        and respond.is_rehydrate(verdict)
        and (doc.defaults.rehydrate_responses if doc is not None else True)
        and mapped.interaction.destination.dest_class == "local"
    ):
        rehydrated = _rehydrate(c.rt, ctx, mapped)

    out = respond.pre_tool_use(
        verdict,
        mapped,
        base_url=c.base_url,
        control_name=_control_name(c, _primary_id(verdict)),
        pass_decision=c.params.pass_decision,
        rehydrated=rehydrated,
    )
    if verdict.action in ("allow", "log", "redact"):
        key = ev.tool_use_id or mapped.interaction.id
        evicted = c.state.pending.put(
            c.session_id,
            key,
            PendingEntry(ctx=ctx, interaction=mapped.interaction, verdict=verdict,
                         t0=time.perf_counter(), routed_mcp=mapped.routed_mcp),
        )
        await _complete_abandoned(c.rt, evicted, "evicted before PostToolUse")
    else:
        status = (verdict.primary.http_status if verdict.primary else None) or 403
        await _complete(c.rt, ctx, mapped.interaction, verdict,
                        Outcome(status_code=status, usage=Usage(requests=0)))
    label = _label_pre(out)
    _bump(c, tool_calls=1, denied=1 if label in ("deny", "pending") else 0,
          redactions=len(verdict.redactions))
    return out, label


def _rehydrate(rt: Any, ctx: RequestContext, mapped: mapping.Mapped) -> tuple[Any, int]:
    """DLP-08: restore this session's placeholders in every string leaf (local tools only)."""
    import copy

    root = copy.deepcopy(mapped.interaction.raw if mapped.interaction.raw is not None else {})
    restored = 0
    for path, keys in mapped.leaves.items():
        if path in mapped.truncated:
            continue
        try:
            text = mapping.get_by_keys(root, keys)
        except (KeyError, IndexError, TypeError):
            continue
        if not isinstance(text, str) or not _PLACEHOLDER.search(text):
            continue
        try:
            new = rt.redactor.rehydrate(ctx, text)
        except Exception:
            log.warning("rehydrate failed path=%s", path)
            continue
        if isinstance(new, str) and new != text:
            restored += len(_PLACEHOLDER.findall(text)) - len(_PLACEHOLDER.findall(new))
            root = mapping.set_by_keys(root, keys, new)
    return root, max(restored, 0)


async def _post_tool_use(c: _Call) -> tuple[dict[str, Any], str]:
    ev = parse_event(c.body, "PostToolUse")
    entry = c.state.pending.pop(c.session_id, ev.tool_use_id)
    parent_id = None
    if entry is not None:
        routed = entry.routed_mcp
        it = entry.interaction
        spend = 0.0
        if not routed and (it.action_type or "").startswith("spend.") and it.amount_usd:
            spend = float(it.amount_usd)
        await _complete(
            c.rt, entry.ctx, it, entry.verdict,
            Outcome(
                status_code=200,
                usage=Usage(requests=0, tool_calls=0 if routed else 1, spend_usd=spend),
                upstream_ms=ev.duration_ms,
            ),
        )
        parent_id = it.id
    doc = c.snap.doc if c.snap is not None else None
    mapped = mapping.map_tool_output(ev, doc, c.agent, parent_id=parent_id)
    if mapped.routed_mcp and not c.params.scan_routed_mcp_results:
        return {}, "skip"
    if not mapped.interaction.segments:
        return {}, "noop"
    ctx = _new_ctx(c)
    verdict = await _evaluate(c, ctx, mapped.interaction)
    out = respond.post_tool_use(
        verdict, mapped, base_url=c.base_url,
        control_name=_control_name(c, _primary_id(verdict)),
    )
    if out.get("decision") == "block":
        label = "block"
    elif out:
        label = "modify"
    else:
        label = "noop"
    if label != "noop":
        _bump(c, redactions=len(verdict.redactions))
    return out, label


async def _post_tool_use_failure(c: _Call) -> tuple[dict[str, Any], str]:
    ev = parse_event(c.body, "PostToolUseFailure")
    entry = c.state.pending.pop(c.session_id, ev.tool_use_id)
    if entry is not None:
        await _complete(
            c.rt, entry.ctx, entry.interaction, entry.verdict,
            Outcome(status_code=500, error="tool failed",
                    usage=Usage(requests=0, tool_calls=0 if entry.routed_mcp else 1),
                    upstream_ms=getattr(ev, "duration_ms", None)),
        )
    return {}, "ok"


async def _user_prompt_submit(c: _Call) -> tuple[dict[str, Any], str]:
    ev = parse_event(c.body, "UserPromptSubmit")
    _bump(c, prompts=1)
    g = await guards.budget_precheck(
        c.rt, c.identity, c.session_id, c.snap, c.params, base_url=c.base_url
    )
    if g is not None and g.blocks:
        await _audit(c, {"event": "claude_code.prompt_blocked", "control_id": g.control_id,
                         **{k: v for k, v in g.data.items() if k != "used"}})
        _bus(c, "warning", f"Claude Code prompt blocked: {g.reason[:140]}")
        _bump(c, denied=1)
        return {
            "decision": "block",
            "reason": g.reason,
            "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "suppressOriginalPrompt": True},
        }, "block"
    doc = c.snap.doc if c.snap is not None else None
    mapped = mapping.map_prompt(ev, doc, c.agent)
    if not mapped.interaction.segments:
        return {}, "noop"
    ctx = _new_ctx(c)
    verdict = await _evaluate(c, ctx, mapped.interaction)
    blocked = verdict.action in ("block", "require_approval")
    status = ((verdict.primary.http_status if verdict.primary else None) or 403) if blocked else 200
    await _complete(c.rt, ctx, mapped.interaction, verdict,
                    Outcome(status_code=status, usage=Usage(requests=0)))
    out = respond.user_prompt_submit(
        verdict, base_url=c.base_url, control_name=_control_name(c, _primary_id(verdict))
    )
    if blocked:
        _bump(c, denied=1)
        return out, "block"
    if out:
        _bump(c, redactions=len(verdict.redactions))
        return out, "note"
    return out, "noop"


async def _session_start(c: _Call) -> tuple[dict[str, Any], str]:
    ev = parse_event(c.body, "SessionStart")
    sc = selfcheck.run(
        c.rt, c.snap, c.params,
        agent_id=c.agent_id, agent=c.agent, permission_mode=ev.permission_mode,
        deadline_s=c.deadline_s, session_id=c.session_id, identity=c.identity,
    )
    data = _session_data(c)
    data.update({
        "started_at": utcnow().isoformat(),
        "source": ev.source,
        "permission_mode": ev.permission_mode,
        "model": ev.model if isinstance(ev.model, str) else None,
        "cwd_hash": mapping.cwd_hash(ev.cwd),
        "governed": True,
    })
    await _audit(c, {
        "event": "claude_code.session_start",
        "source": ev.source,
        "permission_mode": ev.permission_mode,
        "policy_version": c.snap.version if c.snap is not None else None,
        "warnings": sc.warnings,
        "cwd_hash": data.get("cwd_hash"),
    })
    _bus(c, "info", f"Claude Code session connected (governed) · {c.agent_id}")
    for w in sc.warnings[:3]:
        _bus(c, "warning", f"Claude Code self-check: {w}")
    return respond.session_start(sc.banner, sc.system_message), "ok"


async def _config_change(c: _Call) -> tuple[dict[str, Any], str]:
    ev = parse_event(c.body, "ConfigChange")
    g = guards.config_change(ev.source, ev.file_path, c.params)
    enforce = g.blocks and c.params.guard_mode == "enforce"
    await _audit(c, {
        "event": "claude_code.config_change",
        "action": "block" if enforce else ("monitor" if g.blocks else "log"),
        "control_id": g.control_id,
        "reason": g.reason,
        **g.data,
    })
    if g.blocks:
        _bus(c, "warning", f"Claude Code settings change {'blocked' if enforce else 'flagged'} "
                           f"({ev.source or 'unknown'}): {g.reason[:120]}")
    if enforce:
        _bump(c, denied=1)
        return respond.config_change_block(g.reason), "block"
    return {}, "log"


async def _stop(c: _Call) -> tuple[dict[str, Any], str]:
    swept = c.state.pending.sweep_session(c.session_id)
    await _complete_abandoned(c.rt, swept, "no PostToolUse")
    if c.event == "SessionEnd":
        data = dict(_session_data(c))
        await _audit(c, {
            "event": "claude_code.session_end",
            "reason": c.body.get("reason"),
            **{k: data.get(k) for k in ("prompts", "tool_calls", "denied", "redactions")},
        })
        _bus(c, "info", f"Claude Code session ended · {data.get('tool_calls', 0)} tool calls, "
                        f"{data.get('denied', 0)} denied")
    return {}, "ok"


_HANDLERS = {
    "PreToolUse": _pre_tool_use,
    "PostToolUse": _post_tool_use,
    "PostToolUseFailure": _post_tool_use_failure,
    "UserPromptSubmit": _user_prompt_submit,
    "SessionStart": _session_start,
    "ConfigChange": _config_change,
    "Stop": _stop,
    "SessionEnd": _stop,
}


# ---------------------------------------------------------------- entry point
async def handle_hook(
    rt: Any,
    raw: bytes | str | None,
    headers: Mapping[str, str] | None,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """Evaluate one Claude Code hook event and return the hook-output JSON. Never raises."""
    t0 = time.perf_counter()
    hdr = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    hint = (hdr.get("x-aegis-hook-event") or "").strip()
    try:
        body = _parse_body(raw)
    except ValueError as exc:
        log.warning("claude code hook payload rejected event=%s why=%s", hint or "?", exc)
        _metric(rt, hint or "unknown", "malformed")
        return respond.fail_closed_output(hint, "malformed hook payload") if hint in BLOCKING_EVENTS else {}
    event = str(body.get("hook_event_name") or hint or "unknown")
    if rt is None:
        _metric(None, event, "no_runtime")
        return respond.fail_closed_output(event, "gateway runtime not started")

    state = state_for(rt)
    state.events[event] += 1
    c: _Call | None = None
    label = "error"
    try:
        expired = state.pending.sweep_expired()
        if expired:
            await _complete_abandoned(rt, expired, "PostToolUse never arrived (expired)")
        snap = _snapshot(rt)
        identity, agent, agent_id = await _resolve(rt, hdr, body)
        session_id = hdr.get("x-aegis-session") or str(body.get("session_id") or "") or "default"
        c = _Call(
            rt=rt, event=event, body=body, hdr=hdr, base_url=base_url.rstrip("/"), state=state,
            snap=snap, params=guards.load_params(snap), identity=identity, agent=agent,
            agent_id=agent_id, session_id=session_id,
            deadline_s=_float(hdr.get("x-aegis-hook-deadline"), DEFAULT_DEADLINE_S),
            safe_headers={k: v for k, v in hdr.items() if k not in _SECRET_HEADERS},
        )
        if snap is None and event in BLOCKING_EVENTS:
            out, label = respond.fail_closed_output(event, "policy unavailable"), "error"
        else:
            fn = _HANDLERS.get(event)
            if fn is None:
                out, label = {}, "ignored"
            else:
                out, label = await fn(c)
        _bump(c, events=1)
    except Exception:
        log.exception("claude code hook failed event=%s", event)
        allow_on_error = c is not None and c.params.internal_error == "allow"
        out = {} if allow_on_error else respond.fail_closed_output(event, "decision unavailable")
        label = "error"
    elapsed = time.perf_counter() - t0
    state.rtt_ms.append(round(elapsed * 1000, 3))
    state.last_event = {"event": event, "result": label, "ts": utcnow().isoformat(),
                        "ms": round(elapsed * 1000, 2)}
    _metric(rt, event, label)
    try:
        rt.metrics.observe_overhead("hook", max(0.0, elapsed - (c.pipeline_s if c else 0.0)))
    except Exception:
        pass
    return out


def _metric(rt: Any, event: str, result: str) -> None:
    if rt is None:
        return
    try:
        rt.metrics.inc(METRIC, {"event": event, "result": result})
    except Exception:
        pass


def hook_status(rt: Any) -> dict[str, Any]:
    """Data for `GET /v1/hooks/claude-code/status` (gap G7)."""
    if rt is None:
        return {"runtime": False}
    return {"runtime": True, **state_for(rt).status()}


__all__ = ["DEFAULT_AGENT", "HookState", "handle_hook", "hook_status", "state_for"]
