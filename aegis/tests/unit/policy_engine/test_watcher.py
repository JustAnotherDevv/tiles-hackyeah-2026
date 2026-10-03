"""POL-V05: hot reload via the file watcher (edit -> applied < 1.5 s; broken -> rejected; own writes ignored)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from aegis.policy.patch import apply_patch_text

pytestmark = pytest.mark.slow


async def _wait(pred, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        await asyncio.sleep(0.05)
    return pred()


async def test_watcher_hot_reload(store, fake_rt, policy_dir: Path) -> None:
    from aegis.policy.watcher import PolicyWatcher

    await store.start()
    w = PolicyWatcher(store)
    w.start()
    try:
        await asyncio.sleep(0.4)  # let awatch arm
        pol = policy_dir / "policy.yaml"
        base = pol.read_text()
        new = apply_patch_text(base, [{"op": "set", "path": "controls[id=INJ-02].threshold", "value": 0.5}])
        t0 = time.monotonic()
        pol.write_text(new, encoding="utf-8")
        assert await _wait(lambda: store.snapshot().version == 2)
        assert time.monotonic() - t0 < 1.5
        assert fake_rt.bus.events("policy.applied")[-1]["latency_ms"] < 1000

        pol.write_text(new + "\nfoo: [\n", encoding="utf-8")
        assert await _wait(lambda: bool(fake_rt.bus.events("policy.rejected")))
        assert fake_rt.bus.events("policy.rejected")[-1]["errors"][0]["line"]
        assert store.snapshot().version == 2

        pol.write_text(new, encoding="utf-8")  # same text as the live version -> no new version
        await asyncio.sleep(0.6)
        assert store.snapshot().version == 2

        res = await store.apply_yaml(base, actor=None, source="api")  # API write -> watcher ignores it
        assert res.version == 3
        await asyncio.sleep(0.6)
        assert store.snapshot().version == 3
    finally:
        await w.stop()
