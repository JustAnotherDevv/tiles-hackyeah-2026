"""DLP-08 - Vault & controlled re-identification. Deterministic, priority 90.

* ``model.response`` toward the local user (``local_user`` in ``rehydrate_to``) with a
  non-empty session vault -> ``allow`` + ``meta {rehydrate: true, roles: ["assistant"]}``; the
  core response path then calls ``rt.redactor.rehydrate`` on assistant text only (never on
  ``tool_use`` inputs).
* ``tool.input`` to a LOCAL tool whose args carry this session's placeholders -> ``log``
  ("Rehydrated 2 placeholders for local tool Write") + ``meta.rehydrate``; the hook handler maps
  it to ``updatedInput`` via ``rt.redactor.rehydrate_obj``. With ``respect_matrix`` only
  classes whose ``matrix[class].local`` is allow/log are restored (a PAN stays ``[PAN_1]``).
* Third-party / remote tools (WebFetch, MCP SaaS): placeholders pass through untouched;
  ``tool_args.aegis_rehydrate: true`` toward them -> ``block`` (A15).
* Shell tools whose command has network egress (curl, wget, ssh, URLs) keep placeholders.
Raw values never appear in findings.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding, Interaction, RequestContext
from aegis.redaction.placeholders import PLACEHOLDER_RE, canonical_key
from aegis.redaction.policy import effective_matrix, load_params

from ._common import get_engine, snapshot, tool_matches

log = logging.getLogger(__name__)
_rx_cache: dict[tuple[str, ...], list[Any]] = {}


def _compile(patterns: list[str]) -> list[Any]:
    key = tuple(patterns)
    got = _rx_cache.get(key)
    if got is not None:
        return got
    out = []
    for pat in patterns:
        try:
            import re2

            out.append(re2.compile(pat))
        except Exception:
            log.warning("dlp-08 deny_command_patterns: invalid RE2 pattern skipped")
    _rx_cache[key] = out
    return out


class Dlp08(BaseControl):
    id: ClassVar[str] = "DLP-08"
    family: ClassVar[str] = "DLP"
    name: ClassVar[str] = "Vault & controlled re-identification"
    kind: ClassVar[str] = "deterministic"  # type: ignore[assignment]
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces={"model.response", "tool.input"})
    owasp: ClassVar[list[str]] = ["LLM02:2026", "MCP10:2025", "ASI03"]
    priority: ClassVar[int] = 90

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        eng = get_engine()
        snap = snapshot(ctx)
        p = load_params(self.id, cfg, snap)
        vault = eng.vaults.peek(ctx.session_id)
        if interaction.surface == "model.response":
            return self._response(ctx, interaction, cfg, p, vault, snap)
        if interaction.surface == "tool.input":
            return self._tool_input(ctx, interaction, cfg, p, vault, snap)
        return None

    # ------------------------------------------------------------------ model.response
    def _response(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        cfg: ControlConfig,
        p: Any,
        vault: Any,
        snap: Any,
    ) -> Decision | None:
        if vault is None or len(vault) == 0:
            return None
        if (
            "local_user" not in p.rehydrate_to
            or interaction.destination.dest_class == "third_party"
        ):
            return None
        enabled = True
        try:
            enabled = bool(snap.doc.defaults.rehydrate_responses) if snap is not None else True
        except Exception:
            enabled = True
        ctx.state["redaction.rehydrate_entities"] = None
        n = sum(_count(seg.text, vault) for seg in interaction.segments)
        return Decision(
            action="allow",
            control_id=self.id,
            reason=(
                f"{n} placeholder{'s' if n != 1 else ''} will be restored for the local user"
                if n
                else "Session vault active; response restored for the local user"
            ),
            severity=cfg.severity,
            owasp=list(cfg.owasp or self.owasp),
            meta={"rehydrate": enabled, "roles": list(p.roles), "placeholders": n},
        )

    # ------------------------------------------------------------------ tool.input
    def _tool_input(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        cfg: ControlConfig,
        p: Any,
        vault: Any,
        snap: Any,
    ) -> Decision | None:
        args = interaction.tool_args or {}
        force = bool(args.get("aegis_rehydrate")) if isinstance(args, dict) else False
        found = _placeholders(interaction, vault)
        dest = interaction.destination.dest_class
        tool = interaction.tool_name or "tool"
        if dest != "local":
            if force:
                return self._decision(
                    cfg,
                    "block",
                    f"Re-identification toward {dest} tool {tool} refused (aegis_rehydrate)",
                    found,
                    {"forced": True, "dest_class": dest},
                )
            if not found:
                return None
            n = sum(found.values())
            return self._decision(
                cfg,
                "allow",
                f"{n} placeholder{'s' if n != 1 else ''} kept for {dest} tool {tool}",
                found,
                {"passthrough": n, "rehydrate": False, "dest_class": dest},
            )
        if not found:
            return None
        n_all = sum(found.values())
        if "local_tools" not in p.rehydrate_to or tool_matches(tool, p.deny_tools):
            return self._decision(
                cfg,
                "allow",
                f"{n_all} placeholders kept for {tool} (rehydration denied)",
                found,
                {"passthrough": n_all, "rehydrate": False},
            )
        if tool_matches(tool, p.shell_tools) and self._shell_egress(interaction, p):
            return self._decision(
                cfg,
                "log",
                f"Placeholders kept for {tool}: command has network egress",
                found,
                {"passthrough": n_all, "rehydrate": False, "shell_egress": True},
            )
        allowed: list[str] | None = None
        if p.respect_matrix:
            matrix = effective_matrix(snap)
            ok_classes = {c for c, row in matrix.items() if row.get("local") in ("allow", "log")}
            from aegis.redaction import entities as E

            allowed = sorted(e for e in found if E.data_class(e) in ok_classes)
        restore = {e: c for e, c in found.items() if allowed is None or e in allowed}
        kept = {e: c for e, c in found.items() if e not in restore}
        if not restore:
            return self._decision(
                cfg,
                "log",
                f"Placeholders kept for local tool {tool} ({', '.join(kept)}: matrix local ≠ allow)",
                found,
                {"passthrough": n_all, "rehydrate": False, "kept": kept},
            )
        ctx.state["redaction.rehydrate_entities"] = allowed
        n = sum(restore.values())
        reason = f"Rehydrated {n} placeholder{'s' if n != 1 else ''} for local tool {tool}"
        if kept:
            reason += f"; kept {', '.join(kept)}"
        return self._decision(
            cfg,
            "log" if p.audit_tool_rehydration else "allow",
            reason,
            found,
            {
                "rehydrate": True,
                "rehydrate_entities": allowed,
                "roles": ["tool_args"],
                "restored": restore,
                "kept": kept,
            },
        )

    def _shell_egress(self, interaction: Interaction, p: Any) -> bool:
        rxs = _compile(list(p.deny_command_patterns))
        return any(rx.search(seg.text or "") for seg in interaction.segments for rx in rxs)

    def _decision(
        self, cfg: ControlConfig, action: str, reason: str, found: dict[str, int], meta: dict
    ) -> Decision:
        findings = [
            Finding(
                control_id=self.id,
                detector="vault.placeholder",
                category="pii",
                entity=e,
                severity=cfg.severity if action == "block" else "info",
                excerpt=f"[{e}_n]×{c}",
                meta={"op": "rehydrate" if meta.get("rehydrate") else "keep", "count": c},
            )
            for e, c in sorted(found.items())
        ]
        return Decision(
            action=action,  # type: ignore[arg-type]
            control_id=self.id,
            reason=reason,
            severity=cfg.severity,
            findings=findings,
            owasp=list(cfg.owasp or self.owasp),
            meta={"entities": dict(found), **meta},
        )


def _count(text: str, vault: Any) -> int:
    if not text or "[" not in text:
        return 0
    return sum(
        1
        for m in PLACEHOLDER_RE.finditer(text)
        if vault.resolve(canonical_key(m.group(1), m.group(2))) is not None
    )


def _placeholders(interaction: Interaction, vault: Any) -> dict[str, int]:
    """{entity: count} of this session's placeholders in the tool args (no values)."""
    if vault is None or len(vault) == 0:
        return {}
    out: dict[str, int] = {}
    texts = [seg.text or "" for seg in interaction.segments]
    if not texts and isinstance(interaction.tool_args, dict):
        texts = list(_leaves(interaction.tool_args))
    for text in texts:
        if "[" not in text:
            continue
        for m in PLACEHOLDER_RE.finditer(text):
            ent = vault.entity_of(canonical_key(m.group(1), m.group(2)))
            if ent:
                out[ent] = out.get(ent, 0) + 1
    return out


def _leaves(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [x for v in obj.values() for x in _leaves(v)]
    if isinstance(obj, list):
        return [x for v in obj for x in _leaves(v)]
    return []


CONTROLS = [Dlp08()]
