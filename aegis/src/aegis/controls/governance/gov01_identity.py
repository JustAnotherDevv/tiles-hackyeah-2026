"""GOV-01 Caller identity & attribution (plan 08 section 2.8, Addendum A-17 semantics; ASI03).

* invalid / revoked / expired Aegis keys, principal spoofing (key != X-Aegis-Agent) and disabled
  principals are blocked; `require_auth` blocks every unauthenticated data-plane call;
* ASI03 - **an identity claim is not a credential**: `X-Aegis-Agent` naming a *registered*
  agent without that agent's key is blocked on data-plane sources ("agent identity not proven",
  `unproven_agent_action`); identity hints count only on `unproven_hint_sources` (default none).
  A request with NO claim is never blocked for that alone (anonymous least privilege below). With a non-blocking action the
  caller is downgraded to the anonymous least-privilege tool allowlist instead;
* anonymous callers and unregistered agent ids get the restrictive `anonymous_allowed_tools`
  allowlist on tool / MCP calls (never "skip the allowlist");
* per-session credential scope: an explicit session id is bound to the first credential that
  used it; another principal, or a credential-less call, in that session is blocked
  (`session_binding_action`) - no session hijack / credential relay.
Key material never appears in reasons or findings.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Any, ClassVar

from aegis.actions.classify import normalize_tool_name, tool_matches
from aegis.controls.governance._common import Params, get_rt, parse_params, peek_agent, peek_member
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding

_ACTIONS = {"allow", "log", "redact", "require_approval", "block"}
_DEFAULT_SOURCES = ["proxy", "mcp", "hook", "egress", "guard"]
_SCOPE_BY_SOURCE = {"hook": ["hooks"], "mcp": ["mcp"], "egress": ["egress"], "guard": ["guard"]}
_MODEL_SCOPES = ["anthropic.messages", "openai.chat", "ollama.chat", "ollama.embed"]
_TOOL_SURFACES = frozenset({"tool.input", "mcp.call"})
#: least-privilege tool set of an unauthenticated caller: read-only discovery, nothing that
#: spends, sends, writes, executes or reads customer data.
ANONYMOUS_TOOLS = [
    "Read",
    "Glob",
    "Grep",
    "LS",
    "TodoWrite",
    "*.list_*",
    "*.get_*",
    "*.search_*",
    "*.describe_*",
]
_NO_SESSION = frozenset({"", "default", "none", "null"})
_MAX_BINDINGS = 20_000
_KEY_HINT = "send the agent's key (Authorization: Bearer aegis_... or X-Aegis-Agent-Key)"


class Gov01Params(Params):
    require_auth: bool | None = None  # None -> policy defaults.require_auth
    require_auth_sources: list[str] = list(_DEFAULT_SOURCES)
    anonymous_action: str = "allow"
    unknown_agent_action: str | None = None  # None -> control action (log)
    block_inactive: bool = True
    block_invalid_keys: bool = True
    block_principal_mismatch: bool = True
    # Addendum A-17 / synth-A spelling (action words; win over the booleans when set)
    invalid_key_action: str | None = None
    disabled_principal_action: str | None = None
    principal_mismatch_action: str | None = None
    enforce_key_scopes: bool | str = False  # False | True(=log) | "log" | "block"
    exempt_agents: list[str] = ["selftest"]
    # ASI03 (identity & privilege abuse)
    unproven_agent_action: str = "block"  # registered agent claimed without its key
    # Sources where an identity *hint* (demo-mode guard body `identity`, Claude Code UA detection)
    # counts as a claim. Default none: hints are attribution only; X-Aegis-Agent is the claim.
    unproven_hint_sources: list[str] = []
    anonymous_allowed_tools: list[str] | None = list(ANONYMOUS_TOOLS)  # None = legacy (no list)
    anonymous_tool_action: str = "block"
    session_binding_action: str = "block"  # allow = off


def _act(explicit: str | None, flag: bool) -> str:
    if explicit and explicit in _ACTIONS:
        return explicit
    return "block" if flag else "log"


class CallerIdentity(BaseControl):
    id: ClassVar[str] = "GOV-01"
    family: ClassVar[str] = "GOV"
    name: ClassVar[str] = "Caller identity & attribution"
    kind: ClassVar[str] = "deterministic"  # type: ignore[misc]
    applies_to: ClassVar[AppliesTo] = AppliesTo()
    owasp: ClassVar[list[str]] = ["ASI03", "ASI07", "MCP07:2025", "LLM03:2026"]
    priority: ClassVar[int] = 1

    _params_cache: ClassVar[dict[int, tuple[Any, Gov01Params]]] = {}
    #: (runtime id, session id) -> (principal, key id) of the first credential seen (LRU)
    _bindings: ClassVar[OrderedDict[tuple[int, str], tuple[str, str | None]]] = OrderedDict()
    _bind_lock: ClassVar[Lock] = Lock()

    def params(self, cfg: Any) -> Gov01Params:
        hit = self._params_cache.get(id(cfg))
        if hit is not None and hit[0] is cfg:
            return hit[1]
        p = parse_params(Gov01Params, getattr(cfg, "params", None), self.id)
        if len(self._params_cache) > 64:
            self._params_cache.clear()
        self._params_cache[id(cfg)] = (cfg, p)
        return p

    def _finding(self, detector: str, severity: str = "high", **meta: Any) -> Finding:
        return Finding(
            control_id=self.id,
            detector=detector,
            category="governance",
            severity=severity,
            meta=meta,
        )  # type: ignore[arg-type]

    def _verdict(
        self,
        cfg: Any,
        action: str,
        reason: str,
        finding: Finding,
        status: int | None = None,
        error_type: str | None = None,
    ) -> Decision | None:
        if action == "allow":
            return None
        kw: dict[str, Any] = {}
        if action == "block" and status is not None:
            kw = {"http_status": status, "error_type": error_type}
        return self.decide(cfg, action=action, reason=reason, findings=[finding], **kw)

    # ------------------------------------------------------------------ ASI03 helpers
    def _anonymous_tool_denied(
        self,
        cfg: Any,
        interaction: Any,
        p: Gov01Params,
        agent_id: str | None,
        anonymous: bool,
        unproven: bool,
    ) -> Decision | None:
        allowed = p.anonymous_allowed_tools
        if allowed is None or getattr(interaction, "surface", None) not in _TOOL_SURFACES:
            return None
        tool = normalize_tool_name(getattr(interaction, "tool_name", None))
        if not tool or any(tool_matches(a, interaction) for a in allowed):
            return None
        who = (
            "anonymous caller"
            if anonymous
            else f"{'unproven' if unproven else 'unregistered'} agent '{agent_id}'"
        )
        return self._verdict(
            cfg,
            p.anonymous_tool_action,
            f"{who} may not call {tool}: not on the anonymous least-privilege tool allowlist "
            f"({_KEY_HINT})",
            self._finding("gov.anonymous_tool", "high", tool=tool, claimed=agent_id),
            403,
            "forbidden",
        )

    def _session_binding(
        self, rt: Any, ctx: Any, ident: Any, cfg: Any, p: Gov01Params
    ) -> Decision | None:
        action = p.session_binding_action
        sid = str(getattr(ctx, "session_id", "") or "").strip()
        if action not in _ACTIONS or action == "allow" or sid.lower() in _NO_SESSION:
            return None
        slot = (id(rt), sid)
        authed = bool(getattr(ident, "authenticated", False))
        principal = getattr(ident, "principal", None) or ""
        with self._bind_lock:
            bound = self._bindings.get(slot)
            if bound is None:
                if authed and principal:
                    self._bindings[slot] = (principal, getattr(ident, "key_id", None))
                    if len(self._bindings) > _MAX_BINDINGS:
                        self._bindings.popitem(last=False)
                return None
            self._bindings.move_to_end(slot)
        bound_principal, bound_key = bound
        if authed and principal == bound_principal:
            return None
        presented = f"'{principal}'" if authed else "no credential"
        return self._verdict(
            cfg,
            action,
            f"session '{sid[:64]}' is bound to the credential of '{bound_principal}' "
            f"(key {bound_key or '?'}); request presents {presented}",
            self._finding(
                "gov.session_binding",
                "critical",
                session=sid[:64],
                bound_principal=bound_principal,
                presented=principal if authed else None,
            ),
            401,
            "unauthenticated",
        )

    async def evaluate(self, ctx: Any, interaction: Any, cfg: Any) -> Decision | None:
        p = self.params(cfg)
        ident = ctx.identity
        agent_id = ident.agent_id
        if agent_id and agent_id in p.exempt_agents:
            return None
        rt = get_rt()

        # 1. credential problems (revoked / expired / unknown aegis key)
        err = getattr(ident, "credential_error", None)
        if err:
            key_id = getattr(ident, "key_id", None)
            if err == "unknown_key":
                reason = "unknown Aegis API key"
            else:
                reason = f"Aegis API key {key_id or '?'} {err}"
            return self._verdict(
                cfg,
                _act(p.invalid_key_action, p.block_invalid_keys),
                reason,
                self._finding(
                    f"gov.key_{'unknown' if err == 'unknown_key' else err}",
                    key_id=key_id,
                    principal=ident.principal,
                ),
                401,
                "unauthenticated",
            )

        # 2. spoofing: key principal != asserted X-Aegis-Agent
        if getattr(ident, "principal_mismatch", False):
            asserted = getattr(ident, "asserted_agent_id", None)
            key_principal = agent_id or ident.member_id
            return self._verdict(
                cfg,
                _act(p.principal_mismatch_action, p.block_principal_mismatch),
                f"X-Aegis-Agent '{asserted}' does not match key principal '{key_principal}'",
                self._finding(
                    "gov.principal_mismatch",
                    "critical",
                    asserted=asserted,
                    principal=ident.principal,
                ),
                401,
                "unauthenticated",  # CONTRACTS A-18
            )

        # 3. disabled / deactivated principal
        known = getattr(ident, "known", None)
        active = getattr(ident, "principal_active", True)
        agent = None
        if agent_id and agent_id != "anonymous":
            agent = await peek_agent(rt, agent_id)
            if agent is not None:
                known, active = True, bool(agent.active) and active
        elif ident.member_id:
            member = await peek_member(rt, ident.member_id)
            if member is not None:
                known, active = True, bool(member.active) and active
        if known and not active:
            who = f"agent {agent_id}" if agent_id else f"member {ident.member_id}"
            return self._verdict(
                cfg,
                _act(p.disabled_principal_action, p.block_inactive),
                f"{who} is disabled",
                self._finding("gov.principal_inactive", principal=ident.principal),
                403,
                "forbidden",  # CONTRACTS A-18
            )

        # 4. authentication required (data-plane sources only)
        snap = getattr(ctx, "policy", None)
        if snap is None and rt is not None and getattr(rt, "policy", None) is not None:
            try:
                snap = rt.policy.snapshot()
            except Exception:
                snap = None
        require = p.require_auth
        if require is None:
            require = bool(
                getattr(
                    getattr(getattr(snap, "doc", None), "defaults", None), "require_auth", False
                )
            )
        if require and ctx.source in p.require_auth_sources and not ident.authenticated:
            return self._verdict(
                cfg,
                "block",
                "authentication required (Aegis API key)",
                self._finding("gov.auth_required", principal=ident.principal),
                401,
                "unauthenticated",
            )

        data_plane = ctx.source in p.require_auth_sources
        method = getattr(ident, "auth_method", None)

        # 4b. per-session credential scope (ASI03): a session is bound to its first credential
        bound = self._session_binding(rt, ctx, ident, cfg, p) if data_plane else None
        if bound is not None:
            return bound

        # 5a. unproven claim (ASI03): a registered agent named without that agent's key
        unproven = bool(
            data_plane
            and agent_id
            and agent_id != "anonymous"
            and known
            and not ident.authenticated
            and (method == "header" or (method == "hint" and ctx.source in p.unproven_hint_sources))
        )
        if unproven and p.unproven_agent_action == "block":
            via = "X-Aegis-Agent" if method == "header" else "an identity hint"
            return self._verdict(
                cfg,
                "block",
                f"agent identity not proven: '{agent_id}' claimed via {via} without that "
                f"agent's key ({_KEY_HINT})",
                self._finding(
                    "gov.identity_unproven",
                    "high",
                    claimed=agent_id,
                    auth_method=method,
                    source=ctx.source,
                ),
                401,
                "unauthenticated",
            )

        anonymous = agent_id == "anonymous" or (not agent_id and not ident.member_id)
        unregistered = bool(agent_id and not anonymous and agent is None and not known)

        # 5b. least privilege (ASI03): anonymous, unregistered and (non-blocked) unproven callers
        #     only get the anonymous tool allowlist on tool / MCP calls
        if (anonymous or unregistered or unproven) and data_plane:
            denied = self._anonymous_tool_denied(cfg, interaction, p, agent_id, anonymous, unproven)
            if denied is not None:
                return denied

        if unproven:
            return self._verdict(
                cfg,
                p.unproven_agent_action,
                f"agent identity not proven: '{agent_id}' (downgraded to anonymous least "
                "privilege)",
                self._finding(
                    "gov.identity_unproven", "high", claimed=agent_id, auth_method=method
                ),
            )

        # 5. unregistered agent id (header-asserted)
        if unregistered:
            action = p.unknown_agent_action or cfg.action
            return self._verdict(
                cfg,
                action,
                f"unregistered agent '{agent_id}' (header-asserted)",
                self._finding("gov.unregistered_agent", "medium", principal=ident.principal),
            )

        # 6. anonymous caller: attribution only by default
        if anonymous:
            return self._verdict(
                cfg,
                p.anonymous_action,
                "anonymous caller (no Aegis identity)",
                self._finding("gov.anonymous", "low"),
                401,
                "unauthenticated",
            )

        # 7. key scopes (could; log by default when enabled)
        if p.enforce_key_scopes and getattr(ident, "auth_method", None) == "api_key":
            scopes = list(getattr(ident, "key_scopes", []) or [])
            needed = _SCOPE_BY_SOURCE.get(ctx.source)
            if needed is None and interaction.surface in ("model.request", "model.admin"):
                needed = _MODEL_SCOPES
            if needed and scopes and not any(s in scopes for s in needed):
                mode = p.enforce_key_scopes
                action = "block" if mode == "block" else "log"
                return self._verdict(
                    cfg,
                    action,
                    f"key {getattr(ident, 'key_id', '?')} lacks scope {'|'.join(needed)}",
                    self._finding("gov.key_scope", "medium", key_id=getattr(ident, "key_id", None)),
                    403,
                    "policy_blocked",
                )
        return None


CONTROLS = [CallerIdentity()]
