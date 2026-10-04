"""APR-V02: the 34 ported staging routing tests + all 54 cases of approvals.tests.

Each case asserts required_role, two_person, rule, every approvers_ok (single -> can_approve and
tally approved; pair -> two votes -> approved), every approvers_not_ok (cannot vote, with a reason)
and the gov05 expectation. Adaptations vs staging are documented in docs/plan/09 APR-V02.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SNIPPET = Path(__file__).resolve().parents[3] / "config" / "snippets" / "approvals-engine.yaml"
CASES = yaml.safe_load(SNIPPET.read_text(encoding="utf-8"))["approvals"]["tests"]
STAGING = [c for c in CASES if c.get("staging")]


def test_exactly_34_staging_cases() -> None:
    assert len(STAGING) == 34
    assert len(CASES) >= 54


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
async def test_routing_case(svc, fake_rt, make_doc_fn, make_snapshot_fn, case) -> None:
    from aegis.approvals.selftest import run_case

    snap = fake_rt.policy.snapshot()
    if case.get("profile"):
        snap = make_snapshot_fn(make_doc_fn(profile=case["profile"]), 99)
    result = run_case(svc, case, snap)
    assert result["passed"], f"{case['name']}: {result['errors']} got={result['got']}"


async def test_selftest_runner_all_green(svc) -> None:
    results = await svc.run_routing_selftest()
    failed = [r for r in results if not r["passed"]]
    # profile-specific cases are evaluated against the live (balanced) snapshot by the runner
    # unless the case carries `profile:`, which run_case honours via route_info(profile=...)
    assert not failed, failed
    assert len(results) == len(CASES)
