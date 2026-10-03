"""BUD-V03: calendar windows (Europe/Warsaw) + limit index / scope chain."""

from __future__ import annotations

from datetime import UTC, datetime

from aegis.budgets import windows
from aegis.budgets.ledger import Ledger
from aegis.budgets.limits import LimitIndex, counter_scope
from tests.unit.budgets_ledger.conftest import agent, human, make_snapshot, snippet_doc

WAW = windows._zone("Europe/Warsaw")


def test_warsaw_day_start_cest() -> None:
    at = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
    assert windows.window_start("day", at, WAW) == "2026-10-02T22:00:00Z"
    assert windows.resets_at("day", at, WAW) == datetime(2026, 10, 3, 22, 0, tzinfo=UTC)
    # 23:30Z on Oct 3 is already Oct 4 in Warsaw
    late = datetime(2026, 10, 3, 23, 30, tzinfo=UTC)
    assert windows.window_start("day", late, WAW) == "2026-10-03T22:00:00Z"


def test_month_and_week_start() -> None:
    at = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
    assert windows.window_start("month", at, WAW) == "2026-09-30T22:00:00Z"
    assert windows.window_start("week", at, WAW) == "2026-09-27T22:00:00Z"  # Monday 28 Sep
    assert windows.resets_at("month", at, WAW) == datetime(2026, 10, 31, 23, 0, tzinfo=UTC)
    assert windows.window_start("session", at, WAW) == "session"
    assert windows.resets_at("total", at, WAW) is None


def test_dst_day_no_crash() -> None:
    at = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)  # CEST -> CET switch day
    assert windows.window_start("day", at, WAW) == "2026-10-24T22:00:00Z"
    assert windows.resets_at("day", at, WAW) == datetime(2026, 10, 25, 23, 0, tzinfo=UTC)
    for w in ("hour", "day", "week", "month"):
        assert windows.window_start(w, at, WAW)


def test_zone_from_snapshot_and_fallback() -> None:
    snap = make_snapshot()
    assert str(windows.zone(snap)) == "Europe/Warsaw"
    assert windows._zone("Not/AZone") is UTC


def test_member_override_beats_glob() -> None:
    def add(d: dict) -> None:
        d["budgets"]["limits"].append({"scope": "member:u_piotr", "window": "day", "usd": 9})

    idx = LimitIndex.compile_doc(snippet_doc(add))
    piotr = idx.resolve("member:u_piotr", human("u_piotr"))[("day", "usd")]
    other = idx.resolve("member:u_anna", human("u_anna"))[("day", "usd")]
    assert piotr.dims["usd"] == 9 and piotr.exact
    assert other.dims["usd"] == 5 and other.scope == "member:*"


def test_match_agents_beats_generic_session() -> None:
    idx = LimitIndex.compile_doc(snippet_doc())
    tc = idx.resolve("session:abc", agent("trading-copilot@trading", "trading"))
    gen = idx.resolve("session:abc", agent("claude-code@platform"))
    assert tc[("session", "usd")].dims["usd"] == 1.0
    assert tc[("session", "usd")].match_agents == ("trading-copilot@trading",)
    assert gen[("session", "usd")].dims["usd"] == 5.0
    # per-instance counters for identity globs, aggregated for model globs
    assert counter_scope(gen[("session", "usd")], "session:abc") == "session:abc"
    opus = idx.resolve("model:claude-opus-4-1", None)[("day", "usd")]
    assert opus.aggregated and counter_scope(opus, "model:claude-opus-4-1") == "model:claude-opus-*"


def test_scope_chain_human_vs_agent() -> None:
    led = Ledger(None, persist=False)
    h = led.scopes_for(human("u_piotr"), "s1")
    a = led.scopes_for(agent("chaos-agent@platform"), "s2")
    assert h == ["org:acme-capital", "team:trading", "member:u_piotr", "session:s1"]
    assert a == ["org:acme-capital", "team:platform", "agent:chaos-agent@platform", "session:s2"]
    assert not any(s.startswith("member:") for s in a)


def test_compile_is_memoised() -> None:
    snap = make_snapshot()
    assert LimitIndex.compile(snap) is LimitIndex.compile(snap)
