"""EVAL-V09: a failing control / pipeline is counted as an error, never as a detection; FPR unchanged."""

from __future__ import annotations

from tests.corpora.loader import load_rows
from tests.eval.adapter import to_cases
from tests.eval.metrics import aggregate
from tests.eval.runner import run_inprocess
from tests.unit.redteam_eval_perf.conftest import FakeRuntime, decision, verdict


async def test_exceptions_and_fail_closed_are_errors():
    rows = [r for r in load_rows(subsets=["public"]) if r.file.endswith("deepset_prompt_injections.jsonl")][:40]
    cases = to_cases(rows)

    def decide(i):
        txt = i.segments[0].text
        h = sum(map(ord, txt)) % 4
        if h == 0:
            raise RuntimeError("control exploded")
        if h == 1:
            return verdict("block", [decision("AEGIS-CORE", reason="internal error (fail-closed)", degraded=True)])
        return verdict("allow", [decision("INJ-01", "allow")])

    out = await run_inprocess(FakeRuntime(decide), cases, profile="balanced", mode="deterministic")
    s = aggregate(out)
    assert s["errors"] > 0
    assert s["overall"]["attack"]["detected"] == 0
    assert s["overall"]["benign"]["over_block"] == 0
    assert s["overall"]["attack"]["n"] + s["overall"]["benign"]["n"] + s["errors"] == len(cases)
