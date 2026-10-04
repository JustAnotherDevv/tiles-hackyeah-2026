"""@slow: real in-process eval on a small subset (skips if aegis.app cannot boot)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.slow


async def test_quick_eval_inprocess_small():
    pytest.importorskip("aegis.app")
    from tests.corpora.loader import load_rows
    from tests.eval.adapter import to_cases
    from tests.eval.harness import active_profile, hermetic_runtime
    from tests.eval.metrics import aggregate
    from tests.eval.runner import run_inprocess

    rows = load_rows(subsets=["generated"])[:40] + load_rows(subsets=["handwritten"])[:40]
    async with hermetic_runtime("balanced", "off") as h:
        assert active_profile(h.rt) == "balanced"
        out = await run_inprocess(h.rt, to_cases(rows, doc=h.rt.policy.snapshot().doc), profile="balanced",
                                  mode="deterministic")
    s = aggregate(out)
    assert s["n"] == 80 and s["errors"] <= 1
    assert s["overall"]["attack"]["n"] > 0
