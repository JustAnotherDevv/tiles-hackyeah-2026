"""GW-V12: gateway overhead benchmark (+ GW-17 1 MB body measurement).

300 `/v1/messages` calls through the in-process ASGI app with the REAL core pipeline
(`aegis.core.pipeline.Pipeline`, Null services from B01's hermetic fakes) + 3 cheap fake controls
+ a MockTransport upstream. Reads `Server-Timing: aegis;dur=` (= wall time minus upstream) and
asserts p50 < 5 ms, p95 < 15 ms. Prints the numbers for the deck:

    AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off uv run --frozen pytest -q -s -m bench \
        tests/unit/core_gateway_proxy/test_overhead.py
"""

from __future__ import annotations

import json
import os
import re
import statistics
from typing import Any

import httpx
import pytest

from aegis.core.policy_schema import ControlConfig
from aegis.proxy import upstream
from tests.unit.core_gateway.gw_fakes import FakeControl, FakeRT
from tests.unit.core_gateway_proxy.fakes import echo_anthropic, make_app

pytestmark = pytest.mark.bench

N = int(os.environ.get("AEGIS_BENCH_N", "300"))
P50_MS = float(os.environ.get("AEGIS_BENCH_P50_MS", "5"))
P95_MS = float(os.environ.get("AEGIS_BENCH_P95_MS", "15"))
_AEGIS = re.compile(r"(?:^|,\s*)aegis;dur=([0-9.]+)")


def _rt(tmp_path: Any) -> FakeRT:
    surfaces = {"model.request", "model.response"}
    controls = [FakeControl(cid, surfaces=surfaces) for cid in ("DLP-01", "INJ-01", "BUD-01")]
    return FakeRT(tmp_path, controls=controls,
                  configs=[ControlConfig(id=c.id) for c in controls])


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(p / 100.0 * (len(xs) - 1)))]


async def _run(tmp_path: Any, body: dict[str, Any], n: int) -> list[float]:
    rt = _rt(tmp_path)
    upstream.set_transport(httpx.MockTransport(echo_anthropic))
    try:
        app = make_app(rt)  # type: ignore[arg-type]
        raw = json.dumps(body).encode()
        out: list[float] = []
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://aegis.test") as c:
            for k in range(n + 10):
                r = await c.post("/v1/messages", content=raw,
                                 headers={"content-type": "application/json",
                                          "x-aegis-agent": "bench@platform"})
                assert r.status_code == 200, r.text
                m = _AEGIS.search(r.headers["server-timing"])
                assert m, r.headers["server-timing"]
                if k >= 10:  # warm-up
                    out.append(float(m.group(1)))
        # the real pipeline ran every control on both hops
        assert all(ctl.calls >= 2 * n for ctl in rt.controls.all())
        return out
    finally:
        upstream.set_transport(None)


async def test_overhead_p50_p95(tmp_path) -> None:
    body = {"model": "mock-echo", "max_tokens": 64,
            "messages": [{"role": "user", "content": "hello, summarize Q3 for me"}]}
    xs = await _run(tmp_path, body, N)
    p50, p95 = statistics.median(xs), _pct(xs, 95)
    print(f"\n[GW-V12] /v1/messages overhead n={len(xs)} p50={p50:.2f} ms p95={p95:.2f} ms "
          f"max={max(xs):.2f} ms (real pipeline, 3 controls x 2 hops, MockTransport upstream)")
    assert p50 < P50_MS, f"p50 {p50:.2f} ms >= {P50_MS} ms"
    assert p95 < P95_MS, f"p95 {p95:.2f} ms >= {P95_MS} ms"


async def test_overhead_1mb_claude_code_body(tmp_path) -> None:
    """GW-17: Claude Code-sized transcript (~1 MB, 200 turns) — report only (no hard bound)."""
    turn = "x" * 5000
    msgs = []
    for k in range(200):
        msgs.append({"role": "user", "content": [{"type": "text", "text": f"{k} {turn}"}]})
        msgs.append({"role": "assistant", "content": [{"type": "text", "text": f"ok {k}"}]})
    msgs.append({"role": "user", "content": "final question"})
    body = {"model": "mock-echo", "max_tokens": 64, "messages": msgs,
            "system": [{"type": "text", "text": "You are Claude Code."}]}
    size = len(json.dumps(body))
    xs = await _run(tmp_path, body, 20)
    print(f"\n[GW-17] {size / 1e6:.2f} MB body overhead p50={statistics.median(xs):.2f} ms "
          f"max={max(xs):.2f} ms")
    assert statistics.median(xs) < 250
