"""`python scripts/bench.py` - gateway overhead / throughput benchmark -> reports/bench.json (plan 19 §2.9).

Default (`make bench`): echo upstream (port 0) -> spawned gateway (deterministic, ephemeral port) ->
guard c1/c16, OpenAI proxy vs direct, 800 ms-upstream share, file->active reload -> stop ->
in-process micro per-control + apply latency -> spawned semantic gateway (if >= 2 GB free and
models present) -> stop -> bench.json/md/html + deck numbers. One gateway at a time; every
process we start is stopped. Never fabricates: failures produce `status: unavailable|partial`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

from tests.eval.common import BENCH_SCHEMA, machine_info, now_iso, reports_dir

LOADGEN = "co-located asyncio httpx closed-loop, concurrency <= 16"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="scripts/bench.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", default="spawn", help="spawn | inproc | http://127.0.0.1:8787 (live, guard dry-run)")
    ap.add_argument("--modes", default="deterministic,semantic")
    ap.add_argument("--quick", action="store_true", help="guard-det-c1 (500 req) + guard-det-c16 (5 s), ~25 s")
    ap.add_argument("--no-micro", action="store_true")
    ap.add_argument("--no-reload", action="store_true")
    ap.add_argument("--no-proxy", action="store_true", help="skip OpenAI proxy vs direct + 800 ms share")
    ap.add_argument("--sizes", action="store_true", help="payload-size profile 0.5/2/8/32 KB")
    ap.add_argument("--upstream-delay-ms", type=float, default=800.0)
    ap.add_argument("--requests", type=int, default=None, help="override guard-det-c1 request count")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-html", action="store_true")
    return ap.parse_args(argv)


def say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _line(p: dict[str, Any]) -> str:
    o = p.get("overhead_ms") or {}
    return (f"  {p['name']:<22} n={p['requests']:<5} err={p['errors']:<3} rps={p.get('rps')!s:<7} "
            f"overhead p50={o.get('p50')} p95={o.get('p95')} p99={o.get('p99')} ms")


async def det_stage(a: argparse.Namespace, target: Any, up: Any, slow: Any, mix: list, doc: dict) -> None:
    from tests.bench.profiles import ProfileSpec, run_profile

    q = a.quick
    specs = [ProfileSpec("guard-det-c1", "POST /v1/guard, record path on, c=1", "deterministic", "/v1/guard", 1,
                         requests=a.requests or (500 if q else 1500), warmup=30 if q else 50),
             ProfileSpec("guard-det-c16", "POST /v1/guard, c=16, fixed duration (throughput)", "deterministic",
                         "/v1/guard", 16, duration_s=5 if q else 10, warmup=0)]
    if target.kind == "live":
        specs = [ProfileSpec("guard-live-c1", "live gateway, guard dry-run", "live", "/v1/guard", 1,
                             requests=a.requests or 300, warmup=10, dry_run=True),
                 ProfileSpec("guard-live-c4", "live gateway, guard dry-run, c=4", "live", "/v1/guard", 4,
                             duration_s=5, dry_run=True)]
    async with target.client() as cl:
        for s in specs:
            p = await run_profile(cl, s, mix, tag="d")
            doc["profiles"].append(p)
            say(_line(p))
        if q or a.no_proxy or target.kind == "live" or up is None:
            return
        import httpx

        async with httpx.AsyncClient(base_url=up.url, timeout=30) as direct:
            pa = await run_profile(cl, ProfileSpec("openai-det-c1", "POST /v1/chat/completions mock-echo via Aegis",
                                                   "deterministic", "/v1/chat/completions", 1, requests=500, warmup=20),
                                   mix, tag="o")
            pd = await run_profile(cl, ProfileSpec("direct-c1", "same mix straight to the echo upstream", "direct",
                                                   "direct", 1, requests=500, warmup=20), mix, direct_client=direct)
            for p in (pa, pd):
                doc["profiles"].append(p)
                say(_line(p))
            pa["client_overhead_vs_direct_ms"] = {
                k: (None if pa["client_ms"].get(k) is None or pd["client_ms"].get(k) is None
                    else round(pa["client_ms"][k] - pd["client_ms"][k], 3)) for k in ("p50", "p95")}
        if slow is not None:
            share_src = None
            for spec in (ProfileSpec("openai-det-800ms-c1",
                                     f"proxy with a simulated {a.upstream_delay_ms:.0f} ms upstream, c=1",
                                     "deterministic", "/v1/chat/completions", 1, requests=12, warmup=2,
                                     model="mock-slow-echo"),
                         ProfileSpec("openai-det-800ms-c16",
                                     f"proxy with a simulated {a.upstream_delay_ms:.0f} ms upstream, c=16",
                                     "deterministic", "/v1/chat/completions", 16, requests=64, warmup=0,
                                     model="mock-slow-echo")):
                ps = await run_profile(cl, spec, mix, tag="s")
                doc["profiles"].append(ps)
                say(_line(ps))
                share_src = share_src or ps
            ps = share_src
            ov = ps["overhead_ms"].get("p50")
            tot = ps["client_ms"].get("p50")
            if ov is not None and tot:
                doc["overhead_share"] = {"upstream_delay_ms": a.upstream_delay_ms, "aegis_p50_ms": ov,
                                         "total_p50_ms": tot, "share_pct": round(100 * ov / tot, 2),
                                         "upstream_p50_ms": (ps.get("upstream_ms") or {}).get("p50"),
                                         "profile": ps["name"],
                                         "note": "simulated upstream (echo with fixed delay); overhead from "
                                                 "Server-Timing aegis; c=1"}


async def inproc_stage(a: argparse.Namespace, doc: dict, kinds: dict) -> list[dict[str, Any]]:
    """Micro per-control + apply latency on an in-process deterministic runtime."""
    from tests.bench.micro import run_micro
    from tests.bench.reload import apply_latency
    from tests.eval.harness import hermetic_runtime

    micro: list[dict[str, Any]] = []
    async with hermetic_runtime("balanced", semantic="off") as h:
        for c in h.rt.controls.all():
            kinds[c.id] = getattr(c, "kind", None)
        if not a.no_micro:
            t0 = time.perf_counter()
            micro = await run_micro(h.rt, n_prompts=40 if a.quick else 120)
            say(f"  micro-bench: {len(micro)} controls in {time.perf_counter() - t0:.1f} s")
        if not a.no_reload:
            doc.setdefault("reload", {})["apply_ms"] = await apply_latency(h.rt, n=4 if a.quick else 10)
            say(f"  apply_yaml latency: {doc['reload']['apply_ms']}")
    return micro


async def sem_stage(a: argparse.Namespace, mix: list, doc: dict, up: Any) -> dict[str, Any]:
    from tests.bench.profiles import ProfileSpec, run_profile
    from tests.bench.targets import SpawnTarget
    from tests.eval.harness import semantic_preflight

    reason = semantic_preflight()
    if reason:
        say(f"  semantic stage skipped: {reason}")
        return {"skipped": reason, "degraded": None}
    meta: dict[str, Any] = {"skipped": None}
    t = SpawnTarget(profile="balanced", semantic="auto", upstream_url=up.url if up else None)
    try:
        await asyncio.to_thread(t.start)
        import httpx

        async with t.client() as cl:
            try:  # best-effort warm-up endpoint (A-44, could)
                await cl.post("/api/semantic/warmup", json={}, timeout=120)
            except httpx.HTTPError:
                pass
            for s in (ProfileSpec("guard-sem-c1", "POST /v1/guard, semantic tier on, c=1", "semantic", "/v1/guard", 1,
                                  requests=100 if a.quick else 300, warmup=20),
                      ProfileSpec("guard-sem-c4", "POST /v1/guard, semantic, c=4, fixed duration", "semantic",
                                  "/v1/guard", 4, duration_s=5 if a.quick else 10)):
                p = await run_profile(cl, s, mix, tag="sem")
                doc["profiles"].append(p)
                say(_line(p))
            try:
                st = (await cl.get("/api/semantic/status")).json()
            except Exception as e:
                st = {"error": repr(e)}
        meta["status"] = st
        meta["degraded"] = st.get("degraded") if isinstance(st, dict) else None
        meta["models"] = [{k: m.get(k) for k in ("name", "state", "p50_ms", "p95_ms", "calls", "fallbacks",
                                                   "escalations")} for m in (st.get("models") or [])] \
            if isinstance(st, dict) else []
        meta["gateway_rss_mb"] = t.rss_mb()
    except Exception as e:
        meta = {"skipped": f"semantic gateway failed: {e!r}"[:400], "degraded": None}
        say(f"  {meta['skipped']}")
    finally:
        t.stop()
    return meta


async def run(a: argparse.Namespace) -> dict[str, Any]:
    from tests.bench.mix import build_mix
    from tests.bench.reload import file_to_active
    from tests.bench.report import load_snapshot, merge_by_control, models_block, modes_block
    from tests.bench.targets import InprocTarget, LiveTarget, SpawnTarget
    from tests.bench.upstream import EchoUpstream

    t_start = time.perf_counter()
    doc: dict[str, Any] = {"schema": BENCH_SCHEMA, "generated_at": now_iso(), "status": "ok",
                           "machine": machine_info(LOADGEN), "profiles": [], "by_control": []}
    modes = [m.strip() for m in a.modes.split(",") if m.strip()]
    mix = build_mix(400)
    kinds: dict[str, Any] = {}
    problems: list[str] = []
    up = slow = None
    sem_meta: dict[str, Any] = {"skipped": "not requested", "degraded": None}
    try:
        if not a.target.startswith("http"):
            up = EchoUpstream(0).start()
            slow = EchoUpstream(a.upstream_delay_ms).start() if not (a.quick or a.no_proxy) else None
        if a.target.startswith("http"):
            target = LiveTarget(a.target)
            doc["target"] = {"kind": "live", "url": target.base_url}
            await det_stage(a, target, None, None, mix, doc)
        elif "deterministic" in modes:
            ov = {"upstream_url": up.url, "slow_upstream_url": slow.url if slow else None}
            spawned = None
            if a.target == "spawn":
                spawned = SpawnTarget(profile="balanced", semantic="off", **ov)
                try:
                    await asyncio.to_thread(spawned.start)
                    say(f"  spawned gateway {spawned.base_url} in {spawned.boot_s:.1f} s (pid {spawned.proc_pid})")
                except Exception as e:
                    problems.append(f"spawn failed, fell back to inproc: {e!r}"[:400])
                    say(f"  {problems[-1]}")
                    spawned = None
            if spawned is not None:
                try:
                    hz = await asyncio.to_thread(lambda: __import__("httpx").get(f"{spawned.base_url}/healthz").json())
                    doc["target"] = {"kind": "spawn", "url": None, "policy_version": hz.get("policy_version"),
                                     "profile": "balanced", "feed_serial": hz.get("feed_serial"),
                                     "boot_s": round(spawned.boot_s or 0, 2)}
                    await det_stage(a, spawned, up, slow, mix, doc)
                    doc["target"]["gateway_rss_mb"] = spawned.rss_mb()
                    if not a.no_reload and not a.quick:
                        doc.setdefault("reload", {})["file_to_active_ms"] = await asyncio.to_thread(
                            file_to_active, spawned.base_url, spawned.policy_path, n=5, **ov)
                        say(f"  file->active reload: {doc['reload']['file_to_active_ms']}")
                finally:
                    spawned.stop()
            else:
                async with InprocTarget(profile="balanced", semantic="off", **ov) as it:
                    doc["target"] = {"kind": "inproc", "url": None, "profile": "balanced",
                                     "policy_version": it.rt.policy.snapshot().version}
                    await det_stage(a, it, up, slow, mix, doc)
        if not a.target.startswith("http"):
            micro = await inproc_stage(a, doc, kinds)
            if "semantic" in modes:
                sem_meta = await sem_stage(a, mix, doc, up)
        else:
            micro = []
    finally:
        for u in (up, slow):
            if u is not None:
                u.stop()
    doc["by_control"] = merge_by_control(doc["profiles"], micro, kinds)
    doc["modes"] = modes_block(doc, sem_meta)
    doc["models"] = models_block(sem_meta.get("status") if isinstance(sem_meta.get("status"), dict) else None)
    doc["streaming"] = load_snapshot("streaming.snapshot.json")
    doc["duration_s"] = round(time.perf_counter() - t_start, 1)
    if problems:
        doc["problems"] = problems
    if not doc["profiles"]:
        doc["status"] = "unavailable"
    elif problems or any(p["errors"] > 0.01 * max(1, p["requests"]) for p in doc["profiles"]):
        doc["status"] = "partial"
    try:
        import psutil

        doc["machine"]["bench_peak_rss_mb"] = round(psutil.Process().memory_info().rss / 2**20, 1)
    except Exception:
        pass
    return doc


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    out_dir = reports_dir(a.out)
    say(f"aegis bench: target={a.target} modes={a.modes} quick={a.quick}")
    try:
        import aegis.app  # noqa: F401
    except Exception as e:
        doc = {"schema": BENCH_SCHEMA, "generated_at": now_iso(), "status": "unavailable",
               "reason": f"aegis.app not importable: {e!r}", "profiles": [], "machine": machine_info(LOADGEN)}
        from tests.bench.report import finalize

        finalize(out_dir, doc, html=not a.no_html)
        say(doc["reason"])
        return 0
    try:
        doc = asyncio.run(run(a))
    except Exception as e:
        import traceback

        traceback.print_exc()
        doc = {"schema": BENCH_SCHEMA, "generated_at": now_iso(), "status": "unavailable",
               "reason": f"bench failed: {type(e).__name__}: {e}"[:500], "profiles": [],
               "machine": machine_info(LOADGEN)}
    from tests.bench.report import finalize
    from tests.eval import deck

    paths = finalize(out_dir, doc, html=not a.no_html)
    deck.write(out_dir)
    h = doc.get("headline") or {}
    say(f"headline: det overhead p50={h.get('det_overhead_p50_ms')} p95={h.get('det_overhead_p95_ms')} ms, "
        f"rps={h.get('rps_det')}, share={h.get('overhead_share_pct')} %, sem p95={h.get('sem_overhead_p95_ms')} ms, "
        f"reload p95={h.get('reload_p95_ms')} ms")
    say("wrote " + ", ".join(str(p) for p in [*paths, out_dir / "deck_numbers.md"]))
    return 0


__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover
    sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[2] / "src")]
    raise SystemExit(main(sys.argv[1:]))
