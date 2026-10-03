"""Control INJ-02 engine: classifier cascade on ``rt.semantic`` (docs/plan/05 INJ-05).

Per scan unit:
1. candidate texts - the unit text (head 3000 + tail 1000 chars), each decoded layer / hidden
   payload, and for long untrusted text the top-K "instruction-like" sentences;
2. ``rt.semantic.injection_score`` per candidate (concurrently, cached by sha1 - scores are
   threshold-independent, so live threshold edits flip verdicts without a cache flush);
   when the engine is degraded (or absent) the local signature heuristic is folded in
   (``max(engine heuristic, signature score)``) and the result is marked ``degraded``;
3. bands: ``s >= thr`` act - ``review <= s < thr`` escalate to ``rt.semantic.moderate`` (guard)
   - else nothing. Guard degraded / timeout / no budget -> ``review_fallback[trust]``.
4. exemplar vote (``rt.semantic.embed``) can lift a unit into the review band, never act alone.

Never raises; every stage is recorded in ``signals`` (Appendix B).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from aegis.injection.normalize import Normalized, normalize
from aegis.injection.segments import ScanUnit, split_sentences
from aegis.injection.signatures import scan_text
from aegis.injection.views import keywords

log = logging.getLogger("aegis.injection.cascade")

_CACHE: OrderedDict[tuple[str, bool], tuple[float, str, bool, str | None]] = OrderedDict()
_CACHE_MAX = 4096


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()


def clear_cache() -> None:
    _CACHE.clear()


@dataclass(slots=True)
class Scored:
    score: float
    model: str
    degraded: bool
    reason: str | None = None
    ms: float = 0.0
    cached: bool = False


@dataclass(slots=True)
class UnitScore:
    unit: ScanUnit
    score: float = 0.0
    model: str = "none"
    band: str = "allow"  # act | review | allow
    act: bool = False
    degraded: bool = False
    review_outcome: str | None = None  # confirmed | cleared | fallback
    stages: list[dict[str, Any]] = field(default_factory=list)
    spans: list[tuple[int, int]] = field(default_factory=list)  # untrusted quarantine spans
    best_candidate: str = ""
    threshold: float = 0.0


# ---------------------------------------------------------------- semantic calls
async def _call_injection(rt: Any, text: str, trusted: bool, timeout_s: float | None) -> Any:
    sem = getattr(rt, "semantic", None) if rt is not None else None
    if sem is None:
        return None
    try:
        return await sem.injection_score(text, trusted=trusted, timeout_s=timeout_s, escalate=False)
    except TypeError:
        return await sem.injection_score(text)


async def _call_guard(rt: Any, text: str, timeout_s: float | None) -> Any:
    sem = getattr(rt, "semantic", None) if rt is not None else None
    if sem is None:
        return None
    try:
        return await sem.moderate(text, mode="prompt", timeout_s=timeout_s)
    except TypeError:
        return await sem.moderate(text)


async def score_text(
    rt: Any,
    text: str,
    *,
    trusted: bool,
    local_heuristic: bool = True,
    timeout_s: float | None = None,
) -> Scored:
    """Injection probability for one candidate text (cached when not degraded)."""
    k = (_key(text), trusted)
    hit = _CACHE.get(k)
    if hit is not None:
        _CACHE.move_to_end(k)
        return Scored(hit[0], hit[1], hit[2], hit[3], 0.0, True)
    t0 = time.perf_counter()
    res = None
    try:
        res = await _call_injection(rt, text, trusted, timeout_s)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning("injection_score failed - heuristic fallback", exc_info=True)
    ms = (time.perf_counter() - t0) * 1000
    if res is None:
        score, model, degraded, reason = 0.0, "none", True, "fallback:missing"
    else:
        score = float(getattr(res, "score", 0.0) or 0.0)
        model = str(getattr(res, "model", "") or "unknown")
        degraded = bool(getattr(res, "degraded", False))
        reason = getattr(res, "reason", None)
    if degraded and local_heuristic:
        local = scan_text(text, trust="trusted" if trusted else "untrusted").score
        if local > score:
            score = local
        model = (
            "heuristic"
            if model in ("null", "none", "unknown", "heuristic")
            else f"{model}+heuristic"
        )
    out = Scored(round(min(1.0, max(0.0, score)), 4), model, degraded, reason, ms)
    if not degraded:
        _CACHE[k] = (out.score, out.model, out.degraded, out.reason)
        if len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return out


# ---------------------------------------------------------------- candidates
_SECOND_PERSON = re.compile(r"\b(?:you|your|yourself|ty|twoj\w*|twoja|ciebie|du|dein\w*|sie)\b")
_URLISH = re.compile(r"https?://|www\.|[\w.+-]+@[\w-]+\.\w")


def _instruction_likeness(sentence: str) -> float:
    s = sentence.lower()
    kw = keywords()
    score = 0.0
    for w in kw.get("imperatives", []):  # type: ignore[union-attr]
        if w and re.search(rf"\b{re.escape(w)}\b", s):
            score += 1.0
    for w in kw.get("agent_words", []):  # type: ignore[union-attr]
        if w and w in s:
            score += 1.5
    if _SECOND_PERSON.search(s):
        score += 0.5
    if _URLISH.search(s):
        score += 0.5
    return score


def head_tail(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.75)
    return text[:head] + "\n…\n" + text[-(max_chars - head) :]


def candidates(
    unit: ScanUnit, norm: Normalized, *, max_chars: int, score_layers: bool, max_sentences: int
) -> list[tuple[str, str]]:
    """(label, text) candidates for one unit."""
    out: list[tuple[str, str]] = []
    text = unit.text
    if unit.trust == "untrusted" and len(text) > max_chars:
        spans = split_sentences(text)
        ranked = sorted(spans, key=lambda sp: -_instruction_likeness(text[sp[0] : sp[1]]))[
            :max_sentences
        ]
        ranked = sorted(r for r in ranked if _instruction_likeness(text[r[0] : r[1]]) > 0)
        if ranked:
            out.append(("sentences", " ".join(text[a:b] for a, b in ranked)[:max_chars]))
        out.append(("head_tail", head_tail(text, max_chars)))
    else:
        out.append(("text", head_tail(text, max_chars)))
    if score_layers:
        for ly in norm.layers[:6]:
            if ly.text.strip() and ly.kind != "rot13":
                out.append((f"layer:{ly.kind}@{ly.depth}", ly.text[:max_chars]))
        for h in norm.hidden[:6]:
            if (
                h.decoded
                and h.decoded.strip()
                and h.kind in ("html_comment", "css_hidden", "md_comment")
            ):
                out.append((f"hidden:{h.kind}", h.decoded[:max_chars]))
    seen: set[str] = set()
    uniq = []
    for lbl, t in out:
        if t not in seen:
            seen.add(t)
            uniq.append((lbl, t))
    return uniq


# ---------------------------------------------------------------- unit classification
async def classify_unit(
    rt: Any,
    unit: ScanUnit,
    *,
    params: Any,
    threshold: float,
    budget_s: float,
    exemplar_vote: Any = None,
) -> UnitScore:
    """Score one unit and resolve its band (see module docstring). Never raises."""
    t_start = time.perf_counter()
    us = UnitScore(unit=unit, threshold=threshold)
    trusted = unit.trust == "trusted"
    try:
        norm = normalize(unit.text, max_len=262_144)
        cands = candidates(
            unit,
            norm,
            max_chars=int(params.max_chars),
            score_layers=bool(params.score_decoded_layers),
            max_sentences=int(params.untrusted_max_sentences),
        )
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *(
                        score_text(rt, t, trusted=trusted, local_heuristic=params.local_heuristic)
                        for _, t in cands
                    )
                ),
                timeout=max(0.05, budget_s),
            )
        except TimeoutError:
            us.degraded = True
            us.stages.append(
                {
                    "stage": "classifier",
                    "degraded": True,
                    "error": "timeout",
                    "ms": round((time.perf_counter() - t_start) * 1000, 2),
                }
            )
            return us
        best_i = max(range(len(results)), key=lambda i: results[i].score)
        best = results[best_i]
        us.score = best.score
        us.model = best.model
        us.degraded = any(r.degraded for r in results)
        us.best_candidate = cands[best_i][1]
        review = float(params.review_threshold)
        us.band = "act" if us.score >= threshold else ("review" if us.score >= review else "allow")
        us.stages.append(
            {
                "stage": "classifier",
                "model": best.model,
                "score": us.score,
                "threshold": threshold,
                "band": us.band,
                "degraded": us.degraded,
                "candidate": cands[best_i][0],
                "candidates": len(cands),
                "ms": round(sum(r.ms for r in results), 2),
                "cached": all(r.cached for r in results),
                **({"reason": best.reason} if best.reason else {}),
            }
        )
        # exemplar vote: may lift into the review band (never acts alone)
        if us.band == "allow" and exemplar_vote is not None:
            try:
                ev = await exemplar_vote(unit.text)
            except Exception:
                ev = None
            if ev:
                us.stages.append(ev)
                if ev.get("hit"):
                    us.band = "review"
        if us.band == "review":
            await _review(rt, us, params, budget_s - (time.perf_counter() - t_start))
        if us.act and not trusted:
            await _localize(rt, us, params, threshold)
    except Exception:
        log.exception("INJ-02 unit classification failed (degraded)")
        us.degraded = True
        us.act = False
        us.stages.append({"stage": "classifier", "error": "internal", "degraded": True})
        return us
    if us.band == "act":
        us.act = True
        if not trusted and not us.spans:
            await _localize(rt, us, params, threshold)
    return us


async def _review(rt: Any, us: UnitScore, params: Any, remaining_s: float) -> None:
    trusted = us.unit.trust == "trusted"
    g = params.guard
    fallback = params.review_fallback.trusted if trusted else params.review_fallback.untrusted
    if not g.enabled or remaining_s * 1000 < g.timeout_ms * 0.5:
        us.review_outcome = "fallback"
        us.stages.append(
            {
                "stage": "guard",
                "skipped": "disabled" if not g.enabled else "budget",
                "fallback": fallback,
            }
        )
        us.act = fallback in ("block", "redact")
        us.degraded = us.degraded or g.enabled
        return
    t0 = time.perf_counter()
    res = None
    try:
        res = await asyncio.wait_for(
            _call_guard(rt, us.best_candidate, g.timeout_ms / 1000),
            timeout=min(remaining_s, g.timeout_ms / 1000 + 0.05),
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        res = None
    ms = round((time.perf_counter() - t0) * 1000, 2)
    if res is None or getattr(res, "degraded", False):
        us.review_outcome = "fallback"
        us.degraded = True
        us.act = fallback in ("block", "redact")
        us.stages.append(
            {
                "stage": "guard",
                "model": getattr(res, "model", "aegis-guard"),
                "degraded": True,
                "fallback": fallback,
                "ms": ms,
            }
        )
        return
    gs = float(getattr(res, "score", 0.0) or 0.0)
    confirmed = gs >= float(g.threshold)
    us.review_outcome = "confirmed" if confirmed else "cleared"
    us.act = confirmed
    us.stages.append(
        {
            "stage": "guard",
            "model": getattr(res, "model", "aegis-guard"),
            "label": getattr(res, "label", ""),
            "categories": list(getattr(res, "categories", []) or []),
            "score": gs,
            "threshold": float(g.threshold),
            "ms": ms,
        }
    )


async def _localize(rt: Any, us: UnitScore, params: Any, threshold: float) -> None:
    """Untrusted act: quarantine the sentences scoring >= threshold (else the whole segment)."""
    text = us.unit.text
    sents = split_sentences(text)
    if len(sents) <= 1:
        us.spans = [(0, len(text))]
        return
    ranked = sorted(sents, key=lambda sp: -_instruction_likeness(text[sp[0] : sp[1]]))[
        : int(params.untrusted_max_sentences)
    ]
    try:
        res = await asyncio.gather(
            *(
                score_text(rt, text[a:b], trusted=False, local_heuristic=params.local_heuristic)
                for a, b in ranked
            )
        )
    except Exception:
        res = []
    cut = threshold if us.review_outcome is None else float(params.review_threshold)
    spans = [sp for sp, r in zip(ranked, res, strict=False) if r.score >= cut]
    us.spans = sorted(spans) if spans else [(0, len(text))]
