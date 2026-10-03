"""Closed-loop asyncio load generator (concurrency N, request count or duration)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from tests.bench.servertiming import controls, parse


@dataclass
class Record:
    status: int
    client_ms: float
    timing: dict[str, float] = field(default_factory=dict)
    action: str | None = None
    verdict_ms: float | None = None
    decisions: list[tuple[str, float, str]] = field(default_factory=list)  # (control_id, latency_ms, mode)
    error: str | None = None
    kind: str | None = None

    @property
    def overhead_ms(self) -> float:
        if "aegis" in self.timing:
            return self.timing["aegis"]
        if self.verdict_ms is not None:
            return self.verdict_ms
        return self.client_ms

    @property
    def overhead_source(self) -> str:
        return "server_timing" if "aegis" in self.timing else ("verdict" if self.verdict_ms is not None else "client")


RequestFn = Callable[[int], Awaitable[Any]]  # i -> httpx.Response


def record_from_response(resp: Any, client_ms: float, *, parse_verdict: bool) -> Record:
    rec = Record(status=resp.status_code, client_ms=client_ms, timing=parse(resp.headers.get("server-timing")))
    if parse_verdict and resp.status_code == 200:
        try:
            v = resp.json().get("verdict") or {}
            rec.action = v.get("action")
            rec.verdict_ms = v.get("latency_ms")
            rec.decisions = [(d.get("control_id"), float(d.get("latency_ms") or 0.0), d.get("mode", "enforce"))
                             for d in v.get("decisions") or [] if d.get("control_id")]
        except Exception as e:
            rec.error = f"bad json: {e!r}"
    elif resp.status_code >= 400:
        rec.error = f"http {resp.status_code}"
    return rec


async def run_closed_loop(send: Callable[[int], Awaitable[Record]], *, concurrency: int, requests: int | None = None,
                          duration_s: float | None = None) -> tuple[list[Record], float]:
    """N workers, each sends back-to-back. Stops after `requests` total or `duration_s`."""
    recs: list[Record] = []
    counter = 0
    stop_at = time.perf_counter() + duration_s if duration_s else None
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal counter
        while True:
            async with lock:
                if requests is not None and counter >= requests:
                    return
                if stop_at is not None and time.perf_counter() >= stop_at:
                    return
                i = counter
                counter += 1
            try:
                recs.append(await send(i))
            except Exception as e:
                recs.append(Record(status=0, client_ms=0.0, error=f"{type(e).__name__}: {e}"[:200]))

    t0 = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))
    return recs, time.perf_counter() - t0


def ctl_timings(rec: Record) -> dict[str, float]:
    return controls(rec.timing)


__all__ = ["Record", "ctl_timings", "record_from_response", "run_closed_loop"]
