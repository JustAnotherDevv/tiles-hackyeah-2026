"""ORG-V11: resolve_identity hot path (10,000 keyed calls < 1 s)."""

from __future__ import annotations

import time

from tests.lib.perf import bound


async def test_resolve_identity_perf(rt, helpers):
    headers = {
        "authorization": f"Bearer {helpers.KEYS['copilot']}",
        "content-type": "application/json",
        "x-aegis-session": "ses_1",
    }
    resolve = rt.org.resolve_identity
    await resolve(headers)
    t0 = time.perf_counter()
    for _ in range(10_000):
        ident = await resolve(headers)
    elapsed = time.perf_counter() - t0
    assert ident.authenticated and ident.agent_id == "trading-copilot@trading"
    assert elapsed < bound(1.0), f"10k resolutions took {elapsed:.3f}s"
