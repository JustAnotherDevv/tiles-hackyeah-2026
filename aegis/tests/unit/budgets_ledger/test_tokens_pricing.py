"""BUD-V01 / BUD-V02: token estimate + contract pricing."""

from __future__ import annotations

import pytest

from aegis.budgets.pricing import PricingTable, load_pricing
from aegis.budgets.tokens import estimate_tokens
from aegis.core.types import Usage
from tests.unit.budgets_ledger.conftest import PRICING


@pytest.fixture(scope="module")
def table() -> PricingTable:
    return load_pricing(PRICING)


def test_estimate_tokens() -> None:
    assert estimate_tokens("x" * 400) == 100
    assert estimate_tokens("x" * 350, "claude-sonnet-4-5") == 100
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1


def test_control_ids() -> None:
    from aegis.controls.budget import bud01_budgets, bud02_local, exe04_loops

    assert [c.id for c in exe04_loops.CONTROLS] == ["EXE-04"]
    assert [c.id for c in bud01_budgets.CONTROLS] == ["BUD-01"]
    assert [c.id for c in bud02_local.CONTROLS] == ["BUD-02"]


def test_sonnet_price(table: PricingTable) -> None:
    u = Usage(input_tokens=1000, output_tokens=500)
    assert table.price("claude-sonnet-4-5", u) == pytest.approx(0.0105)


def test_haiku_cache_read(table: PricingTable) -> None:
    u = Usage(input_tokens=10_000, cache_read_tokens=8_000, output_tokens=100)
    assert table.price("claude-haiku-4-5", u) == pytest.approx(0.0033)


def test_local_compute_price(table: PricingTable) -> None:
    assert table.price("aegis-judge", Usage(compute_s=10)) == pytest.approx(0.002)
    assert table.is_local_priced("aegis-judge")
    assert not table.is_local_priced("mock-echo")


def test_prefix_and_fallback(table: PricingTable) -> None:
    assert table.model_price("anthropic/claude-opus-4-1")[0] == "claude-opus-*"
    assert table.model_price("totally-unknown-model")[0] == "*"
    assert table.tool_price("web.fetch_url") == pytest.approx(0.002)
    assert table.tool_price("Bash") == 0.0


def test_version_and_dict(table: PricingTable) -> None:
    d = table.as_dict()
    assert d["version"] == table.version and d["currency"] == "USD"
    assert {"match", "in", "out", "cache_read", "cache_write", "compute_s"} <= set(d["models"][0])
    assert {"match": "web.fetch_url", "usd": 0.002} in d["tools"]


def test_builtin_default_matches_contract() -> None:
    t = PricingTable.default()
    assert t.price(
        "claude-sonnet-4-5", Usage(input_tokens=1000, output_tokens=500)
    ) == pytest.approx(0.0105)
