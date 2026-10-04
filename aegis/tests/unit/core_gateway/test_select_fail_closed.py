"""R2: a control whose `applies_to.matches()` raises is never silently skipped.

The pipeline applies the control's fail_mode (closed -> block + degraded, open -> allow +
degraded) with an explainable reason; out-of-scope controls stay out of the evaluation.
"""

from __future__ import annotations

from typing import Any

from gw_fakes import EnrichingControl, FakeControl, FakeRT, cfg, interaction

from aegis.core.policy_schema import ControlScope
from aegis.core.types import Identity

AGENT = Identity(agent_id="bot@research", team_id="research", member_id="u_owner")


class _Boom:
    def matches(self, i: Any) -> bool:
        raise TypeError("unexpected field type")


def _broken(cid: str, **kw: Any) -> FakeControl:
    c = FakeControl(cid, **kw)
    c.applies_to = _Boom()  # type: ignore[assignment]
    return c


async def _run(rt: FakeRT):
    ctx = rt.pipeline.new_context(source="guard", identity=AGENT)
    v = await rt.pipeline.evaluate(ctx, interaction("hello"))
    return ctx, v


async def test_applies_to_raises_fail_closed_blocks(tmp_path) -> None:
    bad = _broken("EXE-99", action="block")
    ok = FakeControl("A-01", action="log")
    rt = FakeRT(tmp_path, controls=[bad, ok],
                configs=[cfg("EXE-99", action="block", fail_mode="closed"), cfg("A-01")])
    ctx, v = await _run(rt)
    assert v.action == "block"
    assert v.degraded is True
    assert v.primary is not None and v.primary.control_id == "EXE-99"
    assert "fail-closed" in (v.primary.reason or "")
    assert "applies" in (v.primary.reason or "")
    assert v.primary.meta.get("stage") == "select"
    assert "TypeError" in v.primary.meta.get("error", "")
    assert bad.calls == 0  # not evaluated, but not skipped either
    assert ctx.state.get("core.degraded_select") == ["EXE-99"]


async def test_applies_to_raises_default_fail_mode_is_closed(tmp_path) -> None:
    bad = _broken("EXE-98")
    rt = FakeRT(tmp_path, controls=[bad], configs=[cfg("EXE-98")])
    _ctx, v = await _run(rt)
    assert v.action == "block" and v.degraded


async def test_applies_to_raises_fail_open_allows_degraded(tmp_path) -> None:
    bad = _broken("EXE-97", action="block")
    rt = FakeRT(tmp_path, controls=[bad], configs=[cfg("EXE-97", fail_mode="open")])
    _ctx, v = await _run(rt)
    assert v.action == "allow"
    assert v.degraded is True
    d = next(d for d in v.decisions if d.control_id == "EXE-97")
    assert d.degraded and "fail-open" in (d.reason or "") and d.meta.get("stage") == "select"


async def test_applies_to_raises_monitor_mode_does_not_enforce(tmp_path) -> None:
    bad = _broken("EXE-96")
    rt = FakeRT(tmp_path, controls=[bad], configs=[cfg("EXE-96", mode="monitor")])
    _ctx, v = await _run(rt)
    assert v.action == "allow" and v.degraded
    d = next(d for d in v.decisions if d.control_id == "EXE-96")
    assert d.mode == "monitor" and d.action == "block"


async def test_applies_to_raises_out_of_scope_is_still_skipped(tmp_path) -> None:
    bad = _broken("EXE-95")
    rt = FakeRT(tmp_path, controls=[bad],
                configs=[cfg("EXE-95", scope=ControlScope(teams=["trading"]))])
    _ctx, v = await _run(rt)
    assert v.action == "allow" and not v.degraded
    assert all(d.control_id != "EXE-95" for d in v.decisions)


async def test_enrich_failure_marks_decision_degraded(tmp_path) -> None:
    def boom(ctx: Any, i: Any) -> None:
        raise RuntimeError("enrichment backend down")

    c = EnrichingControl("A-02", action="log", enrich_fn=boom)
    rt = FakeRT(tmp_path, controls=[c], configs=[cfg("A-02")])
    _ctx, v = await _run(rt)
    assert c.calls == 1  # still evaluated
    d = next(d for d in v.decisions if d.control_id == "A-02")
    assert d.degraded and "RuntimeError" in d.meta.get("enrich_error", "")
    assert v.action == "log" and v.degraded
