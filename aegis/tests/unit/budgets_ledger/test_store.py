"""BUD-V06: SQLite write-behind, restart, demo seed, history + samples."""

from __future__ import annotations

import sqlite3

import pytest

from aegis.budgets.ledger import Ledger
from aegis.core.types import Usage
from tests.unit.budgets_ledger.conftest import agent, ctx

CC = agent("claude-code@platform", "platform")


async def _ledger(rt) -> Ledger:
    led = Ledger(rt, persist=True)
    await led.start()
    return led


async def test_restart_restores_used(rt, clock) -> None:
    led = await _ledger(rt)
    await led.commit(ctx(CC), Usage(cost_usd=1.25, input_tokens=100, output_tokens=50))
    await led.stop()
    led2 = await _ledger(rt)
    try:
        assert led2.used("agent:claude-code@platform", "day", "usd") == pytest.approx(1.25)
        assert led2.used("org:acme-capital", "month", "tokens") == pytest.approx(150)
        assert led2.session_usage("s1")["usd"] == pytest.approx(1.25)
    finally:
        await led2.stop()


async def test_demo_seed_values(rt, clock) -> None:
    led = Ledger(rt, persist=True)
    led.demo_mode = True
    await led.start()  # empty table + demo mode -> seed
    try:
        assert led.used("team:trading", "day", "usd") == pytest.approx(38.40)
        assert led.used("org:acme-capital", "month", "usd") == pytest.approx(1088.40)
        hist = await led.history("team:trading", "usd", "24h")
        assert len(hist["points"]) >= 2
        assert hist["points"][-1]["used"] == pytest.approx(38.40)
        assert hist["points"][-1]["limit"] == 60
        fc = await led.history("team:trading", "usd", "30d")
        assert fc["forecast"] is not None and fc["forecast"]["limit"] == 1200
        assert fc["forecast"]["used"] > 310.20  # linear projection to month end
    finally:
        await led.stop()


async def test_reset_reseeds(rt, clock) -> None:
    led = Ledger(rt, persist=True)
    led.demo_mode = True
    await led.start()
    try:
        await led.import_usage("team:trading", "usd", 5, "day")
        assert led.used("team:trading", "day", "usd") == pytest.approx(43.40)
        await led.reset(None)
        assert led.used("team:trading", "day", "usd") == pytest.approx(38.40)
    finally:
        await led.stop()


async def test_samples_at_most_one_per_5s(rt, settings, clock) -> None:
    led = await _ledger(rt)
    try:
        for _ in range(5):
            await led.commit(ctx(CC), Usage(cost_usd=0.01))
            clock.advance(1)
        clock.advance(5)
        await led.commit(ctx(CC), Usage(cost_usd=0.01))
    finally:
        await led.stop()
    conn = sqlite3.connect(settings.data_dir / "aegis.db")
    n = conn.execute(
        "SELECT COUNT(*) FROM budget_samples WHERE scope=? AND dimension='usd' AND window='day'",
        ("agent:claude-code@platform",),
    ).fetchone()[0]
    conn.close()
    assert n == 2
