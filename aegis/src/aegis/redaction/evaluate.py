"""Fixture evaluation for the redaction engine (port of staging/pii/evaluate.py).

    uv run --frozen python -m aegis.redaction.evaluate [--check] [--bench] [--write] [--failures]

Metrics (Tier-D, contract entity names):
  * exact: predicted (entity, start, end) == gold span; covering: same entity covers gold span
  * leak: after tokenizing every prediction (toward ``remote``) the gold value is still present
    verbatim, in the normalised view, or (numeric types) as a digit subsequence. Target 0.
  * hard negatives / finance-benign prompts: any finding is a false positive
  * adversarial recall per technique (A1..A13); per-language P/R/F1; latency p50/p95
NER entities (PERSON, ADDRESS) are reported separately for the heuristic tier.

Fixture rows with secret-shaped strings are stored ROT13-encoded (``"enc": "rot13"``) so that the
repository never contains strings matching secret scanners; they are decoded in memory only.
"""

from __future__ import annotations

import argparse
import codecs
import json
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import entities as E
from .normalize import normalize
from .placeholders import Vault, canonicalize, irreversible, rehydrate_text
from .scan import VALIDATED_ENTITIES, Hit, Scanner

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "data" / "fixtures"
REPORTS = Path(__file__).resolve().parents[3] / "reports"
TIER_D = frozenset(e for e, i in E.ENTITIES.items() if i.source == "tier-d")
NER_EVAL = frozenset({"PERSON", "ADDRESS"})
NUMERIC = frozenset({"PAN", "PESEL", "NIP", "REGON", "PHONE", "CVV", "IBAN"})
GOLD_ALIASES = {"CRYPTO_BTC": "CRYPTO_ADDRESS", "CRYPTO_ETH": "CRYPTO_ADDRESS"}
_RUN = re.compile(r"[0-9](?:[ \t\-.\n]{0,3}[0-9])*")
_BENIGN = "finance_benign.jsonl"


def _decode(c: dict[str, Any]) -> dict[str, Any]:
    if c.get("enc") != "rot13":
        return c
    c = dict(c)
    c["text"] = codecs.decode(c["text"], "rot13")
    c["entities"] = [dict(e, value=codecs.decode(e["value"], "rot13")) for e in c["entities"]]
    c.pop("enc", None)
    return c


def load_fixtures(path: Path = FIXTURES) -> list[dict[str, Any]]:
    """The 626 labelled cases (decoded in memory; gold types mapped to contract names)."""
    cases = []
    for f in sorted(path.glob("*.jsonl")):
        if f.name == _BENIGN:
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c = _decode(json.loads(line))
            for e in c["entities"]:
                e["type"] = GOLD_ALIASES.get(e["type"], e["type"])
            c["_file"] = f.name.replace(".rot13", "")
            cases.append(c)
    return cases


def load_benign(path: Path = FIXTURES / _BENIGN) -> list[dict[str, Any]]:
    try:
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        return []


def _leaked(gold: dict[str, Any], out_text: str) -> bool:
    v = gold["value"]
    if v in out_text:
        return True
    nv = normalize(v).text
    nout = normalize(out_text).text
    if gold["type"] == "CVV":
        runs = {re.sub(r"\D", "", m.group(0)) for m in _RUN.finditer(nout)}
        return re.sub(r"\D", "", nv) in runs
    if len(nv) >= 4 and nv in nout:
        return True
    if gold["type"] in NUMERIC:
        dig = re.sub(r"\D", "", nv)
        if len(dig) >= 9:
            return any(dig in re.sub(r"\D", "", m.group(0)) for m in _RUN.finditer(nout))
    return False


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def tokenize_all(text: str, pred: list[Hit], vault: Vault) -> tuple[str, bool]:
    """What would leave toward ``remote``: every prediction tokenized (SAD dropped)."""
    out = text
    reversible = True
    for h in sorted(pred, key=lambda x: x.start, reverse=True):
        raw = text[h.start : h.end]
        if h.entity in E.IRREVERSIBLE:
            rep = irreversible(h.entity)
            reversible = False
        else:
            rep = vault.put(h.entity, raw, canonicalize(h.entity, raw))
        out = out[: h.start] + rep + out[h.end :]
    return out, reversible


def _detect(det: Scanner, text: str) -> list[Hit]:
    # documentation examples are reported for DLP-02 `log` but never transformed
    return [h for h in det.detect(text) if not h.meta.get("doc_example")]


def evaluate(cases: list[dict[str, Any]] | None = None, detector: Scanner | None = None) -> dict:
    cases = cases if cases is not None else load_fixtures()
    det = detector or Scanner()
    per: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "gold": 0,
            "tp": 0,
            "fp": 0,
            "fn": 0,
            "cov_tp": 0,
            "leaks": 0,
            "adv_gold": 0,
            "adv_tp": 0,
        }
    )
    by_lang: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    by_tech: dict[str, dict[str, int]] = defaultdict(lambda: {"cases": 0, "ok": 0})
    failures = []
    lat = []
    case_ok = 0
    neg_total = neg_fp = 0
    rt_total = rt_ok = 0
    for c in cases:
        text = c["text"]
        gold = [e for e in c["entities"] if e["type"] in TIER_D]
        t0 = time.perf_counter()
        pred = _detect(det, text)
        lat.append((time.perf_counter() - t0) * 1000)
        gset = {(e["type"], e["start"], e["end"]) for e in gold}
        pset = {(f.entity, f.start, f.end) for f in pred}
        adv = "adversarial" in c["tags"]
        for e in gold:
            s = per[e["type"]]
            s["gold"] += 1
            hit = (e["type"], e["start"], e["end"]) in pset
            cov = any(
                f.entity == e["type"] and f.start <= e["start"] and f.end >= e["end"] for f in pred
            )
            s["tp" if hit else "fn"] += 1
            s["cov_tp"] += cov
            if adv:
                s["adv_gold"] += 1
                s["adv_tp"] += hit or cov
            by_lang[c["lang"]][0 if hit else 2] += 1
        for f in pred:
            if (f.entity, f.start, f.end) not in gset:
                per[f.entity]["fp"] += 1
                by_lang[c["lang"]][1] += 1
        vault = Vault("eval")
        out_text, reversible = tokenize_all(text, pred, vault)
        leaked = [e for e in gold if _leaked(e, out_text)]
        for e in leaked:
            per[e["type"]]["leaks"] += 1
        if reversible:
            rt_total += 1
            rt_ok += rehydrate_text(out_text, vault)[0] == text
        expect = "redact" if gold else "allow"
        got = "redact" if pred else "allow"
        case_ok += expect == got
        if "hard-negative" in c["tags"]:
            neg_total += 1
            neg_fp += bool(pred)
        for tag in c["tags"]:
            if re.fullmatch(r"A[0-9]{1,2}", tag):
                by_tech[tag]["cases"] += 1
                by_tech[tag]["ok"] += (gset == pset) and not leaked
        if gset != pset or leaked:
            failures.append(
                {
                    "id": c["id"],
                    "missing": sorted(gset - pset),
                    "extra": sorted(pset - gset),
                    "leaked_types": [e["type"] for e in leaked],
                }
            )
    rows = []
    for ent, s in sorted(per.items()):
        p, r, f = prf(s["tp"], s["fp"], s["fn"])
        _, cr, _ = prf(s["cov_tp"], s["fp"], s["gold"] - s["cov_tp"])
        rows.append(
            {
                "entity": ent,
                "data_class": E.data_class(ent),
                "validated": ent in VALIDATED_ENTITIES,
                "gold": s["gold"],
                "tp": s["tp"],
                "fp": s["fp"],
                "fn": s["fn"],
                "precision": round(p, 4),
                "recall": round(r, 4),
                "f1": round(f, 4),
                "covering_recall": round(cr, 4),
                "leak_rate": round(s["leaks"] / s["gold"], 4) if s["gold"] else 0.0,
                "adversarial_recall": round(s["adv_tp"] / s["adv_gold"], 4)
                if s["adv_gold"]
                else None,
            }
        )
    TP = sum(s["tp"] for s in per.values())
    FP = sum(s["fp"] for s in per.values())
    FN = sum(s["fn"] for s in per.values())
    P, R, F = prf(TP, FP, FN)
    gold_total = sum(s["gold"] for s in per.values())
    leaks_total = sum(s["leaks"] for s in per.values())
    vgold = sum(s["gold"] for t, s in per.items() if t in VALIDATED_ENTITIES)
    vleaks = sum(s["leaks"] for t, s in per.items() if t in VALIDATED_ENTITIES)
    vrecall = prf(
        sum(s["tp"] for t, s in per.items() if t in VALIDATED_ENTITIES),
        0,
        sum(s["fn"] for t, s in per.items() if t in VALIDATED_ENTITIES),
    )[1]
    ls = sorted(lat)
    benign = load_benign()
    benign_fp = sum(1 for b in benign if _detect(det, b.get("text", "")))
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "cases": len(cases),
        "gold": gold_total,
        "ner_loaded": False,
        "overall": {
            "precision": round(P, 4),
            "recall": round(R, 4),
            "f1": round(F, 4),
            "tp": TP,
            "fp": FP,
            "fn": FN,
            "leak_rate": round(leaks_total / gold_total, 6) if gold_total else 0.0,
            "leak_rate_validated": round(vleaks / vgold, 6) if vgold else 0.0,
            "validated_recall": round(vrecall, 4),
            "hard_negative_fp_rate": round(neg_fp / neg_total, 4) if neg_total else 0.0,
            "finance_benign_fp_rate": round(benign_fp / len(benign), 4) if benign else 0.0,
            "case_accuracy": round(case_ok / len(cases), 4) if cases else 0.0,
        },
        "hard_negatives": {"cases": neg_total, "with_findings": neg_fp},
        "finance_benign": {"cases": len(benign), "with_findings": benign_fp},
        "roundtrip": {"cases": rt_total, "exact": rt_ok},
        "latency_ms": {
            "p50": round(statistics.median(lat), 3) if lat else 0.0,
            "p95": round(ls[int(0.95 * (len(ls) - 1))], 3) if ls else 0.0,
            "max": round(ls[-1], 3) if ls else 0.0,
            "avg_chars": round(statistics.fmean(len(c["text"]) for c in cases), 1) if cases else 0,
        },
        "by_entity": rows,
        "by_lang": {
            k: {
                "precision": round(p, 4),
                "recall": round(r, 4),
                "f1": round(f, 4),
                "gold": v[0] + v[2],
            }
            for k, v in sorted(by_lang.items())
            for p, r, f in [prf(*v)]
        },
        "adversarial": {
            k: round(v["ok"] / v["cases"], 4) if v["cases"] else None
            for k, v in sorted(by_tech.items(), key=lambda kv: int(kv[0][1:]))
        },
        "ner": evaluate_ner(cases),
        "failures": failures,
    }


def evaluate_ner(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """PERSON / ADDRESS gold labels vs the deterministic NER fallback (covering match)."""
    from . import ner_fallback

    per: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # tp fp fn
    for c in cases:
        gold = [e for e in c["entities"] if e["type"] in NER_EVAL]
        pred = [s for s in ner_fallback.detect(c["text"], NER_EVAL) if s.entity in NER_EVAL]
        for e in gold:
            hit = any(
                p.entity == e["type"] and p.start <= e["start"] + 1 and p.end >= e["end"] - 1
                for p in pred
            )
            per[e["type"]][0 if hit else 2] += 1
        for p in pred:
            if not any(
                e["type"] == p.entity and p.start < e["end"] and e["start"] < p.end for e in gold
            ):
                per[p.entity][1] += 1
    out = {}
    for ent, (tp, fp, fn) in sorted(per.items()):
        p, r, f = prf(tp, fp, fn)
        out[ent] = {
            "tier": "heuristic",
            "gold": tp + fn,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f, 4),
        }
    return out


def bench(reps: int = 30) -> dict[str, Any]:
    """Tier-D latency (1/4/16 KB prose + code), engine cache on a 20-turn transcript,
    mask_for_log on 2 KB."""
    from .engine import create

    det = Scanner()
    cases = load_fixtures()
    prose = " ".join(c["text"] for c in cases if c["lang"] in ("pl", "en"))
    code = "\n".join(c["text"] for c in cases if c["lang"] == "code")
    out: dict[str, Any] = {}
    for label, src in (("prose", prose), ("code", code)):
        for kb in (1, 4, 16):
            txt = (src * (1 + kb * 1024 // max(1, len(src))))[: kb * 1024]
            ts = []
            for _ in range(reps):
                t0 = time.perf_counter()
                det.detect(txt)
                ts.append((time.perf_counter() - t0) * 1000)
            ts.sort()
            out[f"{label}_{kb}kb"] = {
                "p50": round(statistics.median(ts), 3),
                "p95": round(ts[int(0.95 * (len(ts) - 1))], 3),
            }
    eng = create(None)
    turns = [c["text"] for c in cases[:20]]
    for k in range(1, len(turns) + 1):  # Claude Code resends the whole history every turn
        for t in turns[:k]:
            eng.scan(t)
    hits, misses = eng.cache_hits, eng.cache_misses
    out["transcript_cache"] = {
        "turns": len(turns),
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / max(1, hits + misses), 4),
    }
    two_kb = (prose * 2)[:2048]
    ts = []
    for _ in range(reps):
        eng._cache.clear()
        t0 = time.perf_counter()
        eng.mask_for_log(two_kb, max_len=160)
        ts.append((time.perf_counter() - t0) * 1000)
    out["mask_for_log_2kb_ms"] = round(statistics.median(ts), 3)
    return out


def results_markdown(m: dict[str, Any]) -> str:
    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{100 * x:.1f}%"

    o = m["overall"]
    lines = [
        "# Aegis redaction engine - detection quality",
        "",
        f"Generated {m['generated_at']} · {m['cases']} labelled cases · {m['gold']} gold spans · "
        f"latency p50 {m['latency_ms']['p50']} ms / p95 {m['latency_ms']['p95']} ms",
        "",
        f"**Overall** P={o['precision']:.3f} R={o['recall']:.3f} F1={o['f1']:.3f} · "
        f"leak {pct(o['leak_rate'])} (validated {pct(o['leak_rate_validated'])}) · "
        f"hard-negative FP {pct(o['hard_negative_fp_rate'])} · "
        f"finance-benign FP {pct(o['finance_benign_fp_rate'])}",
        "",
        "| Entity | Class | Validated | Gold | TP | FP | FN | Precision | Recall | F1 | Leak | Adv. recall |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in sorted(m["by_entity"], key=lambda r: (not r["validated"], r["entity"])):
        lines.append(
            f"| {r['entity']} | {r['data_class']} | {'yes' if r['validated'] else 'ctx'} | "
            f"{r['gold']} | {r['tp']} | {r['fp']} | {r['fn']} | {r['precision']:.3f} | "
            f"{r['recall']:.3f} | {r['f1']:.3f} | {pct(r['leak_rate'])} | "
            f"{pct(r['adversarial_recall'])} |"
        )
    lines += [
        "",
        "Adversarial techniques: "
        + ", ".join(f"{k} {pct(v)}" for k, v in m["adversarial"].items()),
    ]
    if m.get("ner"):
        lines += ["", "NER tier (deterministic heuristic fallback):"]
        for ent, r in m["ner"].items():
            lines.append(f"- {ent}: P={r['precision']:.3f} R={r['recall']:.3f} (gold {r['gold']})")
    if m.get("bench"):
        lines += ["", "Bench: " + json.dumps(m["bench"])]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- cached metrics (API)
_metrics_cache: dict[str, Any] | None = None


def public_metrics(m: dict[str, Any]) -> dict[str, Any]:
    """RedactionMetrics shape for GET /api/redaction/metrics (no failure details)."""
    keys = (
        "generated_at",
        "cases",
        "gold",
        "ner_loaded",
        "overall",
        "latency_ms",
        "by_entity",
        "by_lang",
        "adversarial",
        "ner",
        "hard_negatives",
        "finance_benign",
        "roundtrip",
        "bench",
    )
    out = {k: m[k] for k in keys if k in m}
    lat = dict(out.get("latency_ms") or {})
    b = (m.get("bench") or {}).get("prose_1kb")
    if b:
        lat.setdefault("per_kb_p95", b.get("p95"))
    out["latency_ms"] = lat
    return out


def get_metrics(refresh: bool = False) -> dict[str, Any]:
    """Latest ``reports/dlp-metrics.json`` if newer than the code, else computed (cached)."""
    global _metrics_cache
    if _metrics_cache is not None and not refresh:
        return _metrics_cache
    report = REPORTS / "dlp-metrics.json"
    code_mtime = max(p.stat().st_mtime for p in HERE.glob("*.py"))
    if not refresh and report.exists() and report.stat().st_mtime >= code_mtime:
        try:
            _metrics_cache = public_metrics(json.loads(report.read_text(encoding="utf-8")))
            _metrics_cache["source"] = "report"
            return _metrics_cache
        except (OSError, ValueError):
            pass
    _metrics_cache = public_metrics(evaluate())
    _metrics_cache["source"] = "computed"
    return _metrics_cache


def check(m: dict[str, Any]) -> list[str]:
    """--check gate: validated recall 1.0, leak 0, hard-negative FP 0."""
    o = m["overall"]
    problems = []
    if o["validated_recall"] < 1.0:
        problems.append(f"validated-type recall {o['validated_recall']:.4f} < 1.0")
    if o["leak_rate"] > 0:
        problems.append(f"leak rate {o['leak_rate']:.4%} > 0")
    if o["hard_negative_fp_rate"] > 0:
        problems.append(f"hard-negative FP rate {o['hard_negative_fp_rate']:.2%} > 0")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aegis.redaction.evaluate")
    ap.add_argument("--check", action="store_true", help="exit 1 unless recall/leak/FP gates hold")
    ap.add_argument("--bench", action="store_true", help="add latency + cache benchmarks")
    ap.add_argument("--write", action="store_true", help="write reports/dlp-metrics.{json,md}")
    ap.add_argument("--failures", action="store_true", help="print failing case ids")
    args = ap.parse_args(argv)
    m = evaluate()
    if args.bench:
        m["bench"] = bench()
    o = m["overall"]
    sys.stdout.write(
        f"cases={m['cases']} gold={m['gold']} P={o['precision']:.3f} R={o['recall']:.3f} "
        f"F1={o['f1']:.3f} validated_recall={o['validated_recall']:.3f} "
        f"leak={o['leak_rate']:.4%} hardneg_fp={o['hard_negative_fp_rate']:.2%} "
        f"finance_benign_fp={m['finance_benign']['with_findings']}/{m['finance_benign']['cases']} "
        f"p50={m['latency_ms']['p50']}ms p95={m['latency_ms']['p95']}ms\n"
    )
    if args.bench:
        sys.stdout.write("bench " + json.dumps(m["bench"]) + "\n")
    if args.failures:
        for f in m["failures"]:
            sys.stdout.write(json.dumps(f) + "\n")
    if args.write:
        REPORTS.mkdir(parents=True, exist_ok=True)
        pub = public_metrics(m)
        (REPORTS / "dlp-metrics.json").write_text(json.dumps(pub, indent=2), encoding="utf-8")
        (REPORTS / "dlp-metrics.md").write_text(results_markdown(m), encoding="utf-8")
        sys.stdout.write(f"wrote {REPORTS / 'dlp-metrics.json'} and dlp-metrics.md\n")
    if args.check:
        problems = check(m)
        for p in problems:
            sys.stdout.write(f"CHECK FAILED: {p}\n")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
