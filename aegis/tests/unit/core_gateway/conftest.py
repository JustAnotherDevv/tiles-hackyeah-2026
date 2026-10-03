"""core-gateway unit-test fixtures (hermetic: temp data dir, test mode, semantic off)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def _gw_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AEGIS_TEST_MODE", "1")
    monkeypatch.setenv("AEGIS_SEMANTIC", "off")
    monkeypatch.setenv("AEGIS_FEED_URL", "disabled")
    monkeypatch.setenv("AEGIS_DATA_DIR", str(tmp_path / "data"))
    from aegis.core import crypto

    crypto.configure(data_dir=tmp_path / "data")
    yield
    crypto.configure(data_dir=None)
    crypto.reset_key_cache()
