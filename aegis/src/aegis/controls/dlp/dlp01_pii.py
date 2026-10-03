"""DLP-01 - PII/PCI/Polish-ID tokenization (destination matrix). Deterministic, priority 40.

Per redactable segment: one cached Tier-D scan + exact matches of values already in the
session vault (multi-turn safety) -> ``destinations.matrix[class][dest]`` with the control
action relative to its neutral action (``redact``) -> findings with offsets for the spans to
transform (vault placeholders ``[PESEL_1]``; CVV/track dropped as ``[REDACTED:CVV]``).
Recipient args of send tools are routing data governed by ACT-03 [SF-04]: observed, never
redacted or blocked here.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Interaction, RequestContext
from aegis.redaction import entities as E
from aegis.redaction.policy import (
    Resolved,
    SpanIn,
    build_decision,
    build_findings,
    effective_matrix,
    load_params,
    resolve_span,
)

from ._common import (
    all_context_spans,
    arg_name,
    get_engine,
    overlaps,
    routing_args,
    snapshot,
    to_span_in,
)

FRAGMENT_ROLES = ("user", "tool_args")
FRAGMENT_MAX_CHARS = 20_000


class Dlp01(BaseControl):
    id: ClassVar[str] = "DLP-01"
    family: ClassVar[str] = "DLP"
    name: ClassVar[str] = "PII/PCI/Polish-ID tokenization (destination matrix)"
    kind: ClassVar[str] = "deterministic"  # type: ignore[assignment]
    applies_to: ClassVar[AppliesTo] = AppliesTo(
        surfaces={"prompt.user", "model.request", "tool.input", "mcp.call", "egress.request"}
    )
    owasp: ClassVar[list[str]] = ["LLM02:2026", "ASI03", "MCP10:2025"]
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
        matrix = effective_matrix(snap, p.matrix_overrides)
        wanted = set(p.entities)
        routing = routing_args(interaction, p.routing_args)
        hits0 = eng.cache_hits
        resolved: list[Resolved] = []
        context: dict[int, list[tuple[int, int, str, str]]] = {}
        per_seg: dict[int, list[Resolved]] = {}
        for i, seg in enumerate(interaction.segments):
            if not seg.redactable or not seg.text:
                continue
            hits = await eng.scan_async(seg.text, snap)
            spans = [to_span_in(i, h) for h in hits]
            context[i] = all_context_spans(spans)
            mine = [s for s in spans if s.entity in wanted]
            if p.known_values and dest != "local":
                for k in eng.known_value_spans(ctx, seg.text):
                    ks = SpanIn(
                        i,
                        k.start,
                        k.end,
                        k.entity,
                        E.data_class(k.entity),
                        "vault.known_value",
                        1.0,
                        E.category(k.entity),
                        meta={"known_value": True},
                    )
                    if not overlaps(ks, mine):
                        mine.append(ks)
                        context[i].append((k.start, k.end, k.entity, ""))
            is_routing = seg.role == "tool_args" and arg_name(seg.path) in routing
            for s in mine:
                if is_routing:
                    s.meta["routing"] = True
                    r = Resolved(
                        s,
                        "allow",
                        "routing",
                        f"{s.data_class}.{dest}",
                        "recipient = routing data (ACT-03)",
                    )
                else:
                    r = resolve_span(
                        s,
                        control_id=self.id,
                        cfg=cfg,
                        matrix=matrix,
                        dest_class=dest,
                        role=seg.role,
                        params=p,
                        min_score=float(p.min_scores.get(s.entity, 0.0)),
                    )
                resolved.append(r)
                per_seg.setdefault(i, []).append(r)
        if p.cross_segment:
            resolved += self._fragments(eng, interaction, resolved, cfg, matrix, dest, p, context)
        if not resolved:
            return None
        extra_block = self._request_rules(interaction, per_seg, p)
        findings = build_findings(
            resolved,
            control_id=self.id,
            cfg=cfg,
            interaction=interaction,
            dest_class=dest,
            context_spans=context,
        )
        meta: dict[str, Any] = {
            "cache_hits": eng.cache_hits - hits0,
            "scan_ms": round((time.perf_counter() - t0) * 1000, 3),
        }
        err = eng.scanner_error(snap)
        if err:
            meta["scanner_error"] = err
        return build_decision(
            self,
            cfg,
            resolved,
            findings,
            dest_class=dest,
            interaction=interaction,
            extra_block=extra_block,
            meta=meta,
            degraded=bool(err),
        )

    # ------------------------------------------------------------------ request-level rules
    @staticmethod
    def _request_rules(
        interaction: Interaction, per_seg: dict[int, list[Resolved]], p: Any
    ) -> str | None:
        transformed = [
            r for rs in per_seg.values() for r in rs if r.op in ("tokenize", "drop", "mask")
        ]
        if p.max_entities_per_request and len(transformed) > p.max_entities_per_request:
            return (
                f"Bulk sensitive data: {len(transformed)} values in one request "
                f"(max_entities_per_request {p.max_entities_per_request})"
            )
        ratio = p.redaction_ratio_block
        if not ratio:
            return None
        for i, rs in per_seg.items():
            seg = interaction.segments[i]
            if seg.role not in p.ratio_roles or len(seg.text) < p.ratio_min_chars:
                continue
            chars = sum(
                r.span.end - r.span.start for r in rs if r.op in ("tokenize", "drop", "mask")
            )
            share = chars / max(1, len(seg.text))
            if share > ratio:
                return (
                    f"Bulk sensitive data: {share:.0%} of a {seg.role} segment would be "
                    f"redacted (redaction_ratio_block {ratio:.0%})"
                )
        return None

    # ------------------------------------------------------------------ RED-15 fragments
    def _fragments(
        self,
        eng: Any,
        interaction: Interaction,
        resolved: list[Resolved],
        cfg: ControlConfig,
        matrix: dict[str, dict[str, str]],
        dest: str,
        p: Any,
        context: dict[int, list[tuple[int, int, str, str]]],
    ) -> list[Resolved]:
        """PAN / IBAN split across user-authored segments -> irreversible marker per fragment."""
        idx = [
            i
            for i, s in enumerate(interaction.segments)
            if s.redactable and s.role in FRAGMENT_ROLES and any(c.isdigit() for c in s.text)
        ]
        if len(idx) < 2 or sum(len(interaction.segments[i].text) for i in idx) > FRAGMENT_MAX_CHARS:
            return []
        snap_scanner = eng.scanner_for(None)
        try:
            per = snap_scanner.detect_segments([interaction.segments[i].text for i in idx])
        except Exception:
            return []
        out: list[Resolved] = []
        for k, hits in enumerate(per):
            i = idx[k]
            existing = [r.span for r in resolved if r.span.segment_index == i]
            for h in hits:
                if not h.meta.get("fragment") or h.entity not in ("PAN", "IBAN"):
                    continue
                s = to_span_in(i, h)
                if overlaps(s, existing):
                    continue
                r = resolve_span(
                    s,
                    control_id=self.id,
                    cfg=cfg,
                    matrix=matrix,
                    dest_class=dest,
                    role=interaction.segments[i].role,
                    params=p,
                )
                if r.op == "tokenize":
                    r.op, r.replacement = "irreversible", f"[REDACTED:{s.entity}]"
                out.append(r)
                context.setdefault(i, []).append((s.start, s.end, s.entity, s.canonical))
        return out


CONTROLS = [Dlp01()]
