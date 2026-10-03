"""SEM-06: breaker, latency window, TTL cache, single-flight (fake clock)."""

from __future__ import annotations

import asyncio

import pytest

from aegis.semantic.resilience import CircuitBreaker, LatencyWindow, SingleFlight, TTLCache


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_breaker_opens_after_three_failures_and_probes():
    clk = Clock()
    changes = []
    br = CircuitBreaker(
        "g", clock=clk, cooldown_s=30, on_change=lambda b, o, n, w: changes.append((o, n))
    )
    for _ in range(3):
        assert br.allow()
        br.record(False)
    assert br.state == "open" and not br.allow()
    clk.t += 30
    assert br.state == "half_open"
    assert br.allow() and not br.allow()  # exactly one probe
    br.record(True)
    assert br.state == "closed"
    assert changes == [("closed", "open"), ("open", "half_open"), ("half_open", "closed")]


def test_breaker_probe_failure_doubles_cooldown():
    clk = Clock()
    br = CircuitBreaker("g", clock=clk, cooldown_s=30, max_cooldown_s=50)
    for _ in range(3):
        br.record(False)
    clk.t += 30
    assert br.allow()
    br.record(False)
    assert br.state == "open" and br.cooldown_s == 50  # doubled, capped
    clk.t += 49
    assert br.state == "open"
    clk.t += 1
    assert br.state == "half_open"


def test_breaker_error_rate_and_slow_p95():
    br = CircuitBreaker("g", clock=Clock(), min_calls=5, error_rate=0.3)
    for ok in (True, False, True, False, True):
        br.record(ok)
    assert br.state == "open"
    slow = CircuitBreaker("s", clock=Clock(), slow_p95_ms=100)
    for _ in range(5):
        slow.record(True, 500)
    assert slow.state == "open"


def test_latency_window_percentiles():
    w = LatencyWindow(100)
    assert w.p50 is None
    for v in range(1, 101):
        w.add(float(v))
    assert 49 <= w.p50 <= 51
    assert 94 <= w.p95 <= 96
    assert len(w) == 100


def test_ttl_cache_expiry_and_size():
    clk = Clock()
    c = TTLCache(maxsize=2, ttl_s=10, clock=clk)
    c.set("a", 1)
    assert c.get("a") == 1
    clk.t += 11
    assert c.get("a") is None
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    assert len(c) == 2


async def test_single_flight_dedups_and_survives_cancel():
    sf = SingleFlight()
    runs = 0
    gate = asyncio.Event()

    async def work():
        nonlocal runs
        runs += 1
        await gate.wait()
        return 42

    t1 = asyncio.create_task(sf.do("k", work))
    t2 = asyncio.create_task(sf.do("k", work))
    await asyncio.sleep(0)
    t1.cancel()
    gate.set()
    assert await t2 == 42
    with pytest.raises(asyncio.CancelledError):
        await t1
    assert runs == 1 and sf.shared == 1 and len(sf) == 0
