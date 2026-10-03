"""Integration-level checks that are not pipeline controls (plan 12 §2.5, gap G2).

- `load_params(snap)`: integration knobs from `controls[id=GOV-06].params` when present
  (Addendum / seed-fixes SF-26), else module defaults.
- `budget_precheck(...)`: block a prompt up front when a budget scope is hard/killed.
- `config_change(...)`: ConfigChange tamper guard (hooks / gateway / permission keys).
- `bypass_mode(...)`: detect `bypassPermissions`.

Results are `GuardResult`s; the handler turns them into hook output, an audit `system` event
and a bus `system` toast (never fake decision rows).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aegis.core.policy_schema import PolicySnapshot
from aegis.core.types import BudgetStatus, Identity

log = logging.getLogger(__name__)

HARNESS_CONTROL = "GOV-06"

DEFAULT_PROTECTED_PATHS = [
    "**/demo/claude/settings*.json",
    "**/demo/claude/mcp.json",
    "**/demo/claude/.agent_key",
    "**/.claude/settings*.json",
    "**/scripts/aegis-hook",
]
DEFAULT_GUARDED_KEYS = [
    "hooks",
    "disableAllHooks",
    "env.ANTHROPIC_BASE_URL",
    "env.ANTHROPIC_CUSTOM_HEADERS",
    "permissions",
    "enableAllProjectMcpServers",
    "mcpServers",
]


class IntegrationParams(BaseModel):
    """Knobs (CC plan §2.5) + the seed-fixes GOV-06 param names (aliases, SF-26)."""

    model_config = ConfigDict(extra="allow")

    pass_decision: Literal["none", "allow"] = "none"
    approval_surface: Literal["deny_link", "ask_self"] = "deny_link"
    max_hold_s: float = 90.0
    budget_precheck: bool = True
    config_change_guard: Literal["guard_keys", "block_all", "off"] = "guard_keys"
    deny_bypass_mode: bool = False
    scan_routed_mcp_results: bool = False
    internal_error: Literal["deny", "allow"] = "deny"
    agents: list[str] = Field(default_factory=lambda: ["claude-code@*"])
    protected_paths: list[str] = Field(default_factory=lambda: list(DEFAULT_PROTECTED_PATHS))
    config_change_keys: list[str] = Field(default_factory=lambda: list(DEFAULT_GUARDED_KEYS))
    # seed-fixes names
    block_bypass_permissions: bool | None = None
    budget_exhausted_prompt: Literal["block", "allow"] | None = None
    #: False when GOV-06 is configured but disabled / mode off (judges can switch it off live)
    guard_enabled: bool = True
    guard_mode: Literal["enforce", "monitor", "off"] = "enforce"


def load_params(snap: PolicySnapshot | None) -> IntegrationParams:
    raw: dict[str, Any] = {}
    enabled, mode = True, "enforce"
    cfg = None
    if snap is not None:
        try:
            cfg = snap.controls.get(HARNESS_CONTROL) or next(
                (c for c in snap.doc.controls if c.id == HARNESS_CONTROL), None
            )
        except Exception:
            cfg = None
    if cfg is not None:
        raw = dict(cfg.params or {})
        enabled, mode = bool(cfg.enabled), str(cfg.mode)
    try:
        p = IntegrationParams.model_validate(raw)
    except Exception:
        log.warning("invalid GOV-06 params; using defaults")
        p = IntegrationParams()
    if p.block_bypass_permissions is not None:
        p.deny_bypass_mode = p.block_bypass_permissions
    if p.budget_exhausted_prompt is not None:
        p.budget_precheck = p.budget_exhausted_prompt == "block"
    p.guard_enabled = enabled and mode != "off"
    p.guard_mode = mode if mode in ("enforce", "monitor", "off") else "enforce"  # type: ignore[assignment]
    return p


@dataclass
class GuardResult:
    action: Literal["allow", "log", "block"]
    reason: str
    control_id: str = HARNESS_CONTROL
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def blocks(self) -> bool:
        return self.action == "block"


# ---------------------------------------------------------------- budgets
def _control_enforced(snap: PolicySnapshot | None, control_id: str) -> bool:
    if snap is None:
        return False
    cfg = snap.controls.get(control_id)
    return cfg is not None and cfg.enabled and cfg.mode == "enforce"


def kill_switch_scope(snap: PolicySnapshot | None, identity: Identity, session_id: str) -> str | None:
    """Kill-switch scope that applies to this caller (policy `budgets.kill_switch`)."""
    if snap is None:
        return None
    ks = snap.doc.budgets.kill_switch
    if ks.global_:
        return "global"
    if identity.agent_id and identity.agent_id in ks.agents:
        return f"agent:{identity.agent_id}"
    if identity.member_id and identity.member_id in ks.members:
        return f"member:{identity.member_id}"
    if identity.team_id and identity.team_id in ks.teams:
        return f"team:{identity.team_id}"
    if session_id in ks.sessions:
        return f"session:{session_id}"
    return None


async def budget_precheck(
    rt: Any,
    identity: Identity,
    session_id: str,
    snap: PolicySnapshot | None,
    params: IntegrationParams,
    *,
    base_url: str,
) -> GuardResult | None:
    """Block a prompt when any budget scope of this caller is hard/killed (BUD-01 enforce)."""
    if not params.budget_precheck:
        return None
    killed = kill_switch_scope(snap, identity, session_id)
    if killed and (_control_enforced(snap, "EXE-04") or _control_enforced(snap, "BUD-01")):
        return GuardResult(
            "block",
            f"AEGIS-KILLED EXE-04: kill switch active for {killed}. Stop immediately.",
            control_id="EXE-04",
            data={"scope": killed},
        )
    if not _control_enforced(snap, "BUD-01"):
        return None
    try:
        scopes = list(rt.ledger.scopes_for(identity, session_id))
    except Exception:
        return None
    for scope in scopes:
        try:
            statuses: list[BudgetStatus] = list(await rt.ledger.status(scope))
        except Exception:
            continue
        for st in statuses:
            if st.scope != scope or st.state not in ("hard", "killed"):
                continue
            lim = f"{st.limit:g} {st.dimension}/{st.window}"
            url = f"{base_url.rstrip('/')}/ui/governance/budgets"
            if st.state == "killed":
                reason = f"AEGIS-KILLED EXE-04: kill switch active for {scope}. Stop immediately."
            else:
                reason = (
                    f"AEGIS-BUDGET BUD-01: budget exhausted for {scope} ({lim}, used "
                    f"{st.used:g}). Stop now and summarise progress for the user; an admin can "
                    f"raise it at {url}."
                )
            return GuardResult(
                "block",
                reason,
                control_id="BUD-01",
                data={"scope": scope, "dimension": st.dimension, "window": st.window,
                      "limit": st.limit, "used": st.used, "state": st.state},
            )
    return None


# ---------------------------------------------------------------- ConfigChange
def _get_dotted(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def guarded_subset(doc: Any, keys: list[str]) -> dict[str, Any]:
    return {k: v for k in keys if (v := _get_dotted(doc, k)) is not None}


#: file_path -> guarded subset last accepted in this process (baseline for "drops or changes")
_BASELINES: dict[str, dict[str, Any]] = {}


def config_change(
    source: str | None,
    file_path: str | None,
    params: IntegrationParams,
    *,
    baselines: dict[str, dict[str, Any]] | None = None,
) -> GuardResult:
    """Tamper guard for Claude Code settings changes during a governed session."""
    base = _BASELINES if baselines is None else baselines
    src = source or "unknown"
    data: dict[str, Any] = {"source": src, "file": Path(file_path).name if file_path else None}
    if src == "policy_settings":
        return GuardResult("log", "managed policy settings changed (cannot be blocked)", data=data)
    if not params.guard_enabled or params.config_change_guard == "off":
        return GuardResult("log", "config change guard disabled", data=data)
    if params.config_change_guard == "block_all":
        return GuardResult(
            "block",
            "Aegis: Claude Code settings changes are blocked during a governed session "
            "(config_change_guard: block_all).",
            data=data,
        )
    if src == "skills":
        return GuardResult("log", "skills changed", data=data)
    if not file_path:
        return GuardResult(
            "block", "Aegis: unidentified settings change blocked during a governed session.",
            data=data,
        )
    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except OSError:
        return GuardResult(
            "block",
            "Aegis: settings file unreadable after change; blocked during a governed session.",
            data=data,
        )
    try:
        doc = json.loads(text) if text.strip() else {}
    except ValueError:
        return GuardResult(
            "block", "Aegis: unparseable settings change blocked during a governed session.",
            data=data,
        )
    new = guarded_subset(doc, params.config_change_keys)
    old = base.get(file_path, {})
    changed = sorted(k for k in set(new) | set(old) if new.get(k) != old.get(k))
    data["changed_keys"] = changed
    if changed:
        return GuardResult(
            "block",
            "Aegis: changes to Claude Code hooks/gateway settings are blocked during a governed "
            f"session ({', '.join(changed)}).",
            data=data,
        )
    base[file_path] = new
    return GuardResult("log", "settings change without guarded keys", data=data)


# ---------------------------------------------------------------- permission mode
BYPASS_MODES = {"bypassPermissions"}


def bypass_mode(permission_mode: str | None, params: IntegrationParams) -> GuardResult | None:
    if permission_mode not in BYPASS_MODES:
        return None
    if params.deny_bypass_mode and params.guard_enabled and params.guard_mode == "enforce":
        return GuardResult(
            "block",
            "AEGIS-DENY GOV-06 (Agent harness integrity): tool calls are denied while Claude Code "
            "runs with --dangerously-skip-permissions (bypassPermissions). Restart without it.",
        )
    return GuardResult("log", "Claude Code runs in bypassPermissions mode; Aegis hooks still apply")


__all__ = [
    "DEFAULT_GUARDED_KEYS",
    "DEFAULT_PROTECTED_PATHS",
    "HARNESS_CONTROL",
    "GuardResult",
    "IntegrationParams",
    "budget_precheck",
    "bypass_mode",
    "config_change",
    "guarded_subset",
    "kill_switch_scope",
    "load_params",
]
