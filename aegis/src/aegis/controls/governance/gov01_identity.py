"""GOV-01 Caller identity & attribution (plan 08 section 2.8, Addendum A-17 semantics).

Anonymous callers are allowed (attribution only); unregistered agent ids are logged;
invalid / revoked / expired Aegis keys, principal spoofing (key != X-Aegis-Agent) and disabled
principals are blocked; `require_auth` blocks unauthenticated data-plane calls. Key material
never appears in reasons or findings.
"""

from __future__ import annotations

from typing import Any, ClassVar

from aegis.controls.governance._common import Params, get_rt, parse_params, peek_agent, peek_member
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding

_ACTIONS = {"allow", "log", "redact", "require_approval", "block"}
_DEFAULT_SOURCES = ["proxy", "mcp", "hook", "egress", "guard"]
_SCOPE_BY_SOURCE = {"hook": ["hooks"], "mcp": ["mcp"], "egress": ["egress"], "guard": ["guard"]}
_MODEL_SCOPES = ["anthropic.messages", "openai.chat", "ollama.chat", "ollama.embed"]


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

        # 5. unregistered agent id (header-asserted)
        anonymous = agent_id == "anonymous" or (not agent_id and not ident.member_id)
        if agent_id and not anonymous and agent is None and not known:
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
