"""ctl EXE-05 - Code-execution provenance & sandbox guard (action-guards, OWASP ASI05).

EXE-01 is a denylist of dangerous command *shapes*; EXE-05 is the positive control for *running
code*. Over the structural shell analysis (``aegis.actions.commands.exec_profile``) it finds every
segment that executes code:

* ``interpreter_file`` - python/node/bash/sh/zsh/ruby/perl/php/deno/bun/pwsh/... on a script file,
  ``source x.sh``, ``go run main.go`` (also behind ``uv run``/``poetry run``/``sudo``/``env``);
* ``inline_eval`` - ``python -c``, ``node -e``, ``perl -e``, ``ruby -e``, ``php -r``, ``deno eval``,
  ``pwsh -EncodedCommand``, ``eval``; plus code tools (``*.run_python``, ``*.execute_code``);
* ``direct_exec`` - ``./run.sh``, ``bin/tool`` (not system binaries);
* ``pkg_runner`` - ``npx``, ``bunx``, ``uvx``, ``pipx run``, ``npm exec``, ``pnpm|yarn dlx``,
  ``uv tool run``, ``go run pkg@v``, ``deno run https://...`` (downloads and runs a package);
* ``pkg_script`` - ``npm run``/``npm test``/``yarn x``/``make``/``just``/``cargo run``/
  ``pip install .`` (runs what a manifest such as package.json / Makefile says).

Decisions (strongest wins, every reason is listed):

1. **Write-then-exec taint.** Files the agent wrote in this session (Write / Edit / MultiEdit /
   NotebookEdit / MCP ``*.write_*`` tools, shell redirects, ``tee``, ``cp``, ``sed -i``) and files it
   downloaded (``curl -o``, ``wget``) are recorded per session (``aegis.actions.taint``, namespace
   ``written``). Executing such a file - or running a package script whose manifest the agent
   wrote - later in the session (or later in the same command) is decided by
   ``download_exec_action`` (block), ``untrusted_write_exec_action`` (block; the file was written
   while the session held untrusted content, EXE-03's flag) or ``write_exec_action``
   (require_approval). Signal ``write_then_exec``.
2. **Deferred execution.** A write to a path that runs automatically later (git hooks, shell rc
   files, LaunchAgents, cron, ``.envrc``) -> ``autoexec_write_action`` (require_approval).
3. **Sandbox posture.** For action types in ``require_sandbox_for`` (default ``[code.exec]``) an
   unsandboxed run -> ``unsandboxed_action`` (require_approval; label ``sandboxed=false`` routes
   it through approval rule ``code-exec-unsandboxed``). A run counts as sandboxed only when the
   *policy* says so: a recognised sandbox runner in the command (``bwrap``, ``firejail``,
   ``nsjail``, ``sandbox-exec``, ``minijail0``, ``runsc``, ``systemd-run``, ``docker|podman run
   --network none`` without host-root mounts), a tool in ``sandbox_tools`` (e.g. a remote code
   sandbox MCP server), or an agent in ``sandboxed_agents`` (operator attests the agent runs in an
   isolated container). A caller's own ``meta.sandbox`` claim is ignored unless
   ``trust_declared_sandbox: true``. Honest limit: Aegis does not attest isolation itself; it
   classifies the declared runner, so a misconfigured bwrap profile is still "sandboxed".
4. ``pkg_script`` with an untouched manifest -> ``pkg_script_action`` (log: visible, not blocked).

``trusted_exec`` (RE2 over the target) exempts known-safe targets (``.venv/bin/activate``,
``node_modules/.bin/*``, ``./gradlew``) from the posture check only - never from the taint check.
Pipe-to-shell inside one command (``curl … | sh``) stays EXE-01's (it blocks first).
"""

from __future__ import annotations

import os
import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from aegis.actions import taint
from aegis.actions.argpath import first_arg
from aegis.actions.base import ActionGuardBase
from aegis.actions.classify import glob_match, normalize_tool_name, refine
from aegis.actions.commands import (
    DEFAULT_COMMAND_ARGS,
    DEFAULT_SHELL_TOOLS,
    ExecIntent,
    ExecProfile,
    analyze_cached,
    command_text,
    exec_profile,
    matches_any,
    resolve_path,
    same_file,
)
from aegis.actions.explain import Explain, display_path, mask
from aegis.actions.fs import CASE_INSENSITIVE, compile_glob
from aegis.actions.rx import compile_rx
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext

P = "controls[EXE-05].params"
META = "exe.code"
SIGNAL = "write_then_exec"
SoftAction = Literal["allow", "log", "require_approval", "block"]
_RANK = {"allow": 0, "log": 1, "require_approval": 2, "block": 3}
_HOME_RX = re.compile(r"^/(?:Users|home)/[^/]+(?=/|$)")
_CLASSIFIED = ("code.", "package.", "db.", "email.", "egress.", "spend.", "file.")


class Exe05Params(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    require_sandbox_for: list[str] = Field(default_factory=lambda: ["code.exec"])
    unsandboxed_action: SoftAction = "require_approval"
    pkg_script_action: SoftAction = "log"
    write_exec_action: SoftAction = "require_approval"
    untrusted_write_exec_action: SoftAction = "block"
    download_exec_action: SoftAction = "block"
    sandboxed_write_exec_action: SoftAction = "log"
    autoexec_write_action: SoftAction = "require_approval"
    autoexec_paths: list[str] = Field(
        default_factory=lambda: [
            "**/.git/hooks/*",
            "**/.husky/*",
            "**/.envrc",
            "~/.bashrc",
            "~/.bash_profile",
            "~/.profile",
            "~/.zshrc",
            "~/.zprofile",
            "~/.zshenv",
            "~/.config/fish/config.fish",
            "~/Library/LaunchAgents/**",
            "/Library/LaunchDaemons/**",
            "/etc/cron*/**",
            "/etc/profile.d/**",
            "~/.config/autostart/**",
            "~/.config/systemd/user/**",
        ]
    )
    sandbox_tools: list[str] = Field(default_factory=list)  # tool globs that run in a sandbox
    sandboxed_agents: list[str] = Field(default_factory=list)  # agent globs attested sandboxed
    trust_declared_sandbox: bool = False  # honour meta.sandbox from the caller (claim, not proof)
    trusted_exec: list[str] = Field(
        default_factory=lambda: [
            r"(^|/)\.?venv/bin/activate(\.\w+)?$",
            r"(^|/)node_modules/\.bin/[^/]+$",
            r"^\./(gradlew|mvnw)$",
            r"^~/\.(bashrc|zshrc|profile|bash_profile|zprofile)$",
        ]
    )
    shell_tools: list[str] = Field(default_factory=lambda: list(DEFAULT_SHELL_TOOLS))
    command_args: list[str] = Field(default_factory=lambda: list(DEFAULT_COMMAND_ARGS))
    code_tools: list[str] = Field(
        default_factory=lambda: ["*.run_python", "*.execute_code", "*.run_code", "code.*"]
    )
    write_tools: list[str] = Field(
        default_factory=lambda: [
            "Write",
            "Edit",
            "MultiEdit",
            "NotebookEdit",
            "*.write_*",
            "*.edit_*",
            "*.create_file",
            "*.move_file",
            "*.copy_file",
            "*.append_*",
        ]
    )
    path_args: list[str] = Field(
        default_factory=lambda: [
            "file_path",
            "notebook_path",
            "destination",
            "dst",
            "target",
            "path",
            "file",
            "filename",
        ]
    )
    written_ttl_s: float = 86_400.0
    taint_ttl_turns: int = 20
    taint_ttl_s: float = 3600.0


def _key(path: str, cwd: str | None) -> str:
    """Normalised, home-agnostic path key (``/Users/x/p`` and ``~/p`` compare equal)."""
    p = resolve_path(path, cwd)
    home = os.path.expanduser("~")
    if home and home != "~" and (p == home or p.startswith(home + "/")):
        return "~" + p[len(home) :]
    return _HOME_RX.sub("~", p) if _HOME_RX.match(p) else p


def _glob_hit(patterns: list[str], key: str) -> str | None:
    for pat in patterns:
        if compile_glob(pat, "", CASE_INSENSITIVE).match(key):
            return pat
    return None


def _truthy(v: Any) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() in ("1", "true", "yes", "on"))


class CodeExecProvenanceGuard(ActionGuardBase):
    id: ClassVar[str] = "EXE-05"
    family: ClassVar[str] = "EXE"
    name: ClassVar[str] = "Code-execution provenance & sandbox guard"
    kind: ClassVar[ControlKind] = "stateful"
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"tool.input", "mcp.call"}, directions={"out"}
    )
    owasp: ClassVar[list[str]] = ["ASI05", "LLM10:2026", "MCP05:2025"]
    priority: ClassVar[int] = 36  # after EXE-01 (20), ACT-04 (33): they stay primary on ties
    params_model = Exe05Params
    default_levers: ClassVar[list[str]] = [
        f"{P}.require_sandbox_for",
        f"{P}.write_exec_action",
        f"{P}.sandbox_tools",
    ]

    # ------------------------------------------------------------------ analysis
    def _profile(self, i: Interaction, p: Exe05Params) -> tuple[ExecProfile, str | None]:
        cwd = i.meta.get("cwd") if isinstance(i.meta.get("cwd"), str) else None
        cmd = command_text(i, p.shell_tools, p.command_args)
        if cmd and cmd.strip():
            return exec_profile(analyze_cached(cmd), cwd), cmd
        tool = normalize_tool_name(i.tool_name)
        if tool and matches_any(tool, p.code_tools):
            _, code = first_arg(i, ["code", "source", "script", "program", "cmd"])
            intent = ExecIntent(
                "inline_eval",
                tool,
                None,
                f"tool {tool} runs model-supplied code",
                sandboxed=matches_any(tool, p.sandbox_tools),
                sandbox=tool if matches_any(tool, p.sandbox_tools) else None,
            )
            return ExecProfile(intents=[intent]), code if isinstance(code, str) else None
        return ExecProfile(), None

    def _context_sandbox(self, ctx: RequestContext, i: Interaction, p: Exe05Params) -> str | None:
        tool = normalize_tool_name(i.tool_name)
        if tool and p.sandbox_tools and matches_any(tool, p.sandbox_tools):
            return f"tool {tool} (sandbox_tools)"
        agent = ctx.identity.agent_id or ""
        if agent and any(glob_match(g, agent) for g in p.sandboxed_agents):
            return f"agent {agent} (sandboxed_agents)"
        if p.trust_declared_sandbox and _truthy(i.meta.get("sandbox")):
            return "caller-declared meta.sandbox"
        return None

    def _tool_write_path(self, i: Interaction, p: Exe05Params) -> str | None:
        tool = normalize_tool_name(i.tool_name)
        if not tool or not matches_any(tool, p.write_tools):
            return None
        _, val = first_arg(i, p.path_args)
        return val if isinstance(val, str) and val.strip() else None

    def _taint_hits(
        self,
        prof: ExecProfile,
        written: dict[str, dict[str, Any]],
        cwd: str | None,
    ) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        for it in prof.intents:
            targets: list[str] = []
            if it.kind in ("interpreter_file", "direct_exec") and it.target:
                targets.append(it.target)
            if it.kind == "pkg_script":
                targets.extend(it.manifests)
            for t in targets:
                tkey = _key(t, it.cwd or cwd)
                entry = None
                wpath = None
                for w in prof.writes:  # earlier in the same command
                    if w.index < it.index and same_file(_key(w.path, w.cwd or cwd), tkey):
                        entry, wpath = {"origin": w.origin, "tool": "same command"}, w.path
                        break
                if entry is None:
                    for path, e in written.items():
                        if same_file(path, tkey):
                            entry, wpath = e, path
                            break
                if entry is not None:
                    hits.append(
                        {
                            "intent": it,
                            "target": t,
                            "written": display_path(wpath or t),
                            "origin": entry.get("origin", "write"),
                            "untrusted": bool(entry.get("untrusted")),
                            "tool": entry.get("tool"),
                            "same_command": entry.get("tool") == "same command",
                        }
                    )
        return hits

    # ------------------------------------------------------------------ phases
    async def enrich(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> None:
        await super().enrich(ctx, interaction, cfg)
        p: Exe05Params = self.params(cfg)
        cwd = interaction.meta.get("cwd") if isinstance(interaction.meta.get("cwd"), str) else None
        prof, text = self._profile(interaction, p)
        wpath = self._tool_write_path(interaction, p)
        if not prof.intents and not prof.writes and not prof.chmod_x and not wpath:
            return
        sid = ctx.session_id
        written = taint.written_files(sid, p.written_ttl_s)  # snapshot BEFORE this call's writes
        hits = self._taint_hits(prof, written, cwd)
        ctx_sandbox = self._context_sandbox(ctx, interaction, p)
        ctx.state[f"{META}:{id(interaction)}"] = {
            "profile": prof,
            "text": text,
            "hits": hits,
            "ctx_sandbox": ctx_sandbox,
            "tool_write": wpath,
            "cwd": cwd,
        }
        # classification for routing / dashboards
        execs = [it for it in prof.intents if it.action_type == "code.exec"]
        if execs:
            cur = interaction.action_type or ""
            if not cur.startswith(_CLASSIFIED):
                refine(interaction, action_type="code.exec")
            sandboxed = bool(ctx_sandbox) or all(it.sandboxed for it in execs)
            labels: dict[str, Any] = {"sandboxed": "true" if sandboxed else "false"}
            if "pattern" not in interaction.labels:
                labels["pattern"] = execs[0].kind
            refine(interaction, labels=labels)
        if hits:
            cur_sig = [s for s in (interaction.labels.get("signals") or "").split(",") if s]
            if SIGNAL not in cur_sig:
                cur_sig.append(SIGNAL)
            interaction.labels["signals"] = ",".join(cur_sig)
        # record this call's writes for later calls (never for dry runs / selftests)
        if ctx.dry_run or ctx.source == "selftest" or not sid:
            return
        untrusted = taint.flag_live(sid, "untrusted", p.taint_ttl_turns, p.taint_ttl_s) is not None
        tool = normalize_tool_name(interaction.tool_name) or "?"
        if wpath:
            taint.mark_written(
                sid, _key(wpath, cwd), origin="write", tool=tool, untrusted=untrusted
            )
        for w in prof.writes:
            taint.mark_written(
                sid, _key(w.path, w.cwd or cwd), origin=w.origin, tool=tool, untrusted=untrusted
            )
        for path in prof.chmod_x:
            k = _key(path, cwd)
            for wp in taint.written_files(sid, p.written_ttl_s):
                if same_file(wp, k):
                    taint.mark_executable(sid, wp)

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        st = ctx.state.get(f"{META}:{id(interaction)}")
        if not st:
            return None
        p: Exe05Params = self.params(cfg)
        prof: ExecProfile = st["profile"]
        hits: list[dict[str, Any]] = st["hits"]
        ctx_sandbox: str | None = st["ctx_sandbox"]
        cwd: str | None = st["cwd"]
        text = st.get("text") or ""
        reasons: list[tuple[str, str, str]] = []  # (action, detector, sentence)
        findings = []
        ex = Explain(
            facts={
                "command": mask(text, 160) if text else None,
                "intents": [
                    {"kind": it.kind, "prog": it.prog, "target": it.target, "sandbox": it.sandbox}
                    for it in prof.intents[:8]
                ],
                "sandbox": ctx_sandbox,
            }
        )

        # 1) write-then-exec
        for h in hits:
            it: ExecIntent = h["intent"]
            sandboxed = bool(ctx_sandbox) or it.sandboxed
            if h["origin"] == "download":
                act, det = p.download_exec_action, "download_then_exec"
                why = f"runs {h['written']}, which the agent downloaded earlier{' in this command' if h['same_command'] else ' in this session'}"
                param = f"{P}.download_exec_action"
            elif h["untrusted"]:
                act, det = p.untrusted_write_exec_action, "untrusted_write_then_exec"
                why = f"runs {h['written']}, written by the agent after the session read untrusted content"
                param = f"{P}.untrusted_write_exec_action"
            elif sandboxed:
                act, det = p.sandboxed_write_exec_action, "write_then_exec_sandboxed"
                why = f"runs agent-written {h['written']} inside a sandbox ({it.sandbox or ctx_sandbox})"
                param = f"{P}.sandboxed_write_exec_action"
            else:
                act, det = p.write_exec_action, "write_then_exec"
                what = (
                    "package script from agent-edited"
                    if it.kind == "pkg_script"
                    else "agent-written file"
                )
                why = f"runs {what} {h['written']} ({it.prog}) without a sandbox"
                param = f"{P}.write_exec_action"
            reasons.append((act, det, why))
            ex.check(det, "executes a file the agent wrote", h["written"], None, "fail", param)
            findings.append(
                self.finding(
                    f"exe.code.{det}",
                    category="command",
                    severity="critical" if act == "block" else "high",
                    excerpt=f"{it.prog} {h['target']}",
                    origin=h["origin"],
                    written_by=h["tool"],
                )
            )

        # 2) deferred execution (autoexec paths)
        auto_targets: list[str] = []
        if st.get("tool_write"):
            auto_targets.append(_key(st["tool_write"], cwd))
        auto_targets += [_key(w.path, w.cwd or cwd) for w in prof.writes]
        for k in auto_targets:
            pat = _glob_hit(p.autoexec_paths, k)
            if pat:
                reasons.append(
                    (
                        p.autoexec_write_action,
                        "autoexec_write",
                        f"writes {display_path(k)}, which runs automatically later ({pat})",
                    )
                )
                ex.check(
                    "autoexec_write",
                    "deferred-execution path",
                    display_path(k),
                    pat,
                    "fail",
                    f"{P}.autoexec_paths",
                )
                findings.append(
                    self.finding(
                        "exe.code.autoexec_write",
                        category="command",
                        severity="high",
                        excerpt=display_path(k),
                    )
                )
                break

        # 3) sandbox posture
        tainted = {id(h["intent"]) for h in hits}
        for it in prof.intents:
            if id(it) in tainted:
                continue
            if it.kind == "pkg_script":
                if p.pkg_script_action != "allow":
                    reasons.append((p.pkg_script_action, "pkg_script", it.detail))
                continue
            if it.action_type not in p.require_sandbox_for:
                continue
            if it.sandboxed or ctx_sandbox:
                ex.check(
                    "sandbox",
                    "runs in a sandbox",
                    it.sandbox or ctx_sandbox,
                    None,
                    "pass",
                    f"{P}.sandbox_tools",
                )
                continue
            if it.target and any(compile_rx(rx).search(it.target) for rx in p.trusted_exec):
                ex.check(
                    "trusted_exec", "trusted target", it.target, None, "pass", f"{P}.trusted_exec"
                )
                continue
            reasons.append(
                (p.unsandboxed_action, f"unsandboxed_{it.kind}", f"{it.detail} outside a sandbox")
            )
            ex.check(
                f"unsandboxed_{it.kind}",
                "code.exec requires a sandbox",
                it.detail,
                "sandbox runner / sandbox_tools / sandboxed_agents",
                "fail",
                f"{P}.require_sandbox_for",
            )
            findings.append(
                self.finding(
                    f"exe.code.unsandboxed_{it.kind}",
                    category="command",
                    severity="medium",
                    excerpt=f"{it.prog} {it.target or ''}".strip(),
                )
            )

        reasons = [r for r in reasons if r[0] != "allow"]
        if not reasons:
            return None
        reasons.sort(key=lambda r: -_RANK.get(r[0], 0))
        act, det, core = reasons[0]
        extra = sorted({r[2] for r in reasons[1:] if r[2] != core})
        if extra:
            core = core + "; also " + "; ".join(extra[:3])
        labels = {"pattern": det, "sandboxed": interaction.labels.get("sandboxed") or "false"}
        if interaction.labels.get("signals"):
            labels["signals"] = interaction.labels["signals"]
        if act in ("log", "allow"):
            return self.note(
                cfg,
                interaction,
                core=core,
                action=act,
                explain=ex,
                findings=findings or None,
                action_type=interaction.action_type,
            )
        agent = ctx.identity.agent_id or ctx.identity.member_id or "agent"
        return await self.soft(
            ctx,
            interaction,
            cfg,
            core=core,
            action=act,
            action_type="code.exec",
            title=f"{agent}: run code ({det.replace('_', ' ')})",
            explain=ex,
            findings=findings or None,
            labels=labels,
            suffix="Do not retry or work around this." if act == "block" else "",
        )


CONTROLS = [CodeExecProvenanceGuard()]
