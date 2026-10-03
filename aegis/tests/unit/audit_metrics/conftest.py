"""audit-metrics fixtures: FakeRT (tmp data dir, real AuditService + MetricsService) + ASGI client."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from am_fakes import make_app, make_rt


@pytest.fixture(autouse=True)
def _am_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AEGIS_TEST_MODE", "1")
    monkeypatch.setenv("AEGIS_SEMANTIC", "off")
    from aegis.metrics import stats

    stats._CACHE.clear()


@pytest.fixture
async def am_rt(tmp_path: Path):
    rt = make_rt(tmp_path)
    await rt.audit.start()
    yield rt
    await rt.audit.stop()


@pytest.fixture
async def am_client(am_rt):
    transport = httpx.ASGITransport(app=make_app(am_rt))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
