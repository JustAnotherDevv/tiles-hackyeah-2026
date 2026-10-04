"""Obfuscation heatmap (`aegis.heatmap/1`, plan 19 §2.8) from generated/obfuscation_matrix results."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from tests.corpora.obfuscate import (
    BENIGN_SEEDS,
    BENIGN_TRANSFORMS,
    EXPECTED_HANDLING,
    SEEDS,
    TRANSFORMS,
)
from tests.eval.metrics import wilson
from tests.eval.scoring import CaseResult

SCHEMA = "aegis.heatmap/1"
MATRIX_FILE = "generated/obfuscation_matrix.jsonl"


def _cell(r: CaseResult | None) -> dict[str, Any] | None:
    if r is None:
        return None
    return {
        "action": r.action if r.error is None else "error",
        "control_id": r.primary_control,
        "detected": bool(r.detected) if r.label == "attack" else None,
        "over_block": bool(r.over_block) if r.label == "benign" else None,
        "score": None if r.score is None else round(r.score, 3),
        "latency_ms": None if r.latency_ms is None else round(r.latency_ms, 2),
        "error": r.error,
    }


def _rate(k: int, n: int) -> float | None:
    return round(k / n, 4) if n else None


def _preview(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def matrix_results(results: list[CaseResult]) -> list[CaseResult]:
    return [r for r in results if r.source == MATRIX_FILE or (r.seed_id and r.transform)]


def build_matrix(results: list[CaseResult]) -> dict[str, Any]:
    """Primary-style matrix block (seeds x transforms) for one run's results."""
    idx = {(r.seed_id, r.transform): r for r in matrix_results(results)}
    transforms = list(TRANSFORMS)
    cells: list[list[dict[str, Any] | None]] = []
    row_rate = []
    col = {t: [0, 0] for t in transforms}
    tot_k = tot_n = 0
    for sid, _lang, _kind, _text in SEEDS:
        row = []
        k = n = 0
        for t in transforms:
            r = idx.get((sid, t))
            c = _cell(r)
            row.append(c)
            if r is not None and r.error is None:
                n += 1
                col[t][1] += 1
                if r.detected:
                    k += 1
                    col[t][0] += 1
        cells.append(row)
        row_rate.append({"seed": sid, "detected": k, "n": n, "rate": _rate(k, n)})
        tot_k += k
        tot_n += n
    col_rate = [{"transform": t, "detected": col[t][0], "n": col[t][1], "rate": _rate(*col[t]),
                 "ci95": wilson(*col[t])} for t in transforms]
    bcells = []
    ob = bn = 0
    for sid, _lang, _kind, _text in BENIGN_SEEDS:
        row = []
        for t in BENIGN_TRANSFORMS:
            r = idx.get((sid, t))
            row.append(_cell(r))
            if r is not None and r.error is None:
                bn += 1
                ob += int(r.over_block)
        bcells.append(row)
    return {
        "cells": cells,
        "row_rate": row_rate,
        "col_rate": col_rate,
        "overall": {"detected": tot_k, "n": tot_n, "rate": _rate(tot_k, tot_n), "ci95": wilson(tot_k, tot_n)},
        "benign": {
            "seeds": [{"id": s, "lang": lang, "kind": kind, "preview": _preview(text)}
                      for s, lang, kind, text in BENIGN_SEEDS],
            "transforms": list(BENIGN_TRANSFORMS),
            "cells": bcells,
            "over_block": ob,
            "n": bn,
            "fpr": _rate(ob, bn),
            "ci95": wilson(ob, bn),
        },
    }


def build_heatmap(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """`runs` = [{profile, mode, results: [CaseResult]}]. Primary = balanced·semantic, else balanced·det."""
    usable = [r for r in runs if matrix_results(r.get("results") or [])]
    if not usable:
        return None

    def pick() -> dict[str, Any]:
        for prof, mode_prefix in (("balanced", "semantic"), ("balanced", "deterministic")):
            for r in usable:
                if r["profile"] == prof and str(r["mode"]).startswith(mode_prefix):
                    return r
        return usable[0]

    primary = pick()
    m = build_matrix(primary["results"])
    out: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "profile": primary["profile"],
        "mode": primary["mode"],
        "transforms": [{"id": t, "handling": EXPECTED_HANDLING.get(t, "")} for t in TRANSFORMS],
        "seeds": [{"id": s, "lang": lang, "kind": kind, "preview": _preview(text)}
                  for s, lang, kind, text in SEEDS],
        **m,
        "variants": [],
    }
    for r in usable:
        if r is primary:
            continue
        v = build_matrix(r["results"])
        out["variants"].append({"profile": r["profile"], "mode": r["mode"], "overall": v["overall"],
                                "col_rate": v["col_rate"], "benign_over_block": v["benign"]["over_block"]})
    return out


def ascii_heatmap(hm: dict[str, Any]) -> str:
    """█ detected · missed (blank = n/a, E = error)."""
    ts = [t["id"] for t in hm["transforms"]]
    abbrev = [t[:4] for t in ts]
    lines = ["seed        " + " ".join(f"{a:>4}" for a in abbrev) + "  rate"]
    for seed, row, rr in zip(hm["seeds"], hm["cells"], hm["row_rate"], strict=False):
        chars = []
        for c in row:
            if c is None:
                chars.append("    ")
            elif c.get("error"):
                chars.append("   E")
            else:
                chars.append("   █" if c.get("detected") else "   ·")
        rate = "  n/a" if rr["rate"] is None else f"{rr['rate'] * 100:4.0f}%"
        lines.append(f"{seed['id']:<11} " + " ".join(chars) + f"  {rate}")
    cr = hm["col_rate"]
    lines.append("col rate    " + " ".join(
        "  - " if c["rate"] is None else f"{c['rate'] * 100:3.0f}%" for c in cr))
    o = hm["overall"]
    b = hm["benign"]
    lines.append(f"overall {o['detected']}/{o['n']} detected; benign twins over-blocked {b['over_block']}/{b['n']}")
    return "\n".join(lines)


__all__ = ["SCHEMA", "ascii_heatmap", "build_heatmap", "build_matrix"]
