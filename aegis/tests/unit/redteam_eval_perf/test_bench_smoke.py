"""@slow: in-process bench target + echo upstream (no fixed ports; port 0)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.slow


async def test_guard_profile_inproc():
    pytest.importorskip("aegis.app")
    from tests.bench.mix import build_mix
    from tests.bench.profiles import ProfileSpec, run_profile
    from tests.bench.targets import InprocTarget
    from tests.bench.upstream import EchoUpstream

    with EchoUpstream(0) as up:
        async with InprocTarget(upstream_url=up.url) as t, t.client() as cl:
            p = await run_profile(cl, ProfileSpec("guard-det-c1", "smoke", "deterministic", "/v1/guard", 1,
                                                  requests=20, warmup=2), build_mix(20))
    assert p["requests"] == 20 and p["errors"] == 0
    assert p["overhead_ms"]["p50"] is not None
    assert p["by_control"]
