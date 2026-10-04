"""INJ-V08 - latency budget of the deterministic path (generous CI margins)."""

from __future__ import annotations

import statistics
import time

from aegis.controls.injection import inj01_signatures
from aegis.injection.normalize import _normalize_cached
from aegis.injection.signatures import _scan_text_cached
from tests.lib.perf import bound
from tests.unit.injection_defense._helpers import make_cfg, make_ctx, make_interaction

CTL = inj01_signatures.CONTROLS[0]
CFG = make_cfg("INJ-01", threshold=0.75, params={})
PROMPT = (
    "Please review the attached quarterly report and summarise the revenue drivers by region. "
    "Highlight any risks mentioned by management and compare margins with the previous year. "
) * 12


async def _once(text: str, surface: str = "prompt.user") -> float:
    _scan_text_cached.cache_clear()
    _normalize_cached.cache_clear()
    t = time.perf_counter()
    await CTL.evaluate(make_ctx(), make_interaction(surface, text), CFG)
    return (time.perf_counter() - t) * 1000


async def test_inj01_2kb_prompt_latency(rt) -> None:
    await _once(PROMPT)  # warm the catalog
    runs = sorted([await _once(PROMPT + str(i)) for i in range(60)])
    p50 = statistics.median(runs)
    p95 = runs[int(len(runs) * 0.95) - 1]
    print(f"INJ-01 2KB p50={p50:.2f}ms p95={p95:.2f}ms")
    # target 1 / 3 ms on a quiet box; bound is load-tolerant (shared 8 GB host) x AEGIS_PERF_SLACK
    assert p50 <= bound(25), f"p50={p50:.2f}ms"
    assert p95 <= bound(100), f"p95={p95:.2f}ms"


async def test_inj01_100kb_tool_output(rt) -> None:
    text = ("Line of ordinary tool output with numbers 12345 and words. " * 1700)[:100_000]
    await _once(text, "tool.output")
    ms = await _once(text + "x", "tool.output")
    print(f"INJ-01 100KB tool.output {ms:.1f}ms")
    assert ms <= bound(400), f"{ms:.1f}ms"  # target 40 ms


async def test_cached_repeat(rt) -> None:
    await CTL.evaluate(make_ctx(), make_interaction("prompt.user", PROMPT), CFG)
    t = time.perf_counter()
    await CTL.evaluate(make_ctx(), make_interaction("prompt.user", PROMPT), CFG)
    ms = (time.perf_counter() - t) * 1000
    assert ms <= bound(5), f"{ms:.2f}ms"  # target 0.2 ms
