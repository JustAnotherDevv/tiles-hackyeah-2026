"""B23 demo-agents unit-test fixtures (hermetic: temp data dir, test mode, semantic off)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for p in (str(ROOT), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An in-process gateway (real create_app, real policy, no network) + its sync transport."""
    monkeypatch.setenv("AEGIS_TEST_MODE", "1")
    monkeypatch.setenv("AEGIS_SEMANTIC", "off")
    monkeypatch.setenv("AEGIS_FEED_URL", "disabled")
    monkeypatch.setenv("AEGIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(ROOT)
    from fastapi.testclient import TestClient

    from aegis.app import create_app
    from aegis.core import crypto

    crypto.configure(data_dir=tmp_path / "data")
    app = create_app()
    try:
        with TestClient(app, base_url="http://gw.test") as client:
            yield client
    finally:
        crypto.configure(data_dir=None)
        crypto.reset_key_cache()
