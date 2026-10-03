"""Bench load profiles against a target (guard / OpenAI proxy / direct upstream)."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import httpx

from tests.bench.loadgen import Record, record_from_response, run_closed_loop
from tests.bench.mix import MixItem, guard_body, openai_body
from tests.bench.servertiming import controls as st_controls
from tests.eval.metrics import pct_summary

AGENT_HEADERS = {"X-Aegis-Agent": "chaos-agent@platform"}


@dataclass
class ProfileSpec:
    name: str
    description: str
    mode: str
    path: str  # /v1/guard | /v1/chat/completions | direct
    concurrency: int
    requests: int | None = None
    duration_s: float | None = None
    warmup: int = 0
    model: str = "mock-echo"
    dry_run: bool = False


def summarize(spec: ProfileSpec, recs: list[Record], elapsed_s: float, *, upstream: bool = False) -> dict[str, Any]:
    ok = [r for r in recs if r.error is None and r.status > 0]
    over = [r.overhead_ms for r in ok]
    srcs = Counter(r.overhead_source for r in ok)
    by_ctl: dict[str, list[float]] = defaultdict(list)
    for r in ok:
        if r.decisions:
            for cid, ms, _mode in r.decisions:
                by_ctl[cid].append(ms)
        else:
            for cid, ms in st_controls(r.timing).items():
                by_ctl[cid].append(ms)
    ctl_rows = []
    for cid, xs in sorted(by_ctl.items()):
        s = pct_summary(xs, ndigits=4)
        ctl_rows.append({"control_id": cid, "p50_ms": s["p50"], "p95_ms": s["p95"], "p99_ms": s["p99"],
                         "count": s["n"], "source": "pipeline" if any(r.decisions for r in ok) else "server_timing"})
    up = [r.timing["upstream"] for r in ok if "upstream" in r.timing] if upstream else []
    out = {
        "name": spec.name, "description": spec.description, "mode": spec.mode, "path": spec.path,
        "concurrency": spec.concurrency, "requests": len(recs), "errors": len(recs) - len(ok),
        "error_samples": sorted({(r.error or f"http {r.status}") for r in recs if r not in ok})[:3],
        "elapsed_s": round(elapsed_s, 2), "rps": round(len(ok) / elapsed_s, 1) if elapsed_s > 0 else None,
        "overhead_ms": pct_summary(over, ndigits=3), "overhead_source": dict(srcs),
        "client_ms": pct_summary([r.client_ms for r in ok], ndigits=3),
        "upstream_ms": pct_summary(up, ndigits=3) if up else None,
        "actions": dict(Counter(r.action for r in ok if r.action)),
        "by_control": ctl_rows,
    }
    return out


async def run_profile(client: httpx.AsyncClient, spec: ProfileSpec, mix: list[MixItem], *,
                      direct_client: httpx.AsyncClient | None = None, tag: str = "b") -> dict[str, Any]:
    import time

    async def send(i: int, *, warm: bool = False) -> Record:
        item = mix[i % len(mix)]
        sid = f"bench-{tag}-{spec.name}-{'w' if warm else ''}{i}"
        t0 = time.perf_counter()
        if spec.path == "/v1/guard":
            resp = await client.post("/v1/guard", json=guard_body(item.text, sid, dry_run=spec.dry_run),
                                     headers={**AGENT_HEADERS, "X-Aegis-Session": sid})
            rec = record_from_response(resp, (time.perf_counter() - t0) * 1000, parse_verdict=True)
        elif spec.path == "direct":
            assert direct_client is not None
            resp = await direct_client.post("/v1/chat/completions", json=openai_body(item.text, spec.model))
            rec = record_from_response(resp, (time.perf_counter() - t0) * 1000, parse_verdict=False)
        else:
            resp = await client.post(spec.path, json=openai_body(item.text, spec.model),
                                     headers={**AGENT_HEADERS, "X-Aegis-Session": sid,
                                              "Authorization": "Bearer bench-not-a-key"})
            rec = record_from_response(resp, (time.perf_counter() - t0) * 1000, parse_verdict=False)
            if rec.error and resp.status_code in (402, 403, 429):
                rec.error = None  # a policy block is a valid gateway answer (synthetic 200 per A-07, else counted)
        rec.kind = item.kind
        return rec

    for k in range(spec.warmup):
        try:
            await send(k, warm=True)
        except Exception:
            pass
    recs, elapsed = await run_closed_loop(send, concurrency=spec.concurrency, requests=spec.requests,
                                          duration_s=spec.duration_s)
    return summarize(spec, recs, elapsed, upstream=spec.path not in ("/v1/guard", "direct"))


__all__ = ["ProfileSpec", "run_profile", "summarize"]
