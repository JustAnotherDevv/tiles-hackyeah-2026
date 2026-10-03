"""ctl EXE-01 - Dangerous command guard (action-guards).

Structural shell analysis (``aegis.actions.shell``): normalization (NFKC, zero-width, ``$IFS``,
quote concatenation), pipe graph, nested ``$()``/``-c``/``eval``/``python -c`` bodies and decoded
base64 variants. Built-in detectors (``pipe_to_shell``, ``base64_exec``, ``reverse_shell``,
``rm_rf_broad``, ``chmod_world``, ``sudo``, ``ai_cli_bypass``, ``drop_table``, ``unsafe_deser``,
``crontab_write``, ``ollama_admin``) + ``params.deny_patterns`` -> ``cfg.action`` (block by default;
a judge can flip it to ``require_approval``). ``approve_patterns`` -> soft approval.
Benign twins (``rm -rf ./build``, ``echo "curl x | sh" > notes.md``) pass.
"""

from __future__ import annotations

from typing import ClassVar

from aegis.actions.argpath import first_arg
from aegis.actions.base import ActionGuardBase
from aegis.actions.commands import analyze_cached, command_text, matches_any
from aegis.actions.explain import Explain, mask
from aegis.actions.params import Exe01Params
from aegis.actions.rules_builtin import DB_TOOLS
from aegis.actions.rx import compile_rx
from aegis.actions.shell import DETECTOR_LABELS, Hit, code_hits, sql_hits
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import AppliesTo, ControlKind, Decision, Interaction, RequestContext

P = "controls[EXE-01].params"
SUFFIX = "Do not retry or work around this."


class DangerousCommandGuard(ActionGuardBase):
    id: ClassVar[str] = "EXE-01"
    family: ClassVar[str] = "EXE"
    name: ClassVar[str] = "Dangerous command guard"
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"tool.input", "mcp.call", "mcp.init"}, directions={"out"}
    )
    owasp: ClassVar[list[str]] = ["ASI05", "MCP05:2025", "LLM10:2026"]
    priority: ClassVar[int] = 20
    params_model = Exe01Params
    default_levers: ClassVar[list[str]] = [
        "controls[EXE-01].action",
        f"{P}.disabled_detectors",
        f"{P}.allow_patterns",
    ]

    def _hits(self, i: Interaction, p: Exe01Params) -> tuple[list[Hit], str | None, str]:
        """(hits, inspected text, source) over the command, code or SQL argument."""
        hits: list[Hit] = []
        text = command_text(i, p.shell_tools, p.command_args)
        source = "command"
        if text:
            a = analyze_cached(text, p.decode_depth, p.max_scan_chars)
            hits.extend(a.all_hits())
        elif matches_any(i.tool_name, p.code_tools):
            _, code = first_arg(i, p.command_args)
            if isinstance(code, str):
                text, source = code, "code"
                hits.extend(code_hits(code))
        if not text:
            path, sql = first_arg(i, p.sql_args)
            is_db = path == "sql" or matches_any(i.tool_name, DB_TOOLS)
            if is_db and isinstance(sql, str) and sql.strip():
                text, source = sql, "sql"
                hits.extend(sql_hits(sql))
        if text:
            for spec in p.deny_patterns:
                if compile_rx(spec.pattern).search(text):
                    hits.append(
                        Hit(spec.id, spec.reason or f"matches deny pattern {spec.id}", text[:60])
                    )
        disabled = set(p.disabled_detectors)
        return [h for h in hits if h.id not in disabled], text, source

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        p: Exe01Params = self.params(cfg)
        hits, text, source = self._hits(interaction, p)
        if not text:
            return None
        at = interaction.action_type or "code.exec"
        ex = Explain(
            facts={"source": source, "command": mask(text, 160), "detectors": [h.id for h in hits]}
        )
        if hits:
            first = hits[0]
            label = DETECTOR_LABELS.get(first.id, first.id.replace("_", " "))
            findings = [
                self.finding(
                    f"exe.cmd.{h.id}",
                    category="command",
                    severity="critical",
                    excerpt=h.excerpt,
                    via=h.via or None,
                    label=DETECTOR_LABELS.get(h.id, h.id),
                )
                for h in hits[:6]
            ]
            for h in hits[:6]:
                ex.check(
                    h.id,
                    DETECTOR_LABELS.get(h.id, h.id),
                    h.via or "direct",
                    None,
                    "fail",
                    f"{P}.disabled_detectors",
                )
            core = f"{label} — {first.detail}"
            labels = {"pattern": first.id}
            act = (
                cfg.action
                if cfg.action in ("block", "require_approval", "log", "allow")
                else "block"
            )
            if act == "block":
                return self.hard(
                    cfg,
                    interaction,
                    core=core,
                    findings=findings,
                    explain=ex,
                    action_type=at,
                    suffix=SUFFIX,
                )
            return await self.soft(
                ctx,
                interaction,
                cfg,
                core=core,
                findings=findings,
                explain=ex,
                action=act,
                action_type=at,
                title=f"Run a flagged command ({label})",
                labels=labels,
            )
        for spec in p.approve_patterns:
            if compile_rx(spec.pattern).search(text):
                ex.check(spec.id, "approval pattern", None, None, "fail", f"{P}.approve_patterns")
                return await self.soft(
                    ctx,
                    interaction,
                    cfg,
                    action="require_approval",
                    action_type="code.exec",
                    core=spec.reason or f"command matches approval pattern {spec.id}",
                    explain=ex,
                    title=f"Run command ({spec.id})",
                    findings=[
                        self.finding(
                            f"exe.cmd.{spec.id}",
                            category="command",
                            severity="medium",
                            excerpt=text[:60],
                        )
                    ],
                )
        if p.unknown_command != "allow" and source == "command":
            if any(compile_rx(rx).search(text.strip()) for rx in p.allow_patterns):
                return None
            ex.check(
                "unknown_command",
                "command not on the allow list",
                None,
                None,
                "info",
                f"{P}.unknown_command",
            )
            if p.unknown_command == "log":
                return self.note(
                    cfg, interaction, core="command not on the allow list", action="log", explain=ex
                )
            return await self.soft(
                ctx,
                interaction,
                cfg,
                action=p.unknown_command,
                action_type="code.exec",
                core="command not on the allow list",
                explain=ex,
                title="Run an unlisted command",
            )
        return None


CONTROLS = [DangerousCommandGuard()]
