"""Control INJ-01 - normalization + deterministic injection signatures (docs/plan/05 INJ-04).

* trusted, block-eligible text (latest user turn) with score >= threshold -> ``cfg.action``;
* ASCII-smuggler tag characters in trusted latest-turn text -> ``tag_chars_action`` (block);
* hits inside hidden carriers (HTML comment / CSS-hidden / tag chars) in trusted text of any
  turn -> ``hidden_carrier_action`` (redact = quarantine span);
* untrusted text (tool.output, mcp.result, mcp.list, egress.response, tool_result segments)
  with score >= untrusted_threshold -> ``untrusted_action`` (redact = quarantine span);
  tag-character runs in untrusted text are always quarantined.

Quarantine = ``Finding(replacement="[AEGIS-QUARANTINE: ...]")`` the redactor applies verbatim
(Addendum A-42). Never raises: internal errors -> degraded allow + ERROR log.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from aegis.controls.injection import _common as _c
from aegis.controls.injection._common import (
    Inj01Params,
    effective_threshold,
    effective_untrusted_action,
    mask,
    parse_params,
    remember_intent,
)
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding, Interaction, RequestContext
from aegis.injection import explain
from aegis.injection.segments import ScanUnit, select_units, sentence_span
from aegis.injection.signatures import CARRIER_KINDS, ScanOptions, ScanResult, scan_text

log = logging.getLogger("aegis.controls.injection.inj01")

_FLAG_TAGS = re.compile(r"^[a-z0-9]{2,7}$")  # emoji subdivision flags (🏴 + tag letters)
_TO_THREAD_CHARS = 20_000


def scan_options(p: Inj01Params) -> ScanOptions:
    exclude = {f for f, on in (p.families or {}).items() if not on}
    if not p.include_extraction:
        exclude.add("extraction")
    extras = tuple(
        (e.id, e.pattern, e.family or "custom", float(e.weight), e.applies or "any")
        for e in p.extra_signatures
    )
    return ScanOptions(
        exclude_families=frozenset(exclude),
        disabled_signatures=frozenset(p.disabled_signatures),
        extra_signatures=extras,
        mention_discount=p.mention_discount,
        fuzzy=p.fuzzy,
        fuzzy_distance=p.fuzzy_distance,
        decode_depth=p.decode_depth,
        min_blob_len=p.min_blob_len,
        max_scan_chars=p.max_scan_chars,
    )


def _signal(rt: Any, h: Any, unit_text: str) -> dict[str, Any]:
    return {
        "stage": "signature",
        "id": h.sig_id,
        "family": h.family,
        "weight": h.weight,
        "view": h.view,
        "carrier": h.carrier,
        "mentioned": h.mentioned,
        "excerpt": mask(rt, h.matched or unit_text[h.start : h.end], 80),
    }


def _smuggled_runs(res: ScanResult) -> list[Any]:
    return [
        r
        for r in res.norm.hidden
        if r.kind == "tag_chars" and not _FLAG_TAGS.match((r.decoded or "").strip())
    ]


def _merge(spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    spans = sorted(spans)
    out: list[tuple[int, int, str]] = []
    for a, b, fam in spans:
        if out and a <= out[-1][1]:
            pa, pb, pf = out[-1]
            out[-1] = (pa, max(pb, b), pf)
        else:
            out.append((a, b, fam))
    return out


def quarantine_spans(
    res: ScanResult, text: str, *, hidden_only: bool = False
) -> list[tuple[int, int, str]]:
    """Localize the injected spans: hidden run > decoded-layer blob > sentence around the hit."""
    spans: list[tuple[int, int, str]] = []
    hits = sorted(res.hits, key=lambda h: -h.weight)
    for h in hits:
        if h.mentioned:
            continue
        if h.carrier in CARRIER_KINDS:
            run = next(
                (
                    r
                    for r in res.norm.hidden
                    if r.kind == h.carrier and r.start <= h.start and h.end <= r.end
                ),
                None,
            )
            if run is not None:
                spans.append((run.start, run.end, h.family))
                continue
        if hidden_only:
            continue
        if h.view.startswith("layer:"):
            spans.append((h.start, h.end, h.family))
            continue
        a, b = sentence_span(text, h.start, h.end)
        spans.append((a, b, h.family))
    for r in _smuggled_runs(res):
        spans.append((r.start, r.end, "tag_chars"))
    return _merge([(max(0, a), min(len(text), b), f) for a, b, f in spans if b > a])


class InjectionSignatures(BaseControl):
    id = "INJ-01"
    family = "INJ"
    name = "Normalization + deterministic injection signatures"
    kind = "deterministic"
    applies_to = AppliesTo(
        surfaces={
            "prompt.user",
            "model.request",
            "tool.output",
            "mcp.result",
            "mcp.list",
            "egress.response",
        }
    )
    owasp = ["LLM01:2026", "ASI01", "MCP06:2025"]
    priority = 40

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        try:
            p = parse_params(Inj01Params, cfg)
            units = select_units(
                interaction,
                scope=p.model_request_scope,
                strip_harness=p.strip_harness_blocks,
                ctx=ctx,
            )
            if not units:
                return None
            rt = _c.get_rt()
            if sum(len(u.text) for u in units) > _TO_THREAD_CHARS:
                return await asyncio.to_thread(
                    self._evaluate_sync, ctx, interaction, cfg, p, units, rt
                )
            return self._evaluate_sync(ctx, interaction, cfg, p, units, rt)
        except Exception:
            log.exception("INJ-01 internal error (degraded allow)")
            return Decision(
                action="allow",
                control_id=self.id,
                reason="INJ-01 internal error (degraded)",
                degraded=True,
            )

    def _evaluate_sync(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        cfg: ControlConfig,
        p: Inj01Params,
        units: list[ScanUnit],
        rt: Any,
    ) -> Decision | None:
        thr = effective_threshold(cfg, p.threshold)
        uthr = float(p.untrusted_threshold)
        opts = scan_options(p)
        surface = interaction.surface

        block_units: list[tuple[ScanUnit, ScanResult, str]] = []  # (unit, result, why)
        quarantine: list[tuple[ScanUnit, ScanResult, list[tuple[int, int, str]], str]] = []
        weak: list[tuple[ScanUnit, ScanResult]] = []
        max_score = 0.0
        seg_meta: list[dict[str, Any]] = []
        norm_meta: list[dict[str, Any]] = []
        signals: list[dict[str, Any]] = []
        mention = False
        latest_user = ""

        for u in units:
            try:
                res = scan_text(u.text, trust=u.trust, opts=opts)  # type: ignore[arg-type]
            except Exception:
                log.exception("INJ-01 unit scan failed (skipped)")
                continue
            if u.trusted and u.block_eligible:
                latest_user = u.text
            if not res.hits and not res.norm.hidden and not res.norm.layers:
                continue
            max_score = max(max_score, res.score)
            mention = mention or res.mention_discount
            smuggled = _smuggled_runs(res)
            if res.hits or smuggled:
                seg_meta.append(explain.segment_meta(u))
                norm_meta.append(explain.normalization_meta(res.norm))
                signals.extend(_signal(rt, h, u.text) for h in res.hits[:12])
            if u.trusted:
                visible = [h for h in res.hits if h.carrier not in CARRIER_KINDS]
                vis_score = _noisy_or(visible)
                if u.block_eligible and vis_score >= thr:
                    block_units.append((u, res, "signature"))
                    continue
                if u.block_eligible and smuggled:
                    block_units.append((u, res, "tag_chars"))
                    continue
                hidden_hits = [
                    h for h in res.hits if h.carrier in CARRIER_KINDS and not h.mentioned
                ]
                if (hidden_hits and res.score >= uthr) or smuggled:
                    spans = quarantine_spans(res, u.text, hidden_only=True)
                    if spans:
                        quarantine.append((u, res, spans, "hidden_carrier"))
                        continue
                if res.hits and p.log_weak:
                    weak.append((u, res))
            else:
                if res.score >= uthr or smuggled:
                    spans = (
                        quarantine_spans(res, u.text)
                        if res.score >= uthr
                        else quarantine_spans(res, u.text, hidden_only=True)
                    )
                    if spans:
                        quarantine.append((u, res, spans, "untrusted"))
                        continue
                if res.hits and p.log_weak:
                    weak.append((u, res))

        if latest_user and surface in ("prompt.user", "model.request"):
            try:
                remember_intent(rt, ctx, latest_user)
            except Exception:
                log.debug("remember_intent failed", exc_info=True)

        normalization = explain.merge_normalization(norm_meta)

        # ------------------------------------------------ block (trusted, latest turn)
        if block_units:
            findings: list[Finding] = []
            fams: list[str] = []
            top_view: str | None = None
            score = 0.0
            for u, res, why in block_units:
                score = max(score, 1.0 if why == "tag_chars" and res.score < thr else res.score)
                for h in sorted(res.hits, key=lambda h: -h.weight)[:8]:
                    if h.family not in fams:
                        fams.append(h.family)
                    top_view = top_view or h.view
                    findings.append(
                        Finding(
                            control_id=self.id,
                            detector=f"inj.sig.{h.sig_id}",
                            category="injection",
                            entity="PROMPT_INJECTION",
                            severity=cfg.severity,
                            score=h.weight,
                            segment_index=u.index,
                            start=h.start,
                            end=h.end,
                            excerpt=mask(rt, h.matched, 80),
                            meta={"family": h.family, "view": h.view, "carrier": h.carrier},
                        )
                    )
                if why == "tag_chars":
                    if "tag_chars" not in fams:
                        fams.append("tag_chars")
                    for r in _smuggled_runs(res):
                        findings.append(
                            Finding(
                                control_id=self.id,
                                detector="inj.tag_chars",
                                category="injection",
                                entity="PROMPT_INJECTION",
                                severity=cfg.severity,
                                score=1.0,
                                segment_index=u.index,
                                start=r.start,
                                end=r.end,
                                excerpt=mask(rt, r.decoded or "", 80),
                                meta={"family": "tag_chars"},
                            )
                        )
            sig_block = any(w == "signature" for *_, w in block_units)
            action = (
                cfg.action
                if sig_block
                else effective_untrusted_action(cfg.action, p.tag_chars_action)
            )
            if not sig_block:
                reason = (
                    f"Prompt injection (ASCII-smuggler tag characters) in "
                    f"{explain.SURFACE_LABEL.get(surface, surface)} — hidden payload decoded; "
                    f"score {explain.fmt(score)} ≥ {explain.fmt(thr)}"
                )
            else:
                reason = explain.reason_block(fams, surface, top_view, score, thr)
            d = self.decide(
                cfg,
                action=action,
                reason=reason,
                score=round(score, 4),
                findings=findings[:32],
                meta={
                    "inj": explain.meta(
                        trust="trusted",
                        outcome="block",
                        score=score,
                        threshold=thr,
                        segments=seg_meta,
                        normalization=normalization,
                        signals=signals,
                        mention_discount=mention,
                    )
                },
            )
            d.threshold = thr
            return d

        # ------------------------------------------------ quarantine (untrusted / hidden carriers)
        if quarantine:
            findings = []
            fams = []
            score = 0.0
            n_spans = 0
            any_untrusted = any(kind == "untrusted" for *_, kind in quarantine)
            for u, res, spans, kind in quarantine:
                score = max(score, res.score if res.score > 0 else 1.0)
                for a, b, fam in spans:
                    n_spans += 1
                    if fam not in fams:
                        fams.append(fam)
                    top = next((h for h in res.hits if h.family == fam), None)
                    findings.append(
                        Finding(
                            control_id=self.id,
                            detector=f"inj.sig.{top.sig_id}" if top else "inj.tag_chars",
                            category="injection",
                            entity="PROMPT_INJECTION",
                            severity=cfg.severity,
                            score=res.score if res.score > 0 else 1.0,
                            segment_index=u.index,
                            start=a,
                            end=b,
                            excerpt=mask(rt, u.text[a:b], 80),
                            replacement=p.replacement.format(family=fam)
                            if "{family}" in p.replacement
                            else p.replacement,
                            meta={
                                "family": fam,
                                "view": top.view if top else "hidden",
                                "kind": kind,
                            },
                        )
                    )
            configured = p.untrusted_action if any_untrusted else p.hidden_carrier_action
            action = effective_untrusted_action(cfg.action, configured)
            used_thr = uthr
            outcome = "quarantine" if action == "redact" else action
            reason = explain.reason_quarantine(n_spans, surface, fams, score, used_thr)
            if action == "block":
                reason = reason.replace("Quarantined", "Blocked:", 1)
            elif action in ("log", "allow"):
                reason = reason.replace("Quarantined", "Would quarantine", 1)
            d = self.decide(
                cfg,
                action=action,
                reason=reason,
                score=round(score, 4),
                findings=findings[:64],
                meta={
                    "inj": explain.meta(
                        trust="untrusted" if any_untrusted else "trusted",
                        outcome=outcome,
                        score=score,
                        threshold=used_thr,
                        segments=seg_meta,
                        normalization=normalization,
                        signals=signals,
                        quarantined_spans=n_spans,
                        mention_discount=mention,
                    )
                },
            )
            d.threshold = used_thr
            return d

        if weak:
            u, res = max(weak, key=lambda x: x[1].score)
            d = self.decide(
                cfg,
                action="log",
                score=res.score,
                reason=f"Weak injection signals ({', '.join(sorted(res.families))}); "
                f"score {explain.fmt(res.score)} < {explain.fmt(thr if u.trusted else uthr)}",
                meta={
                    "inj": explain.meta(
                        trust=u.trust,
                        outcome="log",
                        score=res.score,
                        threshold=thr if u.trusted else uthr,
                        segments=seg_meta,
                        normalization=normalization,
                        signals=signals,
                        mention_discount=mention,
                    )
                },
            )
            d.threshold = thr if u.trusted else uthr
            return d

        if max_score <= 0:
            return None
        d = self.decide(
            cfg,
            action="allow",
            reason=explain.reason_below(max_score, thr),
            score=round(max_score, 4),
            meta={
                "inj": explain.meta(
                    trust="trusted" if all(u.trusted for u in units) else "untrusted",
                    outcome="allow",
                    score=max_score,
                    threshold=thr,
                    segments=seg_meta,
                    normalization=normalization,
                    signals=signals,
                    mention_discount=mention,
                )
            },
        )
        d.threshold = thr
        return d


def _noisy_or(hits: list[Any]) -> float:
    fam: dict[str, float] = {}
    for h in hits:
        fam[h.family] = max(fam.get(h.family, 0.0), h.weight)
    prod = 1.0
    for w in fam.values():
        prod *= 1.0 - min(1.0, max(0.0, w))
    score = 1.0 - prod
    if score > 0 and any(h.carrier is not None for h in hits):
        score = min(1.0, score + 0.2)
    return round(score, 4)


CONTROLS = [InjectionSignatures()]
