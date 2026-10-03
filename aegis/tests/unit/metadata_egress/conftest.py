"""Fixtures for metadata-egress unit tests."""

from __future__ import annotations

import pytest

from aegis.core.policy_schema import PolicySnapshot
from aegis.core.types import RequestContext
from tests.unit.metadata_egress.helpers import make_ctx, make_snapshot


@pytest.fixture
def snap() -> PolicySnapshot:
    return make_snapshot()


@pytest.fixture
def ctx(snap: PolicySnapshot) -> RequestContext:
    return make_ctx(snap)
