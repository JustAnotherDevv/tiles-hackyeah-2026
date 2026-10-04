"""DLP-02 - Secrets & credentials. Deterministic, priority 30, fail closed.

SECRET entities via the shared Tier-D scan; matrix SECRET row (local log / remote block /
third_party block). Role-aware: secrets inside tool results / documents (and on tool.output /
mcp.result hops) are tokenized (``[AWS_KEY_1]``) instead of killing a Claude Code turn.
AWS documentation keys are ``log`` (``allow_doc_examples``). ``action: redact`` turns blocking
into tokenization (live-edit lever).
"""

from __future__ import annotations

import time
from typing import ClassVar

from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Interaction, RequestContext
from aegis.redaction.policy import (
    Resolved,
    build_decision,
    build_findings,
    effective_matrix,
    load_params,
    resolve_span,
)

from ._common import all_context_spans, get_engine, snapshot, to_span_in

RESULT_SURFACES = {"tool.output", "mcp.result"}


class Dlp02(BaseControl):
    id: ClassVar[str] = "DLP-02"
    family: ClassVar[str] = "DLP"
    name: ClassVar[str] = "Secrets & credentials"
    kind: ClassVar[str] = "deterministic"  # type: ignore[assignment]
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={
            "prompt.user",
            "model.request",
            "tool.input",
            "mcp.init",
            "mcp.call",
            "egress.request",
            "a2a.message",
            "tool.output",
            "mcp.result",
        }
    )
    owasp: ClassVar[list[str]] = ["MCP01:2025", "LLM02:2026", "ASI03"]
    priority: ClassVar[int] = 30

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
        matrix = effective_matrix(snap, p.matrix_overrides)
        wanted = set(p.entities)
        result_hop = interaction.surface in RESULT_SURFACES
        resolved: list[Resolved] = []
        context: dict[int, list[tuple[int, int, str, str]]] = {}
        for i, seg in enumerate(interaction.segments):
            if not seg.redactable or not seg.text:
                continue
            spans = [to_span_in(i, h) for h in await eng.scan_async(seg.text, snap)]
            context[i] = all_context_spans(spans)
            role = "tool_result" if result_hop else seg.role
            for s in spans:
                if s.entity not in wanted:
                    continue
                resolved.append(
                    resolve_span(
                        s,
                        control_id=self.id,
                        cfg=cfg,
                        matrix=matrix,
                        dest_class=dest,
                        role=role,
                        params=p,
                    )
                )
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
        err = eng.scanner_error(snap)
        meta = {"scan_ms": round((time.perf_counter() - t0) * 1000, 3)}
        if err:
            meta["scanner_error"] = err
        return build_decision(
            self,
            cfg,
            resolved,
            findings,
            dest_class=dest,
            interaction=interaction,
            meta=meta,
            degraded=bool(err),
        )


CONTROLS = [Dlp02()]
