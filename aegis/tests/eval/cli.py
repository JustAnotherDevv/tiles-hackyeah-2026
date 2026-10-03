"""`python -m tests.eval` - red-team evaluation of the real Aegis pipeline (plan 19 §2.11).

Default (`make eval`): deterministic x 4 profiles x all rows + DLP leak leg, then semantic `auto`
on balanced + strict with a stratified sample under a time budget. `--quick`: balanced only.
Exit code 0 even when rates are low (non-gating); `--strict` exits 1 on errors > 1 % or a missing
runtime. Never writes a number that was not measured: if the runtime cannot boot, the report
says `status: unavailable` with the reason.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
import time
from pathlib import Path
from typing import Any

from tests.eval.common import ROOT, machine_info, now_iso, reports_dir, write_json_atomic

DEFAULT_PROFILES = ["permissive", "balanced", "strict", "paranoid"]
SAMPLES_DIR = Path(__file__).resolve().parent / "samples"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m tests.eval", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profiles", default=",".join(DEFAULT_PROFILES))
    ap.add_argument("--semantic", choices=["off", "auto", "on"], default="auto",
                    help="semantic stage (default auto: runs only if >= 2 GB free and models present)")
    ap.add_argument("--sem-profiles", default="balanced,strict")
    ap.add_argument("--sample-sem", type=int, default=200)
    ap.add_argument("--time-budget-s", type=float, default=150.0, help="semantic stage budget")
    ap.add_argument("--subsets", default="public,handwritten,generated,pii,secrets")
    ap.add_argument("--target", default="inproc", help="inproc | http://127.0.0.1:8787 (guard dry-run)")
    ap.add_argument("--agent", default="chaos-agent@platform")
    ap.add_argument("--prompt-surface", default="model.request", choices=["model.request", "prompt.user"])
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", default=None, help="reports dir (default $AEGIS_REPORTS_DIR or reports/)")
    ap.add_argument("--quick", action="store_true", help="deterministic balanced only, no DLP leg (~15 s)")
    ap.add_argument("--no-html", action="store_true")
    ap.add_argument("--no-dlp", action="store_true")
    ap.add_argument("--dlp", action="store_true", help="run the DLP leak leg even with --quick")
    ap.add_argument("--write-samples", action="store_true")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    if a.quick:
        a.profiles = "balanced"
        a.semantic = "off"
        if not a.dlp:
            a.no_dlp = True
    return a


def corpora_meta(subsets: list[str]) -> dict[str, Any]:
    from tests.corpora.loader import load_manifest

    man = load_manifest()
    files = []
    rows = 0
    for rel, m in sorted(man.get("files", {}).items()):
        if rel.split("/")[0] not in subsets:
            continue
        files.append({"file": rel, **{k: m.get(k) for k in ("rows", "attack", "benign", "licence", "sha256",
                                                              "seen_by_tuning")}})
        if not rel.startswith("pii/"):
            rows += m.get("rows") or 0
    if "secrets" in subsets:
        files.append({"file": "secrets_gen (runtime, in memory)", "rows": 40, "attack": 40, "benign": 0,
                      "licence": "Aegis-original", "sha256": None, "seen_by_tuning": False})
    return {"rows": rows, "files": files, "pii_dropped": man.get("pii_dropped")}


async def _maybe_await(x: Any) -> Any:
    return await x if inspect.isawaitable(x) else x


async def semantic_status(rt: Any) -> dict[str, Any] | None:
    sem = getattr(rt, "semantic", None)
    fn = getattr(sem, "status", None)
    if not callable(fn):
        return None
    try:
        st = await _maybe_await(fn())
        return st if isinstance(st, dict) else {"raw": str(st)}
    except Exception as e:
        return {"error": repr(e)}


def semantic_label(st: dict[str, Any] | None) -> str:
    if not st:
        return "semantic (degraded: no status)"
    models = st.get("models") or []
    usable = [m for m in models if (m.get("state") in ("ready", "loaded", "ok") or m.get("loaded"))]
    if st.get("degraded") and not usable:
        why = st.get("health") or "degraded"
        return f"semantic (degraded: {why})"
    if st.get("mode") == "off":
        return "semantic (degraded: off)"
    return "semantic"


class Ctx:
    def __init__(self, a: argparse.Namespace):
        self.a = a
        self.subsets = [s.strip() for s in a.subsets.split(",") if s.strip()]
        self.runs: list[dict[str, Any]] = []
        self.dlp_runs: list[dict[str, Any]] = []
        self.raw: list[dict[str, Any]] = []  # {profile, mode, results} for heatmap
        self.log: list[str] = []

    def say(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)
        self.log.append(msg)


async def eval_one(c: Ctx, rt: Any, profile: str, mode: str, cases: list, dlp_cases: list, gold: dict, *,
                   deadline: float | None = None, sampled: bool = False, extra: dict | None = None) -> None:
    from tests.eval.dlp import score as dlp_score
    from tests.eval.metrics import aggregate
    from tests.eval.runner import run_inprocess

    t0 = time.perf_counter()
    res = await run_inprocess(rt, cases, profile=profile, mode=mode, concurrency=c.a.concurrency, deadline=deadline)
    summ = aggregate(res)
    snap = rt.policy.snapshot()
    run = {"profile": profile, "mode": mode, "status": "ok", "summary": summ, "sampled": sampled,
           "policy_version": getattr(snap, "version", None), "feed_serial": getattr(rt.feed, "serial", None)
           if getattr(rt, "feed", None) is not None else None, "duration_s": round(time.perf_counter() - t0, 2),
           **(extra or {})}
    c.runs.append(run)
    c.raw.append({"profile": profile, "mode": mode, "results": res})
    ov = summ["overall"]
    c.say(f"  {profile:<10} {mode:<14} n={summ['n']:<5} attack {ov['attack']['rate']} FPR {ov['benign']['fpr']} "
          f"errors {summ['errors']} ({run['duration_s']} s)")
    if dlp_cases:
        dres = await run_inprocess(rt, dlp_cases, profile=profile, mode=mode, concurrency=c.a.concurrency,
                                   deadline=deadline, keep_segments=True)
        d = dlp_score(dres, gold, profile, mode)
        c.dlp_runs.append(d)
        c.say(f"  {'':<10} DLP leak leg: {d['leaked_entities']}/{d['entities']} leaked, hard-neg FPR "
              f"{d['hard_negatives']['fpr']}")


async def run_inproc(c: Ctx) -> None:
    from tests.corpora.loader import load_rows
    from tests.eval.adapter import to_cases
    from tests.eval.dlp import load_dlp_rows
    from tests.eval.harness import (
        active_profile,
        hermetic_runtime,
        semantic_preflight,
        switch_profile,
    )
    from tests.eval.metrics import stratified_sample

    a = c.a
    rows = load_rows(subsets=[s for s in c.subsets if s != "pii"])
    dlp_rows, gold = ([], {}) if (a.no_dlp or "pii" not in c.subsets) else load_dlp_rows()
    profiles = [p.strip() for p in a.profiles.split(",") if p.strip()]
    order = (["balanced"] if "balanced" in profiles else []) + [p for p in profiles if p != "balanced"]
    c.say(f"aegis eval: {len(rows)} rows + {len(dlp_rows)} DLP rows; profiles {order}; semantic={a.semantic}")
    t_boot = time.perf_counter()
    async with hermetic_runtime(order[0], semantic="off") as h:
        c.say(f"  runtime booted in {h.boot_s:.1f} s (policy v{h.rt.policy.snapshot().version}, "
              f"{len(h.rt.controls.all())} controls)")
        doc = h.rt.policy.snapshot().doc
        cases = to_cases(rows, prompt_surface=a.prompt_surface, agent_id=a.agent, doc=doc)
        dlp_cases = to_cases(dlp_rows, prompt_surface=a.prompt_surface, agent_id=a.agent, doc=doc)
        fresh: list[str] = []
        for i, p in enumerate(order):
            sw = None
            if i > 0 or active_profile(h.rt) != p:
                sw = await switch_profile(h, p)
                if sw["status"] not in ("applied", "noop"):
                    c.say(f"  {p}: apply_yaml {sw['status']} ({'; '.join(sw.get('errors') or [])[:160]}) -> fresh boot")
                    fresh.append(p)
                    continue
            await eval_one(c, h.rt, p, "deterministic", cases, dlp_cases, gold, extra={"switch": sw})
    for p in fresh:  # profiles the self-test gate rejected via apply: boot directly on that file
        async with hermetic_runtime(p, semantic="off") as h2:
            if active_profile(h2.rt) != p:
                c.runs.append({"profile": p, "mode": "deterministic", "status": "unavailable",
                               "reason": f"fresh boot came up with profile {active_profile(h2.rt)!r}"})
                continue
            doc = h2.rt.policy.snapshot().doc
            cases = to_cases(rows, prompt_surface=a.prompt_surface, agent_id=a.agent, doc=doc)
            dlp_cases = to_cases(dlp_rows, prompt_surface=a.prompt_surface, agent_id=a.agent, doc=doc)
            await eval_one(c, h2.rt, p, "deterministic", cases, dlp_cases, gold,
                           extra={"switch": {"status": "fresh_boot", "note": "apply_yaml self-test gate rejected the "
                                                                              "profile switch; booted on the file"}})
    c.say(f"  deterministic stage {time.perf_counter() - t_boot:.1f} s")

    if a.semantic == "off":
        return
    sem_profiles = [p.strip() for p in a.sem_profiles.split(",") if p.strip()]
    reason = semantic_preflight()
    if reason and a.semantic == "auto":
        for p in sem_profiles:
            c.runs.append({"profile": p, "mode": "semantic", "status": "skipped", "skipped": reason})
        c.say(f"  semantic stage skipped: {reason}")
        return
    deadline = time.monotonic() + a.time_budget_s
    async with hermetic_runtime(sem_profiles[0], semantic="on" if a.semantic == "on" else "auto") as h:
        warm = getattr(getattr(h.rt, "semantic", None), "warmup", None)
        if callable(warm):
            try:
                await asyncio.wait_for(_maybe_await(warm()), timeout=min(120.0, a.time_budget_s))
            except Exception as e:
                c.say(f"  semantic warmup: {e!r}")
        st = await semantic_status(h.rt)
        label = semantic_label(st)
        doc = h.rt.policy.snapshot().doc
        sample = stratified_sample(rows, a.sample_sem, key=lambda r: (r.top_category, r.lang, r.label))
        cases = to_cases(sample, prompt_surface=a.prompt_surface, agent_id=a.agent, doc=doc)
        for i, p in enumerate(sem_profiles):
            if time.monotonic() > deadline:
                c.runs.append({"profile": p, "mode": "semantic", "status": "skipped",
                               "skipped": f"time budget {a.time_budget_s:.0f} s exhausted"})
                continue
            if i > 0:
                sw = await switch_profile(h, p)
                if sw["status"] not in ("applied", "noop"):
                    c.runs.append({"profile": p, "mode": "semantic", "status": "rejected", "switch": sw})
                    continue
            await eval_one(c, h.rt, p, label, cases, [], {}, deadline=deadline, sampled=True,
                           extra={"semantic_status": await semantic_status(h.rt)})


async def run_http_target(c: Ctx) -> None:
    import httpx

    from tests.corpora.loader import load_rows
    from tests.eval.adapter import to_cases
    from tests.eval.metrics import aggregate
    from tests.eval.runner import run_http

    a = c.a
    base = a.target.rstrip("/")
    rows = load_rows(subsets=[s for s in c.subsets if s != "pii"])
    cases = to_cases(rows, prompt_surface=a.prompt_surface, agent_id=a.agent)
    profile, version = "live", None
    try:
        async with httpx.AsyncClient(base_url=base, timeout=5) as cl:
            hz = (await cl.get("/healthz")).json()
            version = hz.get("policy_version")
            try:
                pol = (await cl.get("/api/policy")).json()
                profile = pol.get("profile") or (pol.get("snapshot") or {}).get("profile") or profile
            except Exception:
                pass
    except Exception as e:
        c.runs.append({"profile": "live", "mode": "live", "status": "unavailable", "reason": f"{base}: {e!r}"})
        return
    c.say(f"aegis eval (live {base}, policy v{version}, profile {profile}): {len(cases)} cases, guard dry-run")
    t0 = time.perf_counter()
    res = await run_http(base, cases, profile=str(profile), mode="live", concurrency=a.concurrency)
    summ = aggregate(res)
    c.runs.append({"profile": str(profile), "mode": "live", "status": "ok", "summary": summ,
                   "policy_version": version, "target": base, "duration_s": round(time.perf_counter() - t0, 2)})
    c.raw.append({"profile": str(profile), "mode": "live", "results": res})


def unavailable_doc(reason: str, a: argparse.Namespace) -> dict[str, Any]:
    from tests.corpora.loader import attribution_lines

    return {"schema": "aegis.eval/1", "generated_at": now_iso(), "duration_s": None, "status": "unavailable",
            "reason": reason, "machine": machine_info(), "corpora": corpora_meta(a.subsets.split(",")),
            "runs": [{"profile": p, "mode": "deterministic", "status": "unavailable", "reason": reason}
                     for p in a.profiles.split(",")], "dlp": None, "heatmap": None, "attribution": attribution_lines()}


def write_samples(out_dir: Path) -> None:
    SAMPLES_DIR.mkdir(exist_ok=True)
    for name in ("bench", "eval", "heatmap"):
        p = out_dir / f"{name}.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            d["sample"] = True
            d["sample_note"] = f"copied from a real run ({d.get('generated_at')}) for dashboard mocks"
            write_json_atomic(SAMPLES_DIR / f"{name}.sample.json", d)


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    out_dir = reports_dir(a.out)
    t0 = time.perf_counter()
    c = Ctx(a)
    try:
        import aegis.app  # noqa: F401
    except Exception as e:
        doc = unavailable_doc(f"aegis.app not importable: {e!r}", a)
        write_json_atomic(out_dir / "eval.json", doc)
        print(f"eval unavailable: {doc['reason']}", file=sys.stderr)
        return 1 if a.strict else 0
    from tests.corpora.loader import attribution_lines, verify_manifest
    from tests.eval.heatmap import build_heatmap
    from tests.eval.report import build_eval_json, console, write_eval_reports

    drift = verify_manifest()
    if drift:
        c.say(f"WARNING corpus drift vs MANIFEST: {drift[:3]}")
    try:
        if a.target == "inproc":
            asyncio.run(run_inproc(c))
        else:
            asyncio.run(run_http_target(c))
    except Exception as e:  # boot failure etc. -> honest "unavailable"
        import traceback

        traceback.print_exc()
        doc = unavailable_doc(f"runtime failed: {type(e).__name__}: {e}", a)
        write_json_atomic(out_dir / "eval.json", doc)
        return 1 if a.strict else 0

    hm = build_heatmap(c.raw)
    dlp = None
    if c.dlp_runs:
        from tests.eval.dlp import detector_metrics_summary

        dlp = {"runs": c.dlp_runs, "detector_metrics": detector_metrics_summary(out_dir),
               "definition": "gold value still present (verbatim, normalized, or >=6-digit subsequence) in the "
                             "post-redaction segments that would leave toward a remote model; blocked = not leaked"}
    meta = {"generated_at": now_iso(), "duration_s": round(time.perf_counter() - t0, 1),
            "machine": machine_info(), "corpora": corpora_meta(c.subsets), "target": a.target,
            "agent": a.agent, "prompt_surface": a.prompt_surface, "corpus_drift": drift,
            "scoring": "tests/eval/scoring.py (plan 19 §2.6): detection needs a non-bookkeeping enforce-mode "
                       "control; AEGIS-CORE fail-closed = error", "attribution": attribution_lines()}
    doc = build_eval_json(meta, c.runs, dlp, hm)
    written = write_eval_reports(out_dir, doc, html=not a.no_html)
    from tests.eval import deck

    deck.write(out_dir)
    console(doc)
    if a.write_samples:
        write_samples(out_dir)
    print("wrote " + ", ".join(str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
                               for p in [*written, out_dir / "deck_numbers.md"]), file=sys.stderr)
    if a.strict:
        tot = sum(r.get("n") or 0 for r in doc["runs"])
        errs = sum(r.get("errors") or 0 for r in doc["runs"])
        if not any(r.get("status") == "ok" for r in doc["runs"]) or (tot and errs / tot > 0.01):
            return 1
    return 0


__all__ = ["main"]
