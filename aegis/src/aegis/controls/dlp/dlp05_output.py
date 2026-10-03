"""DLP-05 - Output & tool-result leak detection (+ canary). Deterministic, priority 40.

Runs on placeholder-bearing text BEFORE rehydration:
* canary tokens (exact or after anti-evasion normalisation) -> ``block``;
* ``model.response``: sensitive values the model emitted are masked irreversibly
  (``[REDACTED:AWS_KEY]``, PAN -> ``411111******1111``) - model output is never vaulted;
  ``meta.reidentified`` marks values the session vault already holds;
* ``tool.output`` / ``mcp.result`` / ``egress.response``: reversible tokenization per the
  destination matrix (the local user still gets real values back via DLP-08).
DLP-05 never blocks on data values (only canaries): blocking cells are capped at ``redact``.
"""

from __future__ import annotations

import time
from typing import ClassVar

from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding, Interaction, RequestContext
from aegis.redaction import entities as E
from aegis.redaction.normalize import normalize
from aegis.redaction.placeholders import irreversible
from aegis.redaction.policy import (
    Resolved,
    build_decision,
    build_findings,
    effective_matrix,
    load_params,
    min_action,
    resolve_span,
)
from aegis.redaction.preview import pan_mask

from ._common import all_context_spans, get_engine, snapshot, to_span_in


class Dlp05(BaseControl):
    id: ClassVar[str] = "DLP-05"
    family: ClassVar[str] = "DLP"
    name: ClassVar[str] = "Output & tool-result leak detection (+ canary)"
    kind: ClassVar[str] = "deterministic"  # type: ignore[assignment]
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"model.response", "tool.output", "mcp.result", "egress.response"}
    )
    owasp: ClassVar[list[str]] = ["LLM02:2026", "LLM05:2026", "MCP10:2025"]
    priority: ClassVar[int] = 40

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        if not interaction.segments:
            return None
        t0 = time.perf_counter()
        eng = get_engine()
        snap = snapshot(ctx)
        p = load_params(self.id, cfg, snap)
        dest = interaction.destination.dest_class
        canary = self._canary(interaction, p.canaries, cfg)
        if canary is not None:
            return canary
        matrix = effective_matrix(snap, p.matrix_overrides)
        wanted = set(p.entities) if p.entities else set(E.DLP01_DEFAULT) | set(E.DLP02_DEFAULT)
        model_out = interaction.surface == "model.response"
        irreversible_out = model_out and p.response_replacement == "irreversible"
        vault = eng.vaults.peek(ctx.session_id) if p.detect_reidentification else None
        resolved: list[Resolved] = []
        context: dict[int, list[tuple[int, int, str, str]]] = {}
        for i, seg in enumerate(interaction.segments):
            if not seg.redactable or not seg.text:
                continue
            spans = [to_span_in(i, h) for h in await eng.scan_async(seg.text, snap)]
            context[i] = all_context_spans(spans)
            for s in spans:
                if s.entity not in wanted:
                    continue
                if (
                    vault is not None
                    and s.canonical
                    and vault.contains_value(s.entity, s.canonical)
                ):
                    s.meta["reidentified"] = True
                r = resolve_span(
                    s,
                    control_id=self.id,
                    cfg=cfg,
                    matrix=matrix,
                    dest_class=dest,
                    role=seg.role,
                    params=p,
                    irreversible_output=irreversible_out,
                )
                if r.action in ("block", "require_approval"):  # never block on data values
                    r = self._cap(r, irreversible_out)
                resolved.append(r)
        if not resolved:
            return None
        findings = build_findings(
            resolved,
            control_id=self.id,
            cfg=cfg,
            interaction=interaction,
            dest_class=dest,
            context_spans=context,
        )
        verb = "Masked" if irreversible_out else "Tokenized"
        meta = {
            "scan_ms": round((time.perf_counter() - t0) * 1000, 3),
            "surface": interaction.surface,
        }
        reid = sum(1 for r in resolved if r.span.meta.get("reidentified"))
        if reid:
            meta["reidentified"] = reid
        return build_decision(
            self,
            cfg,
            resolved,
            findings,
            dest_class=dest,
            interaction=interaction,
            meta=meta,
            verb=verb,
        )

    @staticmethod
    def _cap(r: Resolved, irreversible_out: bool) -> Resolved:
        ent = r.span.entity
        r.action = min_action(r.action, "redact")
        if ent in E.IRREVERSIBLE:
            r.op, r.replacement = "drop", irreversible(ent)
        elif irreversible_out:
            r.op = "irreversible"
            r.replacement = (
                pan_mask(r.span.canonical)
                if ent == "PAN" and r.span.canonical
                else irreversible(ent)
            )
        else:
            r.op, r.replacement = "tokenize", None
        r.reason = r.reason or "masked instead of blocking a result"
        return r

    def _canary(
        self, interaction: Interaction, canaries: list[str], cfg: ControlConfig
    ) -> Decision | None:
        tokens = [c for c in canaries or [] if c]
        if not tokens:
            return None
        for i, seg in enumerate(interaction.segments):
            text = seg.text or ""
            hay = [text]
            if not text.isascii():
                hay.append(normalize(text).text)
            for c in tokens:
                if any(c in h or c.lower() in h.lower() for h in hay):
                    return Decision(
                        action="block",
                        control_id=self.id,
                        reason="Canary token leaked: hidden instructions are being exfiltrated",
                        score=1.0,
                        severity="critical",
                        findings=[
                            Finding(
                                control_id=self.id,
                                detector="canary.token",
                                category="exfil",
                                severity="critical",
                                segment_index=i,
                                excerpt="[CANARY]",
                                meta={"canary_fp": c[:6] + "…"},
                            )
                        ],
                        owasp=list(cfg.owasp or self.owasp),
                        meta={"canary": True, "surface": interaction.surface},
                    )
        return None


CONTROLS = [Dlp05()]
