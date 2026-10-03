"""ctl GOV-06 - Agent harness integrity (Claude Code). Addendum A-48 [SF-26].

Owner: claude-code-integration. Discovered via Addendum A-15 (`aegis.integrations` is scanned for
`CONTROLS`). Kind D (deterministic), priority 20, surfaces prompt.user / tool.input /
config.change. It returns `None` unless the caller is a Claude Code agent (`params.agents` glob on
`identity.agent_id`) or the interaction carries `meta.client == "claude-code"` / `meta.claude_code`.

Blocks:
- tool.input: writes/edits to `params.protected_paths` (Write/Edit/MultiEdit/NotebookEdit file
  paths, or a Bash command that mutates one of them: `>`/`tee`/`sed -i`/`rm`/`mv`/`cp`/`chmod`...);
- tool.input (strict, `block_bypass_permissions: true`): any tool call while Claude Code runs in
  `bypassPermissions` mode;
- config.change: a Claude Code `ConfigChange` whose changed keys intersect
  `params.config_change_keys` (or whose file is unreadable / unparseable). The hook handler puts
  `meta.config_change = {source, file, changed_keys, problem}` on the interaction; without that key
  the interaction is a policy proposal and belongs to GOV-05 (no overlap);
- prompt.user (`budget_exhausted_prompt: block`): the hook handler found a hard/killed budget scope
  (`meta.claude_code.budget_exhausted`), so the prompt is stopped before any model spend.
"""

from __future__ import annotations

import fnmatch
import re
import shlex
from typing import Any, ClassVar

from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import (
    AppliesTo,
    ControlKind,
    Decision,
    Finding,
    Identity,
    Interaction,
    RequestContext,
)

from .guards import DEFAULT_PROTECTED_PATHS, IntegrationParams, params_from_raw

#: tools whose `file_path` / `notebook_path` argument is written
WRITE_TOOLS: frozenset[str] = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
SHELL_TOOLS: frozenset[str] = frozenset({"Bash"})
_MUTATING = re.compile(
    r"(^|[\s;&|(])(rm|mv|cp|tee|chmod|chown|truncate|ln|install|dd|unlink)\b"
    r"|\bsed\b[^|;&]*\s-[a-zA-Z]*i"
    r"|\bperl\b[^|;&]*\s-[a-zA-Z]*i"
    r"|>>?\s*\S"
)
DEFAULT_CONFIG_KEYS = [
    "hooks", "env.ANTHROPIC_BASE_URL", "env.ANTHROPIC_CUSTOM_HEADERS", "permissions.defaultMode",
    "disableAllHooks",
]


def _params(cfg: ControlConfig) -> IntegrationParams:
    raw = dict(cfg.params or {})
    raw.setdefault("config_change_keys", list(DEFAULT_CONFIG_KEYS))
    return params_from_raw(raw)


def in_scope(identity: Identity | None, interaction: Interaction, agents: list[str]) -> bool:
    meta = interaction.meta or {}
    if meta.get("client") == "claude-code" or isinstance(meta.get("claude_code"), dict):
        return True
    agent_id = identity.agent_id if identity is not None else None
    return bool(agent_id) and any(fnmatch.fnmatchcase(agent_id, g) for g in agents)


def path_protected(path: str, patterns: list[str]) -> str | None:
    """The first protected-path glob matching `path` (absolute or relative), else None."""
    if not path:
        return None
    p = path.replace("\\", "/")
    cands = {p, "/" + p.lstrip("/")}
    if p.startswith("./"):
        cands.add("/" + p[2:])
    for pat in patterns:
        tail = pat[3:] if pat.startswith("**/") else None
        for c in cands:
            if fnmatch.fnmatch(c, pat) or (tail and (fnmatch.fnmatch(c, tail)
                                                     or fnmatch.fnmatch(c, "*/" + tail))):
                return pat
    return None


def _shell_tokens(command: str) -> list[str]:
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        return command.split()


def bash_touches_protected(command: str, patterns: list[str]) -> str | None:
    """Protected glob hit by a *mutating* shell command (reads are left to EXE-02)."""
    if not command or not _MUTATING.search(command):
        return None
    for tok in _shell_tokens(command):
        tok = tok.strip("'\"")
        if "/" not in tok and "aegis-hook" not in tok and ".agent_key" not in tok:
            continue
        hit = path_protected(tok, patterns)
        if hit:
            return hit
    return None


def _target_path(args: dict[str, Any]) -> str:
    for k in ("file_path", "notebook_path", "path"):
        v = args.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


class HarnessIntegrity(BaseControl):
    id: ClassVar[str] = "GOV-06"
    family: ClassVar[str] = "GOV"
    name: ClassVar[str] = "Agent harness integrity (Claude Code)"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"prompt.user", "tool.input", "config.change"}
    )
    owasp: ClassVar[list[str]] = ["ASI03", "ASI10", "LLM06:2026"]
    priority: ClassVar[int] = 20

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        p = _params(cfg)
        if not in_scope(ctx.identity, interaction, p.agents):
            return None
        cc = (interaction.meta or {}).get("claude_code") or {}
        if interaction.surface == "config.change":
            return self._config_change(interaction, cfg, p)
        if interaction.surface == "prompt.user":
            return self._prompt(cc, cfg, p)
        if interaction.surface == "tool.input":
            return self._tool_input(interaction, cc, cfg, p)
        return None

    # ------------------------------------------------------------ surfaces
    def _finding(self, detector: str, *, severity: str = "high", **meta: Any) -> Finding:
        return Finding(control_id=self.id, detector=detector, category="governance",
                       severity=severity, meta=meta)  # type: ignore[arg-type]

    def _config_change(
        self, i: Interaction, cfg: ControlConfig, p: IntegrationParams
    ) -> Decision | None:
        info = (i.meta or {}).get("config_change")
        if not isinstance(info, dict):
            return None  # a policy proposal: GOV-05's job
        source = str(info.get("source") or "unknown")
        if source == "policy_settings":
            return None  # managed settings cannot be blocked
        problem = info.get("problem")
        changed = [str(k) for k in info.get("changed_keys") or []]
        guarded = list(p.config_change_keys)
        hits = [k for k in changed
                if any(k == g or k.startswith(g + ".") or g.startswith(k + ".") for g in guarded)]
        if p.config_change_guard == "block_all":
            hits = hits or ["*"]
        if not hits and not problem:
            return None
        what = ", ".join(hits) if hits else str(problem)
        return self.decide(
            cfg,
            reason=f"Claude Code settings change ({source}: {what}) is blocked during a governed "
                   "session; hooks, gateway and permission settings are tamper-protected",
            findings=[self._finding("harness.config_change", source=source, keys=hits,
                                    problem=problem, file=info.get("file"))],
            meta={"config_change": {"source": source, "keys": hits, "file": info.get("file")}},
        )

    def _prompt(self, cc: dict[str, Any], cfg: ControlConfig, p: IntegrationParams) -> Decision | None:
        be = cc.get("budget_exhausted")
        if not isinstance(be, dict) or not p.budget_precheck:
            return None
        killed = be.get("state") == "killed"
        scope = be.get("scope") or "this agent"
        return self.decide(
            cfg,
            reason=(f"kill switch active for {scope}" if killed
                    else f"budget exhausted for {scope}; prompt stopped before any model spend"),
            findings=[self._finding("harness.budget_exhausted_prompt", scope=scope,
                                    state=be.get("state"))],
            http_status=429 if killed else 402,
            error_type="killed" if killed else "budget_exceeded",
            retry_after_s=3600 if killed else None,
            meta={k: be.get(k) for k in ("scope", "limit", "window", "dimension", "state")
                  if be.get(k) is not None}
            | {"response_headers": {"x-should-retry": "false"}},
        )

    def _tool_input(
        self, i: Interaction, cc: dict[str, Any], cfg: ControlConfig, p: IntegrationParams
    ) -> Decision | None:
        mode = cc.get("permission_mode")
        if mode == "bypassPermissions" and p.deny_bypass_mode:
            return self.decide(
                cfg,
                reason="tool calls are denied while Claude Code runs with "
                       "--dangerously-skip-permissions (bypassPermissions); restart without it",
                findings=[self._finding("harness.bypass_permissions", permission_mode=mode)],
            )
        patterns = list(p.protected_paths or DEFAULT_PROTECTED_PATHS)
        tool = cc.get("raw_tool_name") or i.tool_name or ""
        args = i.tool_args if isinstance(i.tool_args, dict) else {}
        hit: str | None = None
        how = ""
        if tool in WRITE_TOOLS:
            hit = path_protected(_target_path(args), patterns)
            how = f"{tool} of a protected harness file"
        elif tool in SHELL_TOOLS:
            cmd = args.get("command")
            hit = bash_touches_protected(cmd, patterns) if isinstance(cmd, str) else None
            how = "shell command modifying a protected harness file"
        if not hit:
            return None
        return self.decide(
            cfg,
            reason=f"{how} ({hit}); the agent may not edit its own guardrails (hooks, gateway "
                   "settings, MCP config, agent key)",
            findings=[self._finding("harness.protected_path", pattern=hit, tool=tool)],
        )


CONTROLS = [HarnessIntegrity()]

__all__ = ["CONTROLS", "HarnessIntegrity", "bash_touches_protected", "in_scope", "path_protected"]
