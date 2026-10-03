"""Hermetic fixtures for threat-feed tests: tmp keys/state/config, in-process ASGI feed app,
a fake runtime (bus/audit/metrics/policy/db) and a FeedManager wired over httpx.ASGITransport.
No fixed ports, no network, no models."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("AEGIS_TEST_MODE", "1")
os.environ.setdefault("AEGIS_SEMANTIC", "off")

from tf_fakes import FEED_BASE, FakeRT

from aegis.feed.manager import FeedManager
from feed_service.build import REPO_ROOT, FeedService


@pytest.fixture
def feed_dirs(tmp_path: Path) -> SimpleNamespace:
    state, cfg = tmp_path / "state", tmp_path / "config"
    svc = FeedService(state, REPO_ROOT, cfg)
    svc.keygen(force=True)
    return SimpleNamespace(tmp=tmp_path, state=state, cfg=cfg, svc=svc)


@pytest.fixture
def feed_app(feed_dirs: SimpleNamespace) -> Any:
    from feed_service.app import create_app

    return create_app(
        state_dir=feed_dirs.state,
        repo_root=REPO_ROOT,
        config_dir=feed_dirs.cfg,
        gateway_url="http://127.0.0.1:9",
    )


@pytest.fixture
async def feed_client(feed_app: Any) -> Any:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=feed_app), base_url=FEED_BASE
    ) as c:
        yield c


@pytest.fixture
def rt(feed_dirs: SimpleNamespace) -> FakeRT:
    return FakeRT(feed_dirs.tmp, feed_dirs.cfg)


@pytest.fixture
async def manager(rt: FakeRT, feed_app: Any) -> Any:
    m = FeedManager(rt, transport=httpx.ASGITransport(app=feed_app))
    rt.feed = m
    await m.start()
    yield m
    await m.stop()


@pytest.fixture
async def seed_manager(feed_dirs: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> Any:
    """FeedManager on the seed bundle only (feed URL disabled) + wired as the SIG runtime."""
    from aegis.controls.signatures import _common

    rt = FakeRT(feed_dirs.tmp, feed_dirs.cfg, feed_url="disabled")
    m = FeedManager(rt)
    rt.feed = m
    await m.start()
    monkeypatch.setattr(_common, "runtime", lambda: rt)
    yield m
    await m.stop()
