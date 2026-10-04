"""INJ-03 Content safety + topic adherence % (owner: semantic-models).

Two legs, run concurrently on the latest user turn (requests) or the assistant text (responses):

1. **Safety** - ``rt.semantic.moderate()`` (Qwen3Guard ``aegis-guard``; heuristic fallback).
   ``score >= cfg.threshold`` (default 0.80; Unsafe = 1.0) -> ``category_actions[category]``
   (max precedence; unknown -> ``cfg.action``). Controversial below the threshold ->
   ``controversial_action`` (default ``log``).
2. **Topic adherence** (requests only) - similarity between the request and the agent's declared
   purpose (``params.adherence.purposes``: agent-id glob -> text), calibrated per backend into a
   percentage. ``adherence_pct < cfg.adherence_pct`` (default 50) -> ``adherence.on_low``
   (``log`` in balanced, ``block`` in strict / paranoid).

Degraded model answers follow ``aegis.semantic.shared.degraded_disposition`` (fail_mode).
Decision meta: model, model_ms, safety, categories, adherence_pct, purpose_agent, fallback.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from aegis.controls.resilience._failsafe import is_fail_closed
from aegis.controls.semantic import _common as c
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding, Interaction, RequestContext, ScoreResult
from aegis.semantic.shared import degraded_disposition, fallback_code

_CLAUSE = re.compile(r"[.:;,]")


def _finance_benign(text: str, cal: Any) -> bool:
    try:
        from aegis.injection.calibration import finance_benign

        return finance_benign(
            text,
            max_chars=int(cal.max_chars),
            domain_terms=tuple(cal.domain_terms),
            harm_cues=tuple(cal.harm_cues),
        )
    except Exception:
        return False


def _slug(cat: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", cat.lower()).strip("_") or "unsafe"


class ContentSafety(BaseControl):
    id = "INJ-03"
    family = "INJ"
    name = "Content safety & topic adherence"
    kind = "semantic"
    applies_to = AppliesTo(surfaces={"prompt.user", "model.request", "model.response"})
    owasp = ["LLM07:2026", "ASI10", "ASI01"]

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _params(cfg: ControlConfig) -> c.Inj03Params:
        try:
            p = c.Inj03Params.model_validate(cfg.params or {})
        except Exception:
            c.log.warning("invalid params control=INJ-03; using defaults")
            p = c.Inj03Params()
        c.warn_unknown("INJ-03", p)
        return p

    @staticmethod
    def _purpose(ctx: RequestContext, p: c.Inj03Params) -> tuple[str | None, str | None]:
        agent = getattr(ctx.identity, "agent_id", None)
        if agent:
            for pattern, text in (p.adherence.purposes or {}).items():
                if text and c.glob_match(pattern, agent):
                    return pattern, text
        if p.purpose and agent and agent != "selftest":
            return "*", p.purpose
        return None, None

    @staticmethod
    def _adherence_pct(sim: ScoreResult, p: c.Inj03Params) -> float:
        cal = p.adherence.calibration or {}
        lo, hi = (cal.get(sim.model) or c.DEFAULT_CALIBRATION.get(sim.model) or [0.10, 0.46])[:2]
        if hi <= lo:
            hi = lo + 1e-6
        return round(100.0 * max(0.0, min(1.0, (sim.score - lo) / (hi - lo))), 1)

    # ------------------------------------------------------------ evaluate
    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        p = self._params(cfg)
        profile = c.profile_of(ctx)
        surface = interaction.surface
        is_response = surface == "model.response"
        if is_response:
            if not c.resolve(p.check_output, profile, True):
                return None
            text = c.assistant_text(interaction)
            prompt = ctx.state.get("inj03.user_text")
        else:
            if not c.resolve(p.check_input, profile, True):
                return None
            text = c.user_text(interaction, latest_only=surface == "model.request")
            prompt = None
            if text:
                ctx.state["inj03.user_text"] = text[: p.max_chars]  # memory only
        if not text:
            return None
        text = (
            text[: p.max_chars]
            if len(text) <= p.max_chars
            else (text[: p.max_chars // 2] + "\n" + text[-p.max_chars // 2 :])
        )
        timeout_s = max(0.05, 0.8 * (cfg.timeout_ms or 600) / 1000.0)

        # ---- legs
        purpose_agent, purpose = (None, None) if is_response else self._purpose(ctx, p)
        adh_on = (
            purpose is not None
            and bool(c.resolve(p.adherence.enabled, profile, True))
            and len(text) >= p.adherence.min_chars
        )
        t0 = time.perf_counter()

        async def safety() -> ScoreResult | None:
            r = await c.call_engine(
                "moderate",
                text,
                mode="response" if is_response else "prompt",
                prompt=prompt,
                timeout_s=timeout_s,
            )
            ctx.timings["sem.guard"] = round((time.perf_counter() - t0) * 1e3, 2)
            return r

        async def adherence() -> ScoreResult | None:
            if not adh_on:
                return None
            refs = [s.strip() for s in _CLAUSE.split(purpose or "") if len(s.strip()) > 2]
            refs.append(purpose or "")
            eng = c.engine()
            if hasattr(eng, "similarity_detail"):
                r = await c.call_engine("similarity_detail", text, refs, timeout_s=timeout_s)
            else:
                sim = await eng.similarity(text, refs)
                r = ScoreResult(score=float(sim or 0.0), model="heuristic")
            ctx.timings["sem.embed"] = round((time.perf_counter() - t0) * 1e3, 2)
            return r

        res = await asyncio.gather(safety(), adherence(), return_exceptions=True)
        mod = res[0] if isinstance(res[0], ScoreResult) else None
        sim = res[1] if isinstance(res[1], ScoreResult) else None
        if mod is None and isinstance(res[0], BaseException):
            mod = ScoreResult(score=0.0, degraded=True, reason="fallback:error", model="heuristic")

        candidates: list[Decision] = []
        meta: dict[str, Any] = {"profile": profile, "surface": surface}
        for leg, r in (("safety", res[0]), ("adherence", res[1])):
            if isinstance(r, BaseException):
                c.log.warning("INJ-03 %s leg failed: %s", leg, type(r).__name__)
        if isinstance(res[1], BaseException) and is_fail_closed(cfg):
            # ASI08: the adherence leg used to vanish silently on error; closed -> block.
            candidates.append(
                self.decide(
                    cfg,
                    action="block",
                    degraded=True,
                    reason="INJ-03 adherence check failed (fail-closed)",
                    meta={
                        "internal_error": True,
                        "fail_mode": "closed",
                        "error": type(res[1]).__name__,
                    },
                )
            )
        degraded = False
        fallbacks: list[str] = []
        excerpt = c.mask(text, 120)
        threshold = cfg.threshold if cfg.threshold is not None else 0.8

        # ---- safety leg
        if mod is not None:
            degraded |= bool(mod.degraded)
            fb = fallback_code(mod)
            if fb:
                fallbacks.append(fb)
            meta.update(
                model=mod.model,
                model_ms=round(mod.latency_ms, 1),
                safety=mod.label or None,
                safety_score=mod.score,
                categories=list(mod.categories),
            )
            disp = degraded_disposition(mod, cfg.fail_mode)
            if disp == "block":
                candidates.append(
                    self.decide(
                        cfg,
                        action="block",
                        score=mod.score,
                        degraded=True,
                        reason=f"INJ-03 model unavailable (fail-closed: {fb})",
                    )
                )
            elif disp == "use":
                cats = list(mod.categories)
                if mod.score >= threshold:
                    acts = [c.valid_action(p.category_actions.get(k), cfg.action) for k in cats]
                    action = c.max_action(acts) if acts else cfg.action
                    label = mod.label or "Unsafe"
                    reason = f"{label}: {', '.join(cats) or 'unsafe content'} ({mod.model} {mod.score:.2f} ≥ {threshold:.2f})"
                    cal = p.calibration
                    if (
                        cal.enabled
                        and not is_response
                        and cats
                        and set(cats) <= set(cal.categories)
                        and _finance_benign(text, cal)
                    ):
                        action = c.valid_action(cal.action, "log")
                        reason += " → finance-domain calibration: no financial-crime cue, logged"
                        meta["calibration"] = "finance_domain"
                    candidates.append(
                        self.decide(
                            cfg,
                            action=action,
                            score=mod.score,
                            reason=reason,
                            findings=[
                                Finding(
                                    control_id=self.id,
                                    detector=f"sem.guard.{_slug(k)}",
                                    category="content",
                                    severity=cfg.severity,
                                    score=mod.score,
                                    excerpt=excerpt,
                                    meta={"category": k, "model": mod.model},
                                )
                                for k in (cats or ["unsafe"])
                            ],
                        )
                    )
                elif mod.label == "Controversial" or mod.score >= 0.5:
                    action = c.valid_action(p.controversial_action, "log")
                    candidates.append(
                        self.decide(
                            cfg,
                            action=action,
                            score=mod.score,
                            reason=f"Controversial: {', '.join(cats) or 'borderline'} ({mod.model} {mod.score:.2f} < {threshold:.2f})",
                            findings=[
                                Finding(
                                    control_id=self.id,
                                    detector="sem.guard.controversial",
                                    category="content",
                                    severity="low",
                                    score=mod.score,
                                    excerpt=excerpt,
                                    meta={"categories": cats, "model": mod.model},
                                )
                            ],
                        )
                    )

        # ---- adherence leg
        if sim is not None:
            degraded |= bool(sim.degraded)
            fb = fallback_code(sim)
            if fb:
                fallbacks.append(fb)
            pct = self._adherence_pct(sim, p)
            minimum = cfg.adherence_pct if cfg.adherence_pct is not None else 50.0
            meta.update(
                adherence_pct=pct,
                adherence_min=minimum,
                purpose_agent=purpose_agent,
                similarity=sim.score,
                embed_model=sim.model,
            )
            # The org-wide fallback purpose ("*") is broad; hashed heuristic embeddings are too
            # coarse to judge it, so only a real embedding model may flag it (avoids log noise).
            weak = purpose_agent == "*" and bool(sim.degraded)
            if weak:
                meta["adherence_note"] = "org-wide purpose not scored by the heuristic"
            if pct < minimum and not weak and degraded_disposition(sim, cfg.fail_mode) != "allow":
                on_low = p.off_topic_action or c.resolve(p.adherence.on_low, profile, "log")
                action = c.valid_action(on_low, "log")
                d = self.decide(
                    cfg,
                    action=action,
                    score=round(pct / 100.0, 3),
                    reason=f"topic adherence {pct:.0f}% < {minimum:.0f}% (purpose of {purpose_agent})",
                    findings=[
                        Finding(
                            control_id=self.id,
                            detector="sem.adherence",
                            category="content",
                            severity="low",
                            score=round(pct / 100.0, 3),
                            excerpt=excerpt,
                            meta={"adherence_pct": pct, "purpose_agent": purpose_agent},
                        )
                    ],
                )
                d.threshold = round(minimum / 100.0, 3)
                candidates.append(d)

        if fallbacks:
            meta["fallback"] = sorted(set(fallbacks))
        if not candidates:
            safety_note = (
                f"{meta.get('safety') or 'Safe'} ({meta.get('model', 'n/a')})"
                if mod is not None
                else "n/a"
            )
            adh = f", adherence {meta['adherence_pct']:.0f}%" if "adherence_pct" in meta else ""
            return Decision(
                action="allow",
                control_id=self.id,
                reason=f"content ok: {safety_note}{adh}",
                score=mod.score if mod is not None else None,
                threshold=threshold,
                severity=cfg.severity,
                degraded=degraded,
                owasp=list(cfg.owasp or self.owasp),
                meta=meta,
            )
        for d in candidates:
            if d.threshold is None:
                d.threshold = threshold
        best = max(candidates, key=lambda d: c.ACTION_PRECEDENCE.get(d.action, 0))
        best.degraded = best.degraded or degraded
        best.meta = {**meta, **best.meta}
        best.findings = [f for d in candidates for f in d.findings]
        return best


CONTROLS = [ContentSafety()]
