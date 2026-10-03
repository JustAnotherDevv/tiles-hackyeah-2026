"""Control INJ-02 - semantic injection / jailbreak classifier cascade (docs/plan/05 INJ-05).

``rt.semantic.injection_score`` (Horizon PI-small) per scan unit, compared to the live-editable
``cfg.threshold`` (trusted) / ``params.untrusted_threshold``; scores in the review band are
escalated to ``rt.semantic.moderate`` (Qwen3Guard). When the semantic engine is degraded or
absent the heuristic score (engine heuristic + local signature score) is used and the decision
is marked ``degraded=True`` - the threshold demo still works.

Always returns a Decision carrying ``score`` + ``threshold`` (Addendum A-03), even when allowing.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from aegis.controls.injection import _common as _c
from aegis.controls.injection._common import (
    CLASSIFIER_REPLACEMENT,
    Inj02Params,
    effective_threshold,
    effective_untrusted_action,
    mask,
    parse_params,
)
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding, Interaction, RequestContext
from aegis.injection import explain
from aegis.injection.cascade import UnitScore, classify_unit
from aegis.injection.exemplars import exemplar_vote_fn
from aegis.injection.segments import select_units

log = logging.getLogger("aegis.controls.injection.inj02")


class InjectionClassifier(BaseControl):
    id = "INJ-02"
    family = "INJ"
    name = "Semantic injection / jailbreak classifier"
    kind = "semantic"
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
    owasp = ["LLM01:2026", "ASI01", "ASI06", "MCP06:2025"]
    priority = 60

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        try:
            return await self._evaluate(ctx, interaction, cfg)
        except Exception:
            log.exception("INJ-02 internal error (degraded allow)")
            return Decision(
                action="allow",
                control_id=self.id,
                reason="INJ-02 internal error (degraded)",
                degraded=True,
            )

    async def _evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        p = parse_params(Inj02Params, cfg)
        units = select_units(
            interaction, scope=p.model_request_scope, strip_harness=p.strip_harness_blocks, ctx=ctx
        )
        # block-type decisions only consider the latest user turn; untrusted units always
        units = [u for u in units if u.block_eligible or u.trust == "untrusted"]
        if not units:
            return None
        rt = _c.get_rt()
        thr = effective_threshold(cfg, p.threshold)
        uthr = float(p.untrusted_threshold)
        budget_s = max(0.05, cfg.timeout_ms * 0.8 / 1000)
        t0 = time.perf_counter()
        vote = exemplar_vote_fn(rt, p.exemplars) if p.exemplars.enabled else None
        results: list[UnitScore] = []
        for u in units[:16]:
            remaining = budget_s - (time.perf_counter() - t0)
            if remaining <= 0.01:
                break
            results.append(
                await classify_unit(
                    rt,
                    u,
                    params=p,
                    threshold=thr if u.trust == "trusted" else uthr,
                    budget_s=remaining,
                    exemplar_vote=vote,
                )
            )
        if not results:
            return None
        degraded = any(r.degraded for r in results)
        top = max(results, key=lambda r: r.score)
        signals: list[dict[str, Any]] = []
        for r in results:
            for st in r.stages:
                signals.append({**st, "segment": r.unit.index})
        seg_meta = [explain.segment_meta(r.unit) for r in results]
        review = float(p.review_threshold)

        trusted_act = [r for r in results if r.act and r.unit.trust == "trusted"]
        untrusted_act = [r for r in results if r.act and r.unit.trust == "untrusted"]

        if trusted_act:
            r = max(trusted_act, key=lambda x: x.score)
            action = cfg.action
            if r.review_outcome == "fallback":
                action = effective_untrusted_action(cfg.action, p.review_fallback.trusted)
            reason = self._reason(r, thr, review)
            d = self.decide(
                cfg,
                action=action,
                reason=reason,
                score=r.score,
                degraded=degraded,
                findings=[
                    Finding(
                        control_id=self.id,
                        detector=f"inj.classifier.{r.model}",
                        category="injection",
                        entity="PROMPT_INJECTION",
                        severity=cfg.severity,
                        score=r.score,
                        segment_index=r.unit.index,
                        excerpt=mask(rt, r.unit.text, 80),
                        meta={"band": r.band, "review": r.review_outcome},
                    )
                ],
                meta={
                    "inj": explain.meta(
                        trust="trusted",
                        outcome="block" if action == "block" else action,
                        score=r.score,
                        threshold=thr,
                        review_threshold=review,
                        segments=seg_meta,
                        signals=signals,
                        model=r.model,
                        degraded=degraded,
                    )
                },
            )
            d.threshold = thr
            return d

        if untrusted_act:
            findings: list[Finding] = []
            n = 0
            score = 0.0
            for r in untrusted_act:
                score = max(score, r.score)
                for a, b in r.spans:
                    n += 1
                    findings.append(
                        Finding(
                            control_id=self.id,
                            detector=f"inj.classifier.{r.model}",
                            category="injection",
                            entity="PROMPT_INJECTION",
                            severity=cfg.severity,
                            score=r.score,
                            segment_index=r.unit.index,
                            start=a,
                            end=b,
                            excerpt=mask(rt, r.unit.text[a:b], 80),
                            replacement=CLASSIFIER_REPLACEMENT.format(score=r.score, thr=uthr),
                            meta={"band": r.band, "review": r.review_outcome},
                        )
                    )
            configured = p.untrusted_action
            if all(r.review_outcome == "fallback" for r in untrusted_act):
                configured = p.review_fallback.untrusted
            action = effective_untrusted_action(cfg.action, configured)
            r = max(untrusted_act, key=lambda x: x.score)
            reason = (
                f"Quarantined {n} span{'s' if n != 1 else ''} in "
                f"{explain.SURFACE_LABEL.get(interaction.surface, interaction.surface)} — "
                + self._reason(r, uthr, review)
            )
            d = self.decide(
                cfg,
                action=action,
                reason=reason,
                score=score,
                degraded=degraded,
                findings=findings[:64],
                meta={
                    "inj": explain.meta(
                        trust="untrusted",
                        outcome="quarantine" if action == "redact" else action,
                        score=score,
                        threshold=uthr,
                        review_threshold=review,
                        segments=seg_meta,
                        signals=signals,
                        quarantined_spans=n,
                        model=r.model,
                        degraded=degraded,
                    )
                },
            )
            d.threshold = uthr
            return d

        # allow - still explain score vs threshold (A-03)
        used_thr = thr if top.unit.trust == "trusted" else uthr
        cleared = top.review_outcome == "cleared"
        action = "log" if (cleared and p.log_review) else "allow"
        if cleared:
            reason = (
                f"Injection classifier {top.model} {top.score:.2f} in review band → guard cleared; "
                f"score {top.score:.2f} < {used_thr:.2f}"
            )
        elif top.review_outcome == "fallback":
            reason = (
                f"Injection classifier {top.model} {top.score:.2f} in review band → guard unavailable, "
                f"fallback allow; score {top.score:.2f} < {used_thr:.2f}"
            )
        else:
            reason = f"Injection classifier {top.model} {top.score:.2f} < {used_thr:.2f}"
        d = self.decide(
            cfg,
            action=action,
            reason=reason,
            score=top.score,
            degraded=degraded,
            meta={
                "inj": explain.meta(
                    trust=top.unit.trust,
                    outcome="review_cleared" if cleared else ("degraded" if degraded else "allow"),
                    score=top.score,
                    threshold=used_thr,
                    review_threshold=review,
                    segments=seg_meta,
                    signals=signals,
                    model=top.model,
                    degraded=degraded,
                )
            },
        )
        d.threshold = used_thr
        return d

    @staticmethod
    def _reason(r: UnitScore, thr: float, review: float) -> str:
        deg = " (degraded: heuristic)" if r.degraded else ""
        if r.review_outcome == "confirmed":
            g = next((s for s in r.stages if s.get("stage") == "guard"), {})
            cats = "/".join(g.get("categories") or [])
            lbl = g.get("label") or "unsafe"
            return (
                f"Injection classifier {r.model} {r.score:.2f} in review band → guard {lbl}"
                f"{'/' + cats if cats else ''}; score {r.score:.2f} ≥ {review:.2f} [confirmed]{deg}"
            )
        if r.review_outcome == "fallback":
            return (
                f"Injection classifier {r.model} {r.score:.2f} in review band → guard unavailable "
                f"(fallback); score {r.score:.2f} ≥ {review:.2f}{deg}"
            )
        return f"Injection classifier {r.model} score {r.score:.2f} ≥ {thr:.2f}{deg}"


CONTROLS = [InjectionClassifier()]
