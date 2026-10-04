"""ROG-01 - Rogue-agent behavioural anomaly detector (OWASP ASI10). Stateful, priority 14.

Containment already exists (kill switch, BUD caps, EXE-04 loop ladder, GOV-06 anti-tamper,
RES-01 cascade quarantine). ROG-01 adds *detection*: it learns a per-agent behavioural baseline
from the calls that actually executed (``on_complete``) and scores every outbound call against
it with explainable, additive signals:

==========================  ======  ====================================================
signal                      weight  fires when
==========================  ======  ====================================================
self_modify                 0.60    write/edit/shell/HTTP aimed at the agent's own controls:
                                    Aegis policy/profiles/snippets/org seed, hook settings,
                                    GOV-06 protected paths (read from the live policy), gateway
                                    env vars, the Aegis control-plane API (policy, kill switch,
                                    org agents, approval votes)
spawn_burst                 0.55    >= ``spawn_burst_medium`` sub-agent spawns / A2A delegations
                                    in ``spawn_window_s`` (Task/Agent tools, *.spawn_agent,
                                    *.create_agent, ``claude -p`` & co., POST /api/org/agents)
spawn_burst_high            0.90    >= ``spawn_burst_high`` in the same window
spawn_session_cap           0.55    > ``max_spawns_per_session`` in one session
delegation_depth            0.55    delegation chain deeper than ``max_delegation_depth``
data_escalation             0.45    session read CONFIDENTIAL+/PII data, now sends outward
new_high_risk_tool          0.35    first use of a spend/write/send/exec/config tool (mature)
new_destination             0.30    first call to an external host / MCP server / peer (mature)
call_rate_spike             0.35    calls in ``rate_window_s`` > ``rate_factor`` x baseline (mature);
                                    x1.5 when severe (>= 2x the factor and 2x the floor)
spend_spike                 0.50    amount > ``spend_factor`` x mean and above the max (mature)
off_hours                   0.10    hour of day never seen in a large baseline (mature)
repeat_flags                0.15    per earlier flag in this session (max 3), persistence
                                    (not added to pure spawn-burst flags: those escalate by count)
==========================  ======  ====================================================

"mature" = the baseline has >= ``min_events`` executed calls over >= ``min_sessions`` sessions,
so a brand-new agent is never flagged for novelty, only for stateless signals.

Score (sum, capped at 1.0) >= ``medium`` -> ``medium_action`` (require_approval, the approval
card lists every signal); >= ``high`` -> ``high_action`` (block) answered like the kill switch
(429 ``killed``, Retry-After 3600, x-should-retry false - Addendum A-07) **and** auto-quarantine:
session scope = a runtime session kill in the budgets ledger (EXE-04 then stops every further call
with 429 killed) persisted into ``budgets.kill_switch.sessions`` so the dashboard kill-switch panel
shows it and can release it; agent scope = ``kill_switch.agents``. Without a ledger (unit tests)
ROG-01 enforces its own quarantine store.

Self-tests evaluate stateless signals only (empty state, A-09); dry runs read state but never
write it. Owner: ASI-ROGUE.
"""

from __future__ import annotations

import logging
import re
import time
from fnmatch import fnmatchcase
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
from aegis.rogue.store import STORE, AgentBaseline, BaselineStore, SessionState

log = logging.getLogger(__name__)

ActionName = Literal["allow", "log", "redact", "require_approval", "block"]
OUT_SURFACES = {"tool.input", "mcp.call", "mcp.init", "egress.request", "a2a.message"}
IN_SURFACES = {"tool.output", "mcp.result", "egress.response", "a2a.result"}
FILE_WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit", "*.write_file", "*.edit_file",
                    "*.create_file", "*.delete_file", "*.move_file", "*.write", "*.edit")
SHELL_TOOLS = ("Bash", "*.run_command", "*.exec_command", "*.shell", "shell.*")
COMMAND_ARGS = ("command", "cmd", "script", "commands")
CLASS_RANK = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "RESTRICTED": 3, "SECRET": 4}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

DEFAULT_WEIGHTS: dict[str, float] = {
    "self_modify": 0.60,
    "spawn_burst": 0.55,
    "spawn_burst_high": 0.90,
    "spawn_session_cap": 0.55,
    "delegation_depth": 0.55,
    "data_escalation": 0.45,
    "new_high_risk_tool": 0.35,
    "new_destination": 0.30,
    "call_rate_spike": 0.35,
    "spend_spike": 0.50,
    "off_hours": 0.10,
    "repeat_flags": 0.15,
}
SPAWN_SIGNALS = {"spawn_burst", "spawn_burst_high", "spawn_session_cap"}
SIGNAL_LABEL = {
    "self_modify": "self-modification attempt",
    "spawn_burst": "sub-agent spawn burst",
    "spawn_burst_high": "sub-agent spawn storm",
    "spawn_session_cap": "too many sub-agents in one session",
    "delegation_depth": "delegation chain too deep",
    "data_escalation": "data-class escalation (sensitive read, then outbound send)",
    "new_high_risk_tool": "first-time high-risk tool",
    "new_destination": "new external destination",
    "call_rate_spike": "call-rate spike vs baseline",
    "spend_spike": "spend spike vs baseline",
    "off_hours": "activity outside the agent's usual hours",
    "repeat_flags": "repeated anomalies in this session",
}


class Rog01Params(BaseModel):
    model_config = ConfigDict(extra="ignore")

    medium: float = Field(0.5, gt=0)
    high: float = Field(0.85, gt=0)
    medium_action: ActionName = "require_approval"
    high_action: ActionName = "block"
    weights: dict[str, float] = Field(default_factory=dict)  # overrides DEFAULT_WEIGHTS
    exempt_agents: list[str] = Field(default_factory=list)
    # baseline maturity (novelty / spike signals only)
    min_events: int = Field(20, ge=1)
    min_sessions: int = Field(2, ge=1)
    min_age_s: float = Field(0.0, ge=0)
    # call rate
    rate_window_s: float = Field(60.0, gt=0)
    rate_factor: float = Field(5.0, gt=1)
    rate_floor: int = Field(20, ge=1)
    rate_min_minutes: int = Field(3, ge=1)
    # spend
    spend_factor: float = Field(5.0, gt=1)
    spend_floor_usd: float = Field(25.0, ge=0)
    spend_min_samples: int = Field(3, ge=1)
    # off hours
    off_hours: bool = True
    off_hours_min_events: int = Field(200, ge=1)
    # novelty
    high_risk_capabilities: list[str] = Field(
        default_factory=lambda: ["spend", "data_write", "external_send", "code_exec", "config"]
    )
    high_risk_tools: list[str] = Field(
        default_factory=lambda: ["*.delete_*", "*.drop_*", "*.export_*", "*.transfer*",
                                 "*.wire_*", "*.grant_*", "*.revoke_*", "*.create_user*",
                                 "*.set_permission*", "*.purchase*", "*.send_*"]
    )
    # data-class escalation
    sensitive_classes: list[str] = Field(
        default_factory=lambda: ["CONFIDENTIAL", "RESTRICTED", "SECRET"]
    )
    sensitive_read_tools: list[str] = Field(
        default_factory=lambda: ["*.export_*", "*.get_customer*", "*.list_customers*",
                                 "*.read_customer*", "*.get_client*", "*.read_pii*"]
    )
    scan_results: bool = True
    scan_max_chars: int = Field(16000, ge=0)
    outbound_capabilities: list[str] = Field(default_factory=lambda: ["external_send"])
    # self-modification
    self_modify_paths: list[str] = Field(
        default_factory=lambda: [
            "**/config/policy*.yaml", "**/config/profiles/**", "**/config/snippets/**",
            "**/config/org*.yaml", "**/config/feeds/**", "**/.claude/settings*.json",
            "**/.claude/hooks/**", "**/scripts/aegis-hook*", "**/demo/claude/settings*.json",
            "**/demo/claude/mcp.json", "**/.mcp.json", "**/.aegis/**", "**/.agent_key",
        ]
    )
    include_gov06_paths: bool = True
    self_modify_env: str = (
        r"(?i)(?:\b(?:export|unset|setenv)\s+|\benv\s+-u\s+|^|[\s;&|])"
        r"(?:ANTHROPIC_BASE_URL|ANTHROPIC_CUSTOM_HEADERS|AEGIS_[A-Z0-9_]+|HTTPS?_PROXY|NO_PROXY)\s*="
        r"|\b(?:unset|env\s+-u)\s+(?:ANTHROPIC_BASE_URL|AEGIS_[A-Z0-9_]+)\b"
        r"|--dangerously-skip-permissions|disableAllHooks"
    )
    control_plane_paths: list[str] = Field(
        default_factory=lambda: [
            r"/api/policy(?:/|$)", r"/api/(?:budgets/)?killswitch", r"/api/org/agents",
            r"/api/controls/", r"/api/approvals/[^/]+/(?:vote|approve|decide)",
        ]
    )
    control_plane_read_ok: bool = True  # GET on the control plane is not self-modification
    # spawning / delegation
    spawn_tools: list[str] = Field(
        default_factory=lambda: ["Task", "Agent", "*.spawn_agent*", "*.spawn_subagent*",
                                 "*.create_agent*", "*.delegate*", "*.run_agent*",
                                 "*.start_agent*", "*.launch_agent*", "a2a.*"]
    )
    spawn_command: str = (
        r"(?i)(?:^|[;&|(\s])(?:claude\s+(?:-p|--print)\b|codex\s+(?:exec|e)\b|gemini\s+-p\b"
        r"|aider\s+--message\b|goose\s+run\b|npx\s+@anthropic-ai/claude-code\b)"
    )
    spawn_urls: list[str] = Field(default_factory=lambda: [r"/api/org/agents(?:/|$)"])
    spawn_window_s: float = Field(60.0, gt=0)
    spawn_burst_medium: int = Field(8, ge=1)
    spawn_burst_high: int = Field(16, ge=1)
    max_spawns_per_session: int = Field(50, ge=1)
    max_delegation_depth: int = Field(3, ge=1)
    depth_keys: list[str] = Field(
        default_factory=lambda: ["delegation_depth", "x-aegis-delegation-depth", "a2a_depth"]
    )
    # persistence of flags + quarantine
    flag_window_s: float = Field(900.0, gt=0)
    quarantine: bool = True
    quarantine_scope: Literal["session", "agent"] = "session"
    quarantine_ttl_s: float = Field(900.0, gt=0)
    persist_quarantine: bool = True


_RX_CACHE: dict[str, re.Pattern[str] | None] = {}


def _rx(pattern: str) -> re.Pattern[str] | None:
    if pattern not in _RX_CACHE:
        try:
            _RX_CACHE[pattern] = re.compile(pattern) if pattern else None
        except re.error:
            log.warning("ROG-01: invalid regex ignored: %r", pattern)
            _RX_CACHE[pattern] = None
    return _RX_CACHE[pattern]


# Cheap PII shapes in tool results (data-class escalation); harmless, bounded scan.
_PII_RX = re.compile(
    r"\b\d{11}\b"  # PESEL-like
    r"|\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}\b"  # IBAN
    r"|\b(?:\d{4}[ -]?){3}\d{4}\b"  # card PAN
    r"|\b\d{3}-\d{2}-\d{4}\b"  # SSN
)

_PARAMS_CACHE: dict[int, tuple[Any, Rog01Params]] = {}


def _params(cfg: Any) -> Rog01Params:
    raw = getattr(cfg, "params", None) or {}
    hit = _PARAMS_CACHE.get(id(cfg))
    if hit is not None and hit[0] is raw:
        return hit[1]
    try:
        p = Rog01Params.model_validate(raw)
    except ValidationError:
        log.warning("invalid params control=ROG-01; using defaults")
        p = Rog01Params()
    if len(_PARAMS_CACHE) > 64:
        _PARAMS_CACHE.clear()
    _PARAMS_CACHE[id(cfg)] = (raw, p)
    return p


def _glob(patterns: list[str] | tuple[str, ...], value: str | None) -> str | None:
    if not value:
        return None
    for pat in patterns:
        if fnmatchcase(value, pat):
            return pat
    return None


def who(ctx: RequestContext) -> tuple[str, bool]:
    ident = ctx.identity
    if ident.agent_id:
        return ident.agent_id, True
    return f"member:{ident.member_id or 'anonymous'}", False


def session_key(agent: str, ctx: RequestContext) -> str:
    return f"{agent}|{ctx.session_id}"


def _url(i: Interaction) -> str | None:
    try:
        from aegis.actions.argpath import url_of

        return url_of(i)
    except Exception:
        return i.url


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        from aegis.actions.net import host_of

        h = host_of(url)
    except Exception:
        h = None
    if h is None:
        m = re.match(r"^[a-z][a-z0-9+.-]*://([^/:?#]+)", url, re.I)
        h = m.group(1) if m else None
    return h.lower() if h else None


def _method(i: Interaction) -> str:
    if i.http_method:
        return i.http_method.upper()
    m = (i.tool_args or {}).get("method")
    return m.upper() if isinstance(m, str) else ("GET" if (i.tool_name or "") == "WebFetch" else "")


def destination_key(i: Interaction) -> str | None:
    """Stable key of where the call goes: URL host, MCP server or A2A peer (None = local)."""
    host = _host(_url(i))
    if host:
        return None if host in LOCAL_HOSTS else host
    if i.mcp_server:
        return f"mcp:{i.mcp_server}"
    tool = i.tool_name or ""
    if i.surface in ("mcp.call", "mcp.init") and "." in tool:
        return f"mcp:{tool.split('.', 1)[0]}"
    if i.surface == "a2a.message":
        peer = (i.meta or {}).get("peer_agent") or i.labels.get("peer_agent") or i.destination.name
        return f"agent:{peer}"
    d = i.destination
    if d.dest_class != "local" and d.name not in ("unknown", "aegis", "local", ""):
        return d.name
    return None


def tool_key(i: Interaction) -> str:
    if i.tool_name:
        return i.tool_name
    if i.surface == "egress.request":
        return f"http.{(_method(i) or 'get').lower()}"
    return i.surface


def capability(ctx: RequestContext, i: Interaction) -> str:
    cap = i.labels.get("capability")
    if cap:
        return cap
    try:
        from aegis.actions.classify import ensure_classified

        rules = list(getattr(getattr(ctx.policy, "doc", None), "actions", None) or [])
        ensure_classified(i, rules)
    except Exception:
        log.debug("ROG-01 classify failed", exc_info=True)
    return i.labels.get("capability") or "other"


def _command(i: Interaction) -> str | None:
    args = i.tool_args or {}
    for k in COMMAND_ARGS:
        v = args.get(k)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, list) and v and all(isinstance(x, str) for x in v):
            return " ".join(v)
    return None


def _target_path(args: dict[str, Any]) -> str:
    for k in ("file_path", "notebook_path", "path", "target", "destination"):
        v = args.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


_GOV06_CACHE: dict[str, list[str]] = {}


def gov06_paths(ctx: RequestContext) -> list[str]:
    """GOV-06 ``protected_paths`` from the evaluated policy (read-only coordination)."""
    snap = ctx.policy
    if snap is None:
        return []
    key = f"{getattr(snap, 'version', '')}:{getattr(snap, 'sha256', '')}"
    if key in _GOV06_CACHE:
        return _GOV06_CACHE[key]
    out: list[str] = []
    try:
        for c in getattr(snap.doc, "controls", None) or []:
            if getattr(c, "id", None) == "GOV-06":
                out = [str(x) for x in (c.params or {}).get("protected_paths") or []]
                break
    except Exception:
        out = []
    if len(_GOV06_CACHE) > 16:
        _GOV06_CACHE.clear()
    _GOV06_CACHE[key] = out
    return out


def self_modify(ctx: RequestContext, i: Interaction, p: Rog01Params) -> str | None:
    """Explanation when the call targets the agent's own controls, else None."""
    from aegis.integrations.claude_code.gov06 import bash_touches_protected, path_protected

    tool = i.tool_name or ""
    args = i.tool_args or {}
    patterns = list(p.self_modify_paths)
    if p.include_gov06_paths:
        patterns += [x for x in gov06_paths(ctx) if x not in patterns]
    if _glob(FILE_WRITE_TOOLS, tool):
        path = _target_path(args)
        hit = path_protected(path, patterns)
        if hit:
            return f"{tool} on {path} (protected: {hit})"
    cmd = _command(i) if (_glob(SHELL_TOOLS, tool) or "command" in args) else None
    if cmd:
        hit = bash_touches_protected(cmd, patterns)
        if hit:
            return f"shell command modifies a protected file ({hit})"
        rx = _rx(p.self_modify_env)
        m = rx.search(cmd) if rx else None
        if m:
            return f"shell command tampers with gateway/oversight settings ({m.group(0).strip()[:60]})"
    url = _url(i)
    if url:
        path = re.sub(r"^[a-z][a-z0-9+.-]*://[^/]*", "", url, flags=re.I) or "/"
        method = _method(i)
        for pat in p.control_plane_paths:
            rx = _rx(pat)
            if rx and rx.search(path):
                is_vote = "approvals/" in path
                if p.control_plane_read_ok and method in ("", "GET", "HEAD") and not is_vote:
                    return None
                return f"{method or 'call'} to the Aegis control plane {path[:80]}"
    return None


def spawn_kind(i: Interaction, p: Rog01Params) -> str | None:
    if i.surface == "a2a.message":
        return "A2A delegation"
    tool = i.tool_name or ""
    hit = _glob(p.spawn_tools, tool)
    if hit:
        return f"sub-agent tool {tool}"
    cmd = _command(i) if (_glob(SHELL_TOOLS, tool) or "command" in (i.tool_args or {})) else None
    if cmd:
        rx = _rx(p.spawn_command)
        m = rx.search(cmd) if rx else None
        if m:
            return f"shell launches an agent ({m.group(0).strip()[:40]})"
    url = _url(i)
    if url and _method(i) in ("POST", "PUT"):
        for pat in p.spawn_urls:
            rx = _rx(pat)
            if rx and rx.search(url):
                return "creates a new agent identity"
    return None


def delegation_depth(i: Interaction, ctx: RequestContext, p: Rog01Params) -> int | None:
    for k in p.depth_keys:
        for src in (i.meta or {}, i.labels or {}, i.headers or {}, ctx.headers or {}):
            v = src.get(k) if isinstance(src, dict) else None
            if v is None:
                continue
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    return None


def _is_outbound(i: Interaction, cap: str, p: Rog01Params) -> bool:
    if cap in p.outbound_capabilities:
        return True
    if i.surface == "a2a.message":
        return True
    if i.surface == "egress.request" and _method(i) in ("POST", "PUT", "PATCH"):
        return True
    return i.destination.dest_class == "third_party" and cap != "data_read"


class RogueBehaviourControl(BaseControl):
    id: ClassVar[str] = "ROG-01"
    family: ClassVar[str] = "ROG"
    name: ClassVar[str] = "Rogue-agent behavioural anomaly detector (baseline + quarantine)"
    kind: ClassVar[Any] = "stateful"
    priority: ClassVar[int] = 14
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces=OUT_SURFACES | IN_SURFACES)
    owasp: ClassVar[list[str]] = ["ASI10", "ASI08", "LLM06:2026"]

    def __init__(self, store: BaselineStore | None = None) -> None:
        self._store = store

    @property
    def store(self) -> BaselineStore:
        return self._store or STORE

    # ------------------------------------------------------------ helpers
    def _w(self, p: Rog01Params, name: str) -> float:
        return float(p.weights.get(name, DEFAULT_WEIGHTS.get(name, 0.0)))

    @staticmethod
    def _ledger() -> Any | None:
        try:
            from aegis.controls.budget import _common as bud_common

            return bud_common.ledger()
        except Exception:
            return None

    def _quarantine_check(
        self, ctx: RequestContext, agent: str, cfg: ControlConfig
    ) -> Decision | None:
        st = self.store
        q = st.active_quarantine([f"session:{ctx.session_id}", f"agent:{agent}"])
        if q is None:
            return None
        led = self._ledger()
        if led is not None:
            # Released through the dashboard kill switch? Then the quarantine is over too.
            try:
                from aegis.budgets import killswitch as ks_mod

                snap = ctx.policy
                ks = getattr(getattr(getattr(snap, "doc", None), "budgets", None), "kill_switch", None)
                in_policy = ks_mod.match(ks, ctx.identity, ctx.session_id) is not None
                runtime = q.scope == "session" and led.kills.get(ctx.session_id) is not None
                if not (in_policy or runtime) and (q.scope == "session" or q.persisted):
                    st.release(q.key)
                    return None
            except Exception:
                log.debug("ROG-01 quarantine/ledger check failed", exc_info=True)
        return self._kill_decision(
            cfg,
            ctx,
            f"Aegis ROG-01: {q.key} is quarantined as a rogue agent ({q.reason}). Do not retry.",
            [Finding(control_id=self.id, detector="rogue.quarantined", category="rogue",
                     severity="high", score=q.score, meta={"scope": q.key, "signals": q.signals})],
            {"quarantine": q.key, "signals": q.signals, "score": q.score},
            q.score,
        )

    def _kill_decision(
        self,
        cfg: ControlConfig,
        ctx: RequestContext,
        reason: str,
        findings: list[Finding],
        meta: dict[str, Any],
        score: float,
    ) -> Decision:
        from aegis.budgets.stop import hard_stop

        stop = hard_stop("killed", ctx)
        m = dict(meta)
        m["response_headers"] = dict(stop.headers)
        m["stop"] = "killed"
        return Decision(
            action="block",
            control_id=self.id,
            reason=reason,
            score=round(score, 3),
            threshold=_params(cfg).high,
            severity="high",
            findings=findings,
            owasp=list(cfg.owasp or self.owasp),
            meta=m,
            **stop.kwargs(),
        )

    # ------------------------------------------------------------ evaluate
    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        i = interaction
        p = _params(cfg)
        agent, is_agent = who(ctx)
        if _glob(p.exempt_agents, agent):
            return None
        selftest = ctx.source == "selftest"
        dry = ctx.dry_run or selftest
        st = self.store

        if i.surface in IN_SURFACES:
            if not dry and p.scan_results:
                self._scan_result(ctx, i, p, agent)
            return None
        if i.surface not in OUT_SURFACES:
            return None

        if not selftest:
            q = self._quarantine_check(ctx, agent, cfg)
            if q is not None:
                return q

        now = st.now()
        skey = session_key(agent, ctx)
        if selftest:  # A-09: empty state
            base: AgentBaseline | None = None
            sess: SessionState | None = None
        else:
            base = st.peek_agent(agent) if is_agent else None
            sess = st.peek_session(skey)
        cap = capability(ctx, i)
        tool = tool_key(i)
        dest = destination_key(i)
        signals: list[tuple[str, float, str]] = []

        def add(name: str, detail: str, scale: float = 1.0) -> None:
            w = round(self._w(p, name) * scale, 3)
            if w > 0:
                signals.append((name, w, detail))

        # --- stateless: self-modification
        sm = self_modify(ctx, i, p)
        if sm:
            add("self_modify", sm)

        # --- spawning / delegation (attempts count, executed or not)
        sk = spawn_kind(i, p)
        if sk:
            if not dry:
                sess = sess or st.session(skey)
                sess.spawns.append(now)
                sess.spawn_total += 1
                recent = sum(1 for t in sess.spawns if t >= now - p.spawn_window_s)
                total = sess.spawn_total
            else:
                prior = sess.spawns if sess else ()
                recent = 1 + sum(1 for t in prior if t >= now - p.spawn_window_s)
                total = 1 + (sess.spawn_total if sess else 0)
            if recent >= p.spawn_burst_high:
                add("spawn_burst_high",
                    f"{recent} spawns/delegations in {int(p.spawn_window_s)}s ({sk})")
            elif recent >= p.spawn_burst_medium:
                add("spawn_burst", f"{recent} spawns/delegations in {int(p.spawn_window_s)}s ({sk})")
            elif total > p.max_spawns_per_session:
                add("spawn_session_cap",
                    f"{total} spawns in this session > {p.max_spawns_per_session} ({sk})")
        depth = delegation_depth(i, ctx, p)
        if depth is not None and depth > p.max_delegation_depth:
            add("delegation_depth", f"delegation depth {depth} > {p.max_delegation_depth}")

        # --- data-class escalation
        if sess is not None and sess.sensitive and _is_outbound(i, cap, p):
            dc, src = sess.sensitive
            where = dest or i.destination.name
            add("data_escalation", f"read {dc} data ({src}) earlier in this session, now "
                                   f"{cap.replace('_', ' ')} via {tool} to {where}")

        # --- call rate (record the attempt first; dry runs only peek)
        if is_agent and not dry:
            base = st.hit(agent, now)
        if base is not None and base.mature(now, p.min_events, p.min_sessions, p.min_age_s):
            seen = f"{base.events} calls / {len(base.sessions)} sessions"
            if tool not in base.tools and (
                cap in p.high_risk_capabilities or _glob(p.high_risk_tools, tool)
            ):
                add("new_high_risk_tool", f"{tool} ({cap}) never used before ({seen})")
            if dest and dest not in base.destinations:
                add("new_destination", f"{dest} never contacted before ({seen})")
            if base.minutes_active >= p.rate_min_minutes:
                cur = base.recent(now, p.rate_window_s) + (1 if dry else 0)
                usual = base.rate_baseline() * (p.rate_window_s / 60.0)
                if cur >= p.rate_floor and cur > p.rate_factor * max(usual, 1.0):
                    severe = cur >= 2 * p.rate_floor and cur > 2 * p.rate_factor * max(usual, 1.0)
                    add("call_rate_spike", f"{cur} calls in {int(p.rate_window_s)}s vs usual "
                                           f"{usual:.1f} (x{p.rate_factor:g} limit"
                                           f"{', severe' if severe else ''})",
                        1.5 if severe else 1.0)
            amt = i.amount_usd
            # (a first-ever spend is not a spike: the spend tool is then new -> new_high_risk_tool,
            # and ACT-01 already routes every spend in balanced)
            if amt is not None and amt > 0 and base.spend_n >= p.spend_min_samples:
                lim = max(p.spend_factor * base.spend_mean(), p.spend_floor_usd)
                if amt > lim and amt > base.spend_max:
                    add("spend_spike", f"${amt:,.2f} vs usual ${base.spend_mean():,.2f} "
                                       f"(max ${base.spend_max:,.2f})")
            if p.off_hours and base.events >= p.off_hours_min_events:
                hr = time.localtime(now).tm_hour
                if base.hours[hr] == 0:
                    add("off_hours", f"no activity at {hr:02d}:00 in {base.events} calls")

        # --- persistence: earlier flags in this session (spawn bursts escalate on their own count)
        if any(n not in SPAWN_SIGNALS for n, _, _ in signals) and sess is not None and sess.flags:
            n = sum(1 for t in sess.flags if t >= now - p.flag_window_s)
            if n:
                add("repeat_flags", f"{n} earlier anomal{'y' if n == 1 else 'ies'} in this session",
                    float(min(n, 3)))

        if not signals:
            return None
        raw = sum(w for _, w, _ in signals)
        score = round(min(1.0, raw), 3)
        findings = [
            Finding(control_id=self.id, detector=f"rogue.{name}", category="rogue",
                    severity="high" if w >= p.medium else "medium", score=round(w, 3),
                    meta={"signal": name, "detail": detail, "weight": round(w, 3)})
            for name, w, detail in signals
        ]
        why = "; ".join(f"{SIGNAL_LABEL.get(n, n)}: {d}" for n, _, d in signals)
        meta: dict[str, Any] = {
            "score": score,
            "signals": [n for n, _, _ in signals],
            "agent": agent,
            "baseline": (
                {"events": base.events, "sessions": len(base.sessions),
                 "mature": base.mature(now, p.min_events, p.min_sessions, p.min_age_s)}
                if base is not None else {"events": 0, "sessions": 0, "mature": False}
            ),
        }
        if score >= p.high and p.high_action == "block":
            reason = (f"Aegis ROG-01: rogue-agent behaviour for {agent} (score {score:.2f} >= "
                      f"{p.high:.2f}): {why}.")
            if p.quarantine:
                scope = p.quarantine_scope
                key = f"{scope}:{ctx.session_id if scope == 'session' else agent}"
                reason += f" {key} quarantined (kill switch). Do not retry."
                meta["quarantine"] = key
                if not dry:
                    self._quarantine(ctx, agent, key, scope, why, score,
                                     [n for n, _, _ in signals], p)
            if not dry:
                self._flag(skey, now, agent, tool, score, signals, "quarantine")
            return self._kill_decision(cfg, ctx, reason, findings, meta, score)
        if score >= p.high:
            action: str = p.high_action
        elif score >= p.medium:
            action = p.medium_action
        else:
            # below threshold: explainable trace row only (A-03), never changes the outcome
            return Decision(action="allow", control_id=self.id, score=score, threshold=p.medium,
                            reason=f"ROG-01 anomaly score {score:.2f} < {p.medium:.2f}: {why}",
                            findings=findings, severity="low", owasp=list(cfg.owasp or self.owasp),
                            meta=meta)
        reason = (f"Aegis ROG-01: unusual behaviour for {agent} (score {score:.2f} >= "
                  f"{p.medium:.2f}): {why}. A human must confirm this action.")
        approval = None
        if action == "require_approval":
            at = i.action_type or (f"tool:{i.tool_name}" if i.tool_name else f"{i.kind}.{i.surface}")
            approval = ApprovalDraft(
                kind="action",
                action_type=at,
                title=f"Unusual behaviour: {agent} -> {tool}",
                summary=reason,
                amount_usd=i.amount_usd,
                resource=i.resource or dest,
                labels={"signals": ",".join(n for n, _, _ in signals), "control": self.id},
                payload={"signals": [{"signal": n, "weight": round(w, 3), "detail": d}
                                     for n, w, d in signals], "score": score},
            )
        if not dry:
            self._flag(skey, now, agent, tool, score, signals, action)
        return Decision(
            action=action,  # type: ignore[arg-type]
            control_id=self.id,
            reason=reason,
            score=score,
            threshold=p.medium,
            severity="high" if score >= p.high else "medium",
            findings=findings,
            approval=approval,
            owasp=list(cfg.owasp or self.owasp),
            meta=meta,
        )

    # ------------------------------------------------------------ side effects
    def _flag(self, skey: str, now: float, agent: str, tool: str, score: float,
              signals: list[tuple[str, float, str]], outcome: str) -> None:
        st = self.store
        st.session(skey).flags.append(now)
        st.note_anomaly({"agent": agent, "session": skey.split("|", 1)[-1], "tool": tool,
                         "score": score, "outcome": outcome,
                         "signals": [{"signal": n, "detail": d} for n, _, d in signals]})
        led = self._ledger()
        if led is not None:
            try:
                led.enforcement.record(
                    "kill" if outcome == "quarantine" else "approval_requested",
                    f"agent:{agent}", self.id,
                    f"rogue-agent anomaly {score:.2f}: " + ", ".join(n for n, _, _ in signals),
                    detector=f"ROG-01.{signals[0][0]}",
                )
                from aegis.budgets.events import inc

                inc(led.rt, "aegis_rogue_anomalies_total", {"outcome": outcome})
            except Exception:
                log.debug("ROG-01 enforcement record failed", exc_info=True)

    def _quarantine(self, ctx: RequestContext, agent: str, key: str, scope: str, why: str,
                    score: float, names: list[str], p: Rog01Params) -> None:
        q = self.store.quarantine(key, scope, why[:300], score, names, p.quarantine_ttl_s)
        led = self._ledger()
        if led is None:
            return
        reason = f"ROG-01 rogue-agent quarantine: {why}"[:500]
        try:
            if scope == "session":
                led.kills.add(ctx.session_id, reason, p.quarantine_ttl_s)
            led.announce_kill(key, True, source="rogue-detector", reason=reason)
        except Exception:
            log.warning("ROG-01 runtime kill failed scope=%s", key, exc_info=True)
        if p.persist_quarantine:
            from aegis.budgets.events import spawn

            spawn(_persist(led, key, reason, q))

    def _scan_result(self, ctx: RequestContext, i: Interaction, p: Rog01Params, agent: str) -> None:
        """Mark the session as holding sensitive data when a result looks like PII."""
        st = self.store
        skey = session_key(agent, ctx)
        sess = st.peek_session(skey)
        if sess is not None and sess.sensitive:
            return
        sens = (i.labels or {}).get("sensitivity") or (i.labels or {}).get("data_class")
        if sens and str(sens).upper() in p.sensitive_classes:
            st.session(skey).sensitive = (str(sens).upper(), f"{i.tool_name or i.surface} result")
            return
        if not p.scan_max_chars:
            return
        budget = p.scan_max_chars
        for seg in i.segments:
            text = seg.text[:budget]
            if _PII_RX.search(text):
                st.session(skey).sensitive = ("CONFIDENTIAL",
                                              f"PII-shaped data in {i.tool_name or i.surface} result")
                return
            budget -= len(text)
            if budget <= 0:
                return

    # ------------------------------------------------------------ on_complete (learn)
    async def on_complete(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        verdict: Verdict,
        outcome: Outcome,
        cfg: ControlConfig,
    ) -> None:
        if ctx.dry_run or ctx.source == "selftest":
            return
        i = interaction
        if i.surface not in OUT_SURFACES:
            return
        if outcome.status_code >= 400 or verdict.action not in ("allow", "log", "redact"):
            return  # only executed calls shape the baseline
        p = _params(cfg)
        agent, is_agent = who(ctx)
        if _glob(p.exempt_agents, agent):
            return
        cap = capability(ctx, i)
        tool = tool_key(i)
        st = self.store
        if is_agent:
            st.observe(agent, ctx.session_id, tool=tool, destination=destination_key(i),
                       capability=cap, amount_usd=i.amount_usd)
        sens = str((i.labels or {}).get("sensitivity") or "").upper()
        if (cap == "data_read" and sens in p.sensitive_classes) or _glob(p.sensitive_read_tools, tool):
            sess = st.session(session_key(agent, ctx))
            if not sess.sensitive:
                sess.sensitive = (sens or "CONFIDENTIAL", f"{tool} {i.resource or ''}".strip())


async def _persist(led: Any, key: str, reason: str, q: Any) -> None:
    """Persist the quarantine into ``budgets.kill_switch`` (released from the dashboard)."""
    rt = getattr(led, "rt", None)
    pol = getattr(rt, "policy", None) if rt is not None else None
    if pol is None:
        return
    try:
        from aegis.budgets import killswitch as ks_mod

        patch = ks_mod.toggle_patch(pol.snapshot(), key, True)
        if not patch:
            q.persisted = True
            return
        res = await pol.apply_patch(patch, actor=None, source="budgets-ledger", reason=reason)
        status = getattr(res, "status", "?")
        if status in ("applied", "noop"):
            q.persisted = True
        else:
            log.warning("ROG-01 quarantine persist status=%s key=%s", status, key)
    except Exception as exc:
        log.warning("ROG-01 quarantine persist failed key=%s error=%s", key, exc)


CONTROLS = [RogueBehaviourControl()]
