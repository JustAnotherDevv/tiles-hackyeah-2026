"""RES-01 - Cascading-failure breaker (ASI08). Stateful, priority 12.

Stops one fault from being amplified through an agent chain. Three mechanisms:

1. **Agent quarantine.** ``on_complete`` counts enforce *blocks* of an agent by OTHER controls
   (``ignore_controls``: EXE-04/BUD-* already are breakers) per ``scope`` key (session, or the
   whole agent). ``block_threshold`` blocks within ``window_s`` -> quarantine for
   ``quarantine_ttl_s``: every further side-effecting call (``quarantine_surfaces``) of that
   agent gets ``cfg.action`` (balanced: ``require_approval``, so a human can release it).
2. **Downstream circuit.** Allowed calls to an MCP server / egress host that come back failing
   (HTTP >= ``failure_status_min``, or an upstream error) are counted per target across ALL
   agents; ``tool_failure_threshold`` failures within ``tool_window_s`` open the circuit for
   ``tool_cooldown_s`` -> ``tool_action`` (block, 503 ``circuit_open`` + Retry-After), then a
   single half-open probe; success closes it. Built-in agent tools (Bash, Read, ...) are not
   circuit targets (normal command failures are not an outage).
3. **Cascade taint.** An inbound result (``a2a.result``/``tool.output``/``mcp.result``) whose
   producer (``peer_keys`` label/meta, ``x-aegis-peer-agent`` header, ``resource: agent:<id>``,
   A2A ``tool_name: a2a.<peer>``) is quarantined - agent-wide (``scope: agent``, or quarantined
   in ``agent_wide_after_sessions`` sessions), in the consumer's session, or in the
   ``peer_session`` the result names - is dropped (``quarantined_output_action``: block) and the consuming agent+session
   is tainted (its session; ``taint_scope: agent`` = every session); outputs of a tainted agent
   taint their consumers transitively (``chain``). Tainted callers' side-effecting calls get
   ``taint_action`` (balanced: require_approval) with the propagation chain in the reason.

Self-tests and dry runs never mutate state. Owner: ASI-FAILCLOSED.
"""

from __future__ import annotations

import logging
import time
from fnmatch import fnmatchcase
from typing import Any, ClassVar, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aegis.controls.resilience._state import STATE, CascadeState
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import (
    AppliesTo,
    ApprovalDraft,
    Decision,
    Finding,
    Interaction,
    Outcome,
    RequestContext,
    Verdict,
)

log = logging.getLogger(__name__)

ActionName = Literal["allow", "log", "redact", "require_approval", "block"]
OUT_SURFACES = {"tool.input", "mcp.call", "mcp.init", "egress.request", "a2a.message"}
IN_SURFACES = {"a2a.result", "tool.output", "mcp.result"}
ALLOWED = {"allow", "log", "redact"}


class Res01Params(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scope: Literal["session", "agent"] = "session"
    window_s: float = Field(300.0, gt=0)
    block_threshold: int = Field(3, ge=1)
    quarantine_ttl_s: float = Field(900.0, gt=0)
    quarantine_surfaces: list[str] = Field(
        default_factory=lambda: [
            "tool.input",
            "mcp.call",
            "mcp.init",
            "egress.request",
            "a2a.message",
        ]
    )
    ignore_controls: list[str] = Field(
        default_factory=lambda: ["EXE-04", "BUD-01", "BUD-02", "RES-01"]
    )
    circuit_targets: list[str] = Field(default_factory=lambda: ["mcp:*", "host:*"])
    tool_failure_threshold: int = Field(5, ge=1)
    tool_window_s: float = Field(60.0, gt=0)
    tool_cooldown_s: float = Field(60.0, gt=0)
    tool_action: ActionName = "block"
    failure_status_min: int = 500
    # outputs of an agent quarantined in N distinct sessions are dropped in EVERY session
    agent_wide_after_sessions: int = Field(3, ge=1)
    taint_ttl_s: float = Field(900.0, gt=0)
    taint_scope: Literal["session", "agent"] = "session"  # what gets gated after consuming
    taint_action: ActionName = "require_approval"
    quarantined_output_action: ActionName = "block"
    peer_keys: list[str] = Field(
        default_factory=lambda: ["peer_agent", "source_agent", "from_agent"]
    )
    max_chain: int = Field(6, ge=1)


def _params(cfg: Any) -> Res01Params:
    try:
        return Res01Params.model_validate(getattr(cfg, "params", None) or {})
    except ValidationError:
        log.warning("invalid params control=RES-01; using defaults")
        return Res01Params()


def _who(ctx: RequestContext) -> str:
    ident = ctx.identity
    return ident.agent_id or (f"member:{ident.member_id}" if ident.member_id else "anonymous")


def scope_key(p: Res01Params, ctx: RequestContext) -> str:
    who = _who(ctx)
    return f"agent:{who}" if p.scope == "agent" else f"agent:{who}|session:{ctx.session_id}"


def taint_keys(ctx: RequestContext, p: Res01Params) -> list[str]:
    """Keys whose taint GATES this caller's actions (session by default)."""
    keys = [f"session:{ctx.session_id}"]
    if p.taint_scope == "agent":
        keys.append(f"agent:{_who(ctx)}")
    return keys


def circuit_key(i: Interaction) -> str | None:
    """``mcp:<server>`` for MCP traffic, ``host:<h>`` for egress; None for built-in tools."""
    if i.mcp_server:
        return f"mcp:{i.mcp_server}"
    if i.surface in ("mcp.call", "mcp.init", "mcp.result") and i.tool_name and "." in i.tool_name:
        return f"mcp:{i.tool_name.split('.', 1)[0]}"
    if i.surface in ("egress.request", "egress.response") and i.url:
        host = urlsplit(i.url).hostname
        return f"host:{host}" if host else None
    return None


def peer_of(i: Interaction, p: Res01Params) -> str | None:
    for k in p.peer_keys:
        v = i.labels.get(k) or i.meta.get(k)
        if v:
            return str(v)
    h = i.headers.get("x-aegis-peer-agent")
    if h:
        return h
    if i.resource and i.resource.startswith("agent:"):
        return i.resource.split(":", 1)[1] or None
    if i.surface.startswith("a2a.") and i.tool_name and i.tool_name.startswith("a2a."):
        return i.tool_name.split(".", 1)[1] or None  # A2A-01 peer naming: a2a.<peer>
    return None


def short(agent: str) -> str:
    """``research-agent@research`` -> ``research-agent`` (A2A peers are named without team)."""
    return agent.split("@", 1)[0]


def _skip_state(ctx: RequestContext) -> bool:
    return bool(ctx.dry_run) or ctx.source == "selftest"


class CascadeBreaker(BaseControl):
    id: ClassVar[str] = "RES-01"
    family: ClassVar[str] = "RES"
    name: ClassVar[str] = "Cascading-failure breaker (quarantine + circuit + taint)"
    kind: ClassVar[str] = "stateful"  # type: ignore[assignment]
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces=OUT_SURFACES | IN_SURFACES)
    owasp: ClassVar[list[str]] = ["ASI08", "ASI10", "ASI07"]
    priority: ClassVar[int] = 12

    def __init__(self, state: CascadeState | None = None, clock: Any = None) -> None:
        self.state = state or STATE
        self.clock = clock or time.monotonic

    # ------------------------------------------------------------ helpers
    def _finding(self, detector: str, cfg: Any, excerpt: str, **meta: Any) -> Finding:
        return Finding(
            control_id=self.id,
            detector=detector,
            category="cascade",
            severity=getattr(cfg, "severity", None) or "high",
            excerpt=excerpt,
            meta=meta,
        )

    def _decision(
        self,
        cfg: Any,
        action: str,
        reason: str,
        finding: Finding,
        *,
        i: Interaction,
        ctx: RequestContext,
        meta: dict[str, Any],
        signal: str,
        **kw: Any,
    ) -> Decision:
        approval = None
        if action == "require_approval":
            at = i.action_type or (
                f"tool:{i.tool_name}" if i.tool_name else f"{i.kind}.{i.surface}"
            )
            approval = ApprovalDraft(
                kind="action",
                action_type=at,
                title=f"{_who(ctx)}: {i.tool_name or i.surface} while {signal.replace('_', ' ')}",
                summary=reason,
                resource=i.resource,
                labels={"signals": signal},
            )
        return Decision(
            action=action,  # type: ignore[arg-type]
            control_id=self.id,
            reason=reason,
            severity=getattr(cfg, "severity", None) or "high",
            findings=[finding],
            approval=approval,
            owasp=list(getattr(cfg, "owasp", None) or self.owasp),
            meta={"cascade": signal, **meta},
            **kw,
        )

    # ------------------------------------------------------------ evaluate
    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        if ctx.source == "selftest":
            return None
        p = _params(cfg)
        now = self.clock()
        i = interaction
        if i.surface in IN_SURFACES or i.direction == "in":
            return self._inbound(ctx, i, cfg, p, now)

        # 1. downstream circuit (shared by every agent)
        ck = circuit_key(i)
        if ck and any(fnmatchcase(ck, g) for g in p.circuit_targets):
            state, c = (
                self.state.circuit_state(ck, now)
                if not ctx.dry_run
                else (self._peek_circuit(ck, now))
            )
            if state == "open" and c is not None:
                retry = max(1, int(c.open_until - now + 0.999))
                reason = (
                    f"circuit open for {ck}: it failed {p.tool_failure_threshold}x within "
                    f"{p.tool_window_s:.0f}s (last: {c.last_error or 'upstream error'}); "
                    f"calls are paused for {retry}s so the failure does not cascade "
                    "through dependent agents"
                )
                return self._decision(
                    cfg,
                    p.tool_action,
                    reason,
                    self._finding("res.cascade.circuit_open", cfg, ck, target=ck),
                    i=i,
                    ctx=ctx,
                    meta={"target": ck, "retry_after_s": retry},
                    signal="circuit_open",
                    http_status=503,
                    error_type="circuit_open",
                    retry_after_s=retry,
                )

        if i.surface not in p.quarantine_surfaces:
            return None
        # 2. this agent is quarantined
        q = self.state.quarantine(scope_key(p, ctx), now)
        if q is None and p.scope == "session":
            q = self.state.quarantine(f"agent:{_who(ctx)}", now)  # operator / agent-wide entry
        if q is not None:
            left = int(q.until - now)
            reason = (
                f"agent {q.agent} is quarantined after {q.summary} within "
                f"{p.window_s:.0f}s; further {i.surface} calls need a human "
                f"(cascade breaker, {left}s left). Last: {q.reasons[-1] if q.reasons else '-'}"
            )
            return self._decision(
                cfg,
                cfg.action,
                reason,
                self._finding("res.cascade.quarantine", cfg, q.summary, controls=q.controls),
                i=i,
                ctx=ctx,
                meta={"quarantine": {"controls": q.controls, "expires_in_s": left}},
                signal="cascade_quarantine",
            )
        # 3. this agent consumed output of a quarantined agent
        t = self.state.taint_of(taint_keys(ctx, p), now)
        if t is not None:
            path = " -> ".join([*t.chain, _who(ctx)])
            reason = (
                f"{_who(ctx)} consumed output of quarantined agent {t.root} "
                f"(propagation {path}); {i.surface} needs a human before the failure "
                "spreads further"
            )
            return self._decision(
                cfg,
                p.taint_action,
                reason,
                self._finding("res.cascade.tainted_action", cfg, path, chain=t.chain),
                i=i,
                ctx=ctx,
                meta={"taint": {"root": t.root, "chain": t.chain}},
                signal="cascade_tainted",
            )
        return None

    def _peek_circuit(self, key: str, now: float) -> tuple[str, Any]:
        c = self.state.circuits.get(key)
        if c is None or not c.open_until:
            return "closed", c
        return ("open" if now < c.open_until else "half_open"), c

    def _inbound(
        self, ctx: RequestContext, i: Interaction, cfg: Any, p: Res01Params, now: float
    ) -> Decision | None:
        peer = peer_of(i, p)
        if not peer or peer == _who(ctx):
            return None
        # The producer's quarantine applies when it is agent-wide (agent scope or escalated), or
        # scoped to the consumer's own session (multi-agent in one session) or to the session
        # the result names (``peer_session``). "via:<agent>" = that agent consumed poisoned
        # output somewhere (propagation index only, never gates).
        peer_session = i.labels.get("peer_session") or i.meta.get("peer_session")
        sessions = tuple(x for x in (ctx.session_id, peer_session) if x)
        q = self.state.agent_quarantine(
            peer, now, sessions=sessions, min_sessions=p.agent_wide_after_sessions
        )
        look = [f"via:{peer}"] + ([f"session:{peer_session}"] if peer_session else [])
        t = None if q is not None else self.state.taint_of(look, now)
        if q is None and t is None:
            return None
        root = peer if q is not None else t.root  # type: ignore[union-attr]
        chain = ([peer] if q is not None else [*t.chain, peer])[-p.max_chain :]  # type: ignore[union-attr]
        me = _who(ctx)
        if not _skip_state(ctx):
            self.state.mark_taint(
                [*taint_keys(ctx, p), f"via:{me}", f"via:{short(me)}"],
                root=root,
                chain=chain,
                until=now + p.taint_ttl_s,
                reason=f"consumed {i.surface} from {peer}",
            )
        if q is not None:
            reason = (
                f"{i.surface} produced by quarantined agent {peer} ({q.summary}) was "
                f"dropped before reaching {me}; {me} is now tainted (cascade breaker)"
            )
            return self._decision(
                cfg,
                p.quarantined_output_action,
                reason,
                self._finding("res.cascade.quarantined_output", cfg, f"{peer} -> {me}", peer=peer),
                i=i,
                ctx=ctx,
                meta={"peer": peer, "chain": chain},
                signal="cascade_quarantined_output",
            )
        path = " -> ".join([*chain, me])
        return self._decision(
            cfg,
            "log",
            f"{i.surface} from {peer}, which consumed output of quarantined {root}; "
            f"{me} is now tainted ({path})",
            self._finding("res.cascade.taint_propagation", cfg, path, chain=chain),
            i=i,
            ctx=ctx,
            meta={"peer": peer, "chain": chain},
            signal="cascade_tainted",
        )

    # ------------------------------------------------------------ on_complete
    async def on_complete(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        verdict: Verdict,
        outcome: Outcome,
        cfg: ControlConfig,
    ) -> None:
        if _skip_state(ctx) or getattr(verdict, "dry_run", False):
            return
        p = _params(cfg)
        now = self.clock()
        i = interaction
        action = getattr(verdict, "action", "allow")
        primary = getattr(verdict, "primary", None)
        if action == "block" and primary is not None:
            cid = primary.control_id
            if cid not in p.ignore_controls and getattr(primary, "mode", "enforce") == "enforce":
                q = self.state.record_block(
                    scope_key(p, ctx),
                    agent=_who(ctx),
                    session=ctx.session_id,
                    control_id=cid,
                    reason=(primary.reason or cid)[:160],
                    now=now,
                    window_s=p.window_s,
                    threshold=p.block_threshold,
                    ttl_s=p.quarantine_ttl_s,
                )
                if q is not None:
                    log.warning(
                        "RES-01 quarantine agent=%s session=%s after %s",
                        q.agent,
                        q.session,
                        q.summary,
                    )
            return
        ck = circuit_key(i)
        if (
            action not in ALLOWED
            or not ck
            or not any(fnmatchcase(ck, g) for g in p.circuit_targets)
        ):
            return
        status = int(outcome.status_code or 0)
        if status in (499,):  # client gone / parked guard expired: not the target's fault
            return
        failed = status >= p.failure_status_min or (status < 400 and bool(outcome.error))
        if not failed and status >= 400:
            return  # a 4xx is the caller's problem, not a downstream outage
        c = self.state.record_result(
            ck,
            ok=not failed,
            now=now,
            window_s=p.tool_window_s,
            threshold=p.tool_failure_threshold,
            cooldown_s=p.tool_cooldown_s,
            error=outcome.error or (f"HTTP {status}" if failed else None),
        )
        if c is not None:
            log.warning("RES-01 circuit open target=%s for %.0fs", ck, p.tool_cooldown_s)


CONTROLS = [CascadeBreaker()]
