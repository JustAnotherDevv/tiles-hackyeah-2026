"""Wilson CIs, percentiles and per-run aggregation (plan 19 §2.7)."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from tests.eval.scoring import CaseResult

LANG_BUCKETS = ("en", "pl", "de")
MAX_LIST = 20


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for k successes out of n (None for n == 0)."""
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def percentile(xs: Sequence[float], p: float) -> float | None:
    """Linear-interpolated percentile (same as staging/models `pct`), p in [0, 100]."""
    if not xs:
        return None
    s = sorted(xs)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * p / 100.0
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(s[lo])
    return float(s[lo] + (s[hi] - s[lo]) * (k - lo))


def pct_summary(xs: Sequence[float], *, ndigits: int = 3) -> dict[str, float | int | None]:
    if not xs:
        return {"p50": None, "p95": None, "p99": None, "max": None, "mean": None, "n": 0}
    return {
        "p50": _r(percentile(xs, 50), ndigits),
        "p95": _r(percentile(xs, 95), ndigits),
        "p99": _r(percentile(xs, 99), ndigits),
        "max": _r(max(xs), ndigits),
        "mean": _r(sum(xs) / len(xs), ndigits),
        "n": len(xs),
    }


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(float(x), nd)


def lang_bucket(lang: str) -> str:
    return lang if lang in LANG_BUCKETS else "other"


def _ok(results: Iterable[CaseResult]) -> list[CaseResult]:
    return [r for r in results if r.error is None]


def rates(results: Iterable[CaseResult]) -> dict[str, Any]:
    ok = _ok(results)
    att = [r for r in ok if r.label == "attack"]
    ben = [r for r in ok if r.label == "benign"]
    det = sum(r.detected for r in att)
    mon = sum(r.would_detect_monitor for r in att)
    ob = sum(r.over_block for r in ben)
    itv = sum(r.intervened for r in ben)
    out: dict[str, Any] = {
        "attack": {"n": len(att), "detected": det, "rate": _r(det / len(att)) if att else None,
                   "ci95": wilson(det, len(att)), "would_detect_monitor": mon},
        "benign": {"n": len(ben), "over_block": ob, "fpr": _r(ob / len(ben)) if ben else None,
                   "ci95": wilson(ob, len(ben)), "intervened": itv,
                   "intervention_rate": _r(itv / len(ben)) if ben else None},
    }
    return out


def _with_quality(block: dict[str, Any], results: list[CaseResult]) -> dict[str, Any]:
    tp = block["attack"]["detected"]
    fp = block["benign"]["over_block"]
    fn = block["attack"]["n"] - tp
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None
    ok = _ok(results)
    em = sum(r.exact_match for r in ok)
    block.update({"precision": _r(precision), "recall": _r(recall), "f1": _r(f1),
                  "exact_match_rate": _r(em / len(ok)) if ok else None})
    return block


def breakdown(results: list[CaseResult], key: Callable[[CaseResult], str]) -> dict[str, Any]:
    groups: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        groups[key(r)].append(r)
    return {k: rates(v) for k, v in sorted(groups.items())}


def by_control(results: list[CaseResult]) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "deciding": 0})
    for r in _ok(results):
        for c in r.relevant_controls:
            if r.label == "attack" and r.detected:
                stats[c]["tp"] += 1
            elif r.label == "benign" and r.over_block:
                stats[c]["fp"] += 1
        if r.primary_control and (r.detected or r.over_block):
            stats[r.primary_control]["deciding"] += 1
    return [{"control_id": c, **v} for c, v in sorted(stats.items(), key=lambda kv: -kv[1]["tp"])]


def _item(r: CaseResult) -> dict[str, Any]:
    return {"id": r.id, "category": r.category, "lang": r.lang, "surface": r.surface,
            "action": r.action, "control_id": r.primary_control, "preview": r.preview}


def aggregate(results: list[CaseResult]) -> dict[str, Any]:
    """RunSummary: overall + every breakdown + misses / false positives."""
    overall = _with_quality(rates(results), results)
    lat = [r.latency_ms for r in results if r.latency_ms is not None and r.error is None]
    errors = [r for r in results if r.error is not None]
    misses = [r for r in _ok(results) if r.label == "attack" and not r.detected]
    fps = [r for r in _ok(results) if r.label == "benign" and r.over_block]
    return {
        "n": len(results),
        "overall": overall,
        "by_lang": breakdown(results, lambda r: lang_bucket(r.lang)),
        "by_category": breakdown(results, lambda r: r.category.split(".")[0]),
        "by_surface": breakdown(results, lambda r: r.surface),
        "by_source": breakdown(results, lambda r: r.source),
        "by_split": breakdown(results, lambda r: r.split),
        "by_control": by_control(results),
        "latency_ms": {"p50": _r(percentile(lat, 50), 3), "p95": _r(percentile(lat, 95), 3),
                       "n": len(lat)},
        "errors": len(errors),
        "error_samples": [{"id": r.id, "error": (r.error or "")[:200]} for r in errors[:5]],
        "degraded_blocks": sum(1 for r in results if r.degraded and r.action == "block"),
        "misses_total": len(misses),
        "misses": [_item(r) for r in misses[:MAX_LIST]],
        "false_positives_total": len(fps),
        "false_positives": [_item(r) for r in fps[:MAX_LIST]],
    }


def stratified_sample(items: list[Any], n: int, key: Callable[[Any], tuple], *, seed: int = 20261003,
                      min_per_stratum: int = 3) -> list[Any]:
    """>= min_per_stratum per stratum, then proportional fill up to n (deterministic)."""
    if n >= len(items):
        return list(items)
    rng = random.Random(seed)
    strata: dict[tuple, list[Any]] = defaultdict(list)
    for it in items:
        strata[key(it)].append(it)
    for v in strata.values():
        rng.shuffle(v)
    chosen: list[Any] = []
    for k in sorted(strata):
        chosen.extend(strata[k][:min_per_stratum])
    rest = [it for k in sorted(strata) for it in strata[k][min_per_stratum:]]
    rng.shuffle(rest)
    room = max(0, n - len(chosen))
    chosen.extend(rest[:room])
    return chosen


__all__ = ["aggregate", "breakdown", "by_control", "lang_bucket", "pct_summary", "percentile", "rates",
           "stratified_sample", "wilson"]
