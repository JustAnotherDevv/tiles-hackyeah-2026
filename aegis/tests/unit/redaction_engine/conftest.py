"""Fixtures for redaction-engine unit tests (no models, no servers, no network)."""

from __future__ import annotations

import pytest

from aegis.controls.dlp import _common
from aegis.core.policy_schema import ControlConfig, PolicySnapshot
from aegis.core.types import RequestContext
from aegis.redaction.engine import RedactionEngineImpl
from tests.unit.redaction_engine.helpers import FakeRT, make_ctx, make_snapshot, snippet_controls


@pytest.fixture
def snap() -> PolicySnapshot:
    return make_snapshot()


@pytest.fixture
def rt(snap: PolicySnapshot) -> FakeRT:
    r = FakeRT(snap)
    _common.set_runtime(r)
    yield r
    _common.set_runtime(None)


@pytest.fixture
def engine(rt: FakeRT) -> RedactionEngineImpl:
    return rt.redactor


@pytest.fixture
def ctx(snap: PolicySnapshot, rt: FakeRT) -> RequestContext:
    return make_ctx(snap)


@pytest.fixture
def cfgs() -> dict[str, ControlConfig]:
    return snippet_controls()
