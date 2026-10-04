"""DLP-07 - Multilingual NER sensitive data (incl. Polish). Semantic, priority 60, fail open.

PERSON / ADDRESS / HEALTH / DOB on user-authored and tool-result segments via the single NER
instance (``rt.semantic.ner``, bardsai eu-pii-anonimization-multilang INT8 ONNX) merged with
deterministic heuristics; NER off/unavailable/timeout -> heuristics only and ``degraded=True``
(fail_mode closed + NER timeout/error -> degraded block, ASI08).
Spans already covered by Tier-D detectors (DLP-01/02) are dropped. Same matrix semantics as
DLP-01 (neutral action ``redact``); ``threshold`` (default 0.6) is the score floor - heuristic
hits score 0.65-0.75, so raising it to 0.8 turns names into ``log`` while PESEL/PAN stay
redacted by DLP-01.
"""

from __future__ import annotations

import time
from typing import ClassVar

from aegis.controls.resilience._failsafe import internal_error_decision, is_fail_closed
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Interaction, RequestContext
from aegis.redaction import entities as E
from aegis.redaction.ner import ner_spans, ner_status
from aegis.redaction.policy import (
    Resolved,
    SpanIn,
    build_decision,
    build_findings,
    effective_matrix,
    load_params,
    resolve_span,
)

from ._common import all_context_spans, blank_code, get_engine, overlaps, snapshot, to_span_in

RESULT_SURFACES = {"tool.output", "mcp.result"}


class Dlp07(BaseControl):
    id: ClassVar[str] = "DLP-07"
    family: ClassVar[str] = "DLP"
    name: ClassVar[str] = "Multilingual NER sensitive data (incl. Polish)"
    kind: ClassVar[str] = "semantic"  # type: ignore[assignment]
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"prompt.user", "model.request", "tool.output", "mcp.result"}
    )
    owasp: ClassVar[list[str]] = ["LLM02:2026", "MCP10:2025"]
    priority: ClassVar[int] = 60

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
        roles = set(p.roles)
        eligible = [
            i
            for i, s in enumerate(interaction.segments)
            if s.redactable and s.text and (s.role in roles or result_hop)
        ]
        eligible = eligible[-max(1, int(p.max_segments)) :]  # newest first (keep the tail)
        timeout_s = max(0.05, (cfg.timeout_ms or 400) / 1000 * 0.9)
        resolved: list[Resolved] = []
        context: dict[int, list[tuple[int, int, str, str]]] = {}
        degraded = False
        for i in eligible:
            seg = interaction.segments[i]
            text = seg.text[: int(p.max_chars)]
            scan_text = blank_code(text) if p.skip_code else text
            tier_d = [to_span_in(i, h) for h in await eng.scan_async(seg.text, snap)]
            context[i] = all_context_spans(tier_d)
            spans, deg = await ner_spans(
                eng,
                scan_text,
                entities=wanted,
                timeout_s=timeout_s,
                heuristic=bool(p.heuristic_fallback),
            )
            degraded = degraded or deg
            for sp in spans:
                if sp.entity not in wanted:
                    continue
                s = SpanIn(
                    i,
                    sp.start,
                    sp.end,
                    sp.entity,
                    E.data_class(sp.entity),
                    sp.detector_id,
                    float(sp.score),
                    "pii",
                )
                if overlaps(s, tier_d):
                    continue
                context[i].append((s.start, s.end, s.entity, ""))
                resolved.append(
                    resolve_span(
                        s,
                        control_id=self.id,
                        cfg=cfg,
                        matrix=matrix,
                        dest_class=dest,
                        role=seg.role,
                        params=p,
                        min_score=float(p.label_min_scores.get(s.entity, 0.0)),
                    )
                )
        if degraded and is_fail_closed(cfg):
            # ASI08: NER *failure* (timeout / model error - not "off" or "not loaded") under
            # fail_mode closed must not silently degrade to heuristics-only.
            why = str((ner_status(eng) or {}).get("reason") or "")
            if why == "timeout" or why.startswith("error"):
                return internal_error_decision(self.id, cfg, f"NER {why}", what="NER failed")
        if not resolved:
            return None
        findings = build_findings(
            resolved,
            control_id=self.id,
            cfg=cfg,
            interaction=interaction,
            dest_class=dest,
            tier="S" if not degraded else "H",
            context_spans=context,
        )
        meta = {
            "ner": "heuristic" if degraded else "eu-pii-ner",
            "ner_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
        d = build_decision(
            self,
            cfg,
            resolved,
            findings,
            dest_class=dest,
            interaction=interaction,
            meta=meta,
            degraded=degraded,
        )
        if d is not None and degraded and d.reason:
            d.reason = d.reason + " [heuristic NER]"
        return d


CONTROLS = [Dlp07()]
