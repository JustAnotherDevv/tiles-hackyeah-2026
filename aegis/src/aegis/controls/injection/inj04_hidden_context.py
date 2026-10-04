"""Control INJ-04 - hidden-context exposure (docs/plan/05 INJ-06, INJ-09, INJ-10).

Request side (``prompt.user``, ``model.request`` latest user turn):
  * extraction-attempt signatures (family ``extraction``) with score >= extraction_threshold
    -> ``cfg.action`` (block);
  * exemplar paraphrase leg (embeddings): label ``extraction`` hit AND a weak extraction cue
    -> block (skipped when embeddings are unavailable);
  * hashed 5-gram shingles of role=system segments are recorded in ``ctx.state`` (+ session).
Response side (``model.response``):
  * canary (plain / squashed / decoded layers / inside URLs) -> block;
  * system-prompt shingle overlap >= overlap_threshold -> block;
  * URLs whose decoded query/path carries >= 3 system shingles -> block (hidden-context exfil).
Never raises (``fail_mode: closed`` would turn a bug into an outage).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from aegis.controls.injection import _common as _c
from aegis.controls.injection._common import Inj04Params, mask, parse_params, session_data
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding, Interaction, RequestContext
from aegis.injection import explain
from aegis.injection.canary import _url_texts, extract_urls, find_canaries, overlap, shingles
from aegis.injection.exemplars import exemplar_vote_fn
from aegis.injection.segments import select_units
from aegis.injection.signatures import ScanOptions, scan_text

log = logging.getLogger("aegis.controls.injection.inj04")

_EXTRACTION_OPTS = ScanOptions(only_families=frozenset({"extraction"}))
_WEAK_CUE = (
    "system prompt",
    "instructions",
    "above",
    "initial prompt",
    "prompt systemowy",
    "instrukcj",
    "powyzej",
    "systemprompt",
    "anweisungen",
    "configuration",
    "konfiguracj",
    "verbatim",
    "word for word",
)


class HiddenContextGuard(BaseControl):
    id = "INJ-04"
    family = "INJ"
    name = "Hidden-context exposure (extraction + canary + overlap)"
    kind = "hybrid"
    applies_to = AppliesTo(surfaces={"prompt.user", "model.request", "model.response"})
    owasp = ["LLM08:2026", "ASI01"]
    priority = 45

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        try:
            p = parse_params(Inj04Params, cfg)
            rt = _c.get_rt()
            if interaction.surface == "model.response":
                return self._response(ctx, interaction, cfg, p, rt)
            return await self._request(ctx, interaction, cfg, p, rt)
        except Exception:
            log.exception("INJ-04 internal error (degraded allow)")
            return Decision(
                action="allow",
                control_id=self.id,
                reason="INJ-04 internal error (degraded)",
                degraded=True,
            )

    # ------------------------------------------------------------------ request side
    async def _request(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        cfg: ControlConfig,
        p: Inj04Params,
        rt: Any,
    ) -> Decision | None:
        if interaction.surface == "model.request":
            self._record_system(ctx, interaction, p, rt)
        units = [
            u
            for u in select_units(interaction, strip_harness=p.strip_harness_blocks, ctx=ctx)
            if u.trust == "trusted" and u.block_eligible
        ]
        thr = float(p.extraction_threshold)
        best = None
        for u in units:
            res = scan_text(u.text, trust="trusted", opts=_EXTRACTION_OPTS)
            if res.score >= thr and (best is None or res.score > best[1].score):
                best = (u, res)
        if best is not None:
            u, res = best
            top = res.top
            findings = [
                Finding(
                    control_id=self.id,
                    detector=f"inj.extract.{h.sig_id}",
                    category="injection",
                    entity="PROMPT_INJECTION",
                    severity=cfg.severity,
                    score=h.weight,
                    segment_index=u.index,
                    start=h.start,
                    end=h.end,
                    excerpt=mask(rt, h.matched, 80),
                    meta={"family": h.family, "view": h.view},
                )
                for h in res.hits[:8]
            ]
            reason = (
                f"Hidden-context extraction attempt in {explain.SURFACE_LABEL.get(interaction.surface, '')} — "
                f"{explain.where(top.view if top else None)}; score {res.score:.2f} ≥ {thr:.2f}"
            )
            d = self.decide(
                cfg,
                reason=reason,
                score=res.score,
                findings=findings,
                meta={
                    "inj": explain.meta(
                        trust="trusted",
                        outcome="block",
                        score=res.score,
                        threshold=thr,
                        segments=[explain.segment_meta(u)],
                        normalization=explain.normalization_meta(res.norm),
                        signals=[
                            {
                                "stage": "signature",
                                "id": h.sig_id,
                                "family": h.family,
                                "weight": h.weight,
                                "view": h.view,
                                "excerpt": mask(rt, h.matched, 80),
                            }
                            for h in res.hits[:8]
                        ],
                    )
                },
            )
            d.threshold = thr
            return d
        # paraphrase leg (embeddings; skipped while the index warms up / without MiniLM)
        if p.exemplars.enabled and units:
            vote = exemplar_vote_fn(rt, p.exemplars, only="extraction")
            if vote is not None:
                for u in units:
                    low = u.text.lower()
                    if not any(c in low for c in _WEAK_CUE):
                        continue
                    ev = await vote(u.text)
                    if ev and ev.get("hit"):
                        d = self.decide(
                            cfg,
                            reason=(
                                f"Hidden-context extraction paraphrase — exemplar '{ev['label']}' "
                                f"sim {ev['sim']:.2f} ≥ {ev['threshold']:.2f}"
                            ),
                            score=float(ev["sim"]),
                            findings=[
                                Finding(
                                    control_id=self.id,
                                    detector="inj.extract.exemplar",
                                    category="injection",
                                    entity="PROMPT_INJECTION",
                                    severity=cfg.severity,
                                    score=float(ev["sim"]),
                                    segment_index=u.index,
                                    excerpt=mask(rt, u.text, 80),
                                )
                            ],
                            meta={
                                "inj": explain.meta(
                                    trust="trusted",
                                    outcome="block",
                                    score=float(ev["sim"]),
                                    threshold=float(ev["threshold"]),
                                    segments=[explain.segment_meta(u)],
                                    signals=[ev],
                                )
                            },
                        )
                        d.threshold = float(ev["threshold"])
                        return d
        return None

    def _record_system(
        self, ctx: RequestContext, interaction: Interaction, p: Inj04Params, rt: Any
    ) -> None:
        sys_text = "\n".join(s.text for s in interaction.segments if s.role == "system" and s.text)
        if not sys_text.strip():
            return
        sh = shingles(sys_text, p.ngram)
        ctx.state["inj.sys_shingles"] = sh
        if ctx.dry_run:
            return
        data = session_data(rt, ctx)
        if data is not None:
            data["sys_shingles"] = sh
            data["sys_digest"] = hashlib.sha1(
                sys_text.encode("utf-8", "surrogatepass")
            ).hexdigest()[:16]

    # ------------------------------------------------------------------ response side
    def _response(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        cfg: ControlConfig,
        p: Inj04Params,
        rt: Any,
    ) -> Decision | None:
        # every response text block (adapters use role=assistant; /v1/guard uses tool_result)
        segs = [
            (i, s)
            for i, s in enumerate(interaction.segments)
            if s.text and s.role not in ("system", "header")
        ]
        cans = p.all_canaries()
        for i, s in segs:
            hits = find_canaries(s.text, cans)
            if hits:
                h = hits[0]
                reason = f"System-prompt canary leaked in model response ({h.form})"
                d = self.decide(
                    cfg,
                    reason=reason,
                    score=1.0,
                    findings=[
                        Finding(
                            control_id=self.id,
                            detector="inj.canary",
                            category="injection",
                            entity="CANARY",
                            severity=cfg.severity,
                            score=1.0,
                            segment_index=i,
                            start=h.start,
                            end=h.end,
                            excerpt=mask(rt, h.canary[:6] + "…", 40),
                            meta={"form": h.form},
                        )
                    ],
                    meta={
                        "inj": explain.meta(
                            trust="untrusted",
                            outcome="block",
                            score=1.0,
                            threshold=1.0,
                            signals=[{"stage": "canary", "form": x.form} for x in hits],
                        )
                    },
                )
                d.threshold = 1.0
                return d
        sys_sh = ctx.state.get("inj.sys_shingles")
        if not sys_sh:
            data = session_data(rt, ctx)
            sys_sh = (data or {}).get("sys_shingles")
        if not sys_sh:
            return None
        thr = float(p.overlap_threshold)
        best = None
        for i, s in segs:
            ov = overlap(sys_sh, s.text, p.ngram, p.min_shared_ngrams)
            if best is None or ov.score > best[1].score:
                best = (i, ov)
        if best is not None and best[1].score >= thr:
            i, ov = best
            d = self.decide(
                cfg,
                reason=f"Response reproduces {ov.coverage * 100:.0f} % of system-prompt {p.ngram}-grams "
                f"(score {ov.score:.2f} ≥ {thr:.2f})",
                score=ov.score,
                findings=[
                    Finding(
                        control_id=self.id,
                        detector="inj.overlap",
                        category="injection",
                        entity="SYSTEM_PROMPT",
                        severity=cfg.severity,
                        score=ov.score,
                        segment_index=i,
                        meta={
                            "coverage": ov.coverage,
                            "contamination": ov.contamination,
                            "shared": ov.shared,
                        },
                    )
                ],
                meta={
                    "inj": explain.meta(
                        trust="untrusted",
                        outcome="block",
                        score=ov.score,
                        threshold=thr,
                        signals=[
                            {
                                "stage": "overlap",
                                "coverage": ov.coverage,
                                "contamination": ov.contamination,
                                "shared": ov.shared,
                                "threshold": thr,
                            }
                        ],
                    )
                },
            )
            d.threshold = thr
            return d
        if p.check_urls:
            for i, s in segs:
                for url, a, b in extract_urls(s.text):
                    for form, dec in _url_texts(url):
                        n = (
                            len(sys_sh & shingles(dec, p.ngram))
                            if len(dec.split()) >= p.ngram
                            else 0
                        )
                        if n >= 3:
                            d = self.decide(
                                cfg,
                                reason=f"Hidden context exfiltrated via URL ({form}, {n} system-prompt n-grams)",
                                score=1.0,
                                findings=[
                                    Finding(
                                        control_id=self.id,
                                        detector="inj.url_exfil",
                                        category="exfil",
                                        severity=cfg.severity,
                                        score=1.0,
                                        segment_index=i,
                                        start=a,
                                        end=b,
                                        excerpt=mask(rt, url, 60),
                                        meta={"form": form, "shared": n},
                                    )
                                ],
                                meta={
                                    "inj": explain.meta(
                                        trust="untrusted",
                                        outcome="block",
                                        score=1.0,
                                        threshold=1.0,
                                        signals=[{"stage": "url_exfil", "form": form, "shared": n}],
                                    )
                                },
                            )
                            d.threshold = 1.0
                            return d
        return None


CONTROLS = [HiddenContextGuard()]
