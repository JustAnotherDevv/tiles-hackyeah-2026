"""Fixtures for injection-defense tests (fakes live in ``_helpers.py``)."""

from __future__ import annotations

import pytest

from tests.unit.injection_defense._helpers import FakeRuntime


@pytest.fixture
def rt(monkeypatch: pytest.MonkeyPatch) -> FakeRuntime:
    from aegis.controls.injection import _common

    fake = FakeRuntime()
    monkeypatch.setattr(_common, "get_rt", lambda: fake)
    return fake
