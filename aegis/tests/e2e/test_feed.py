"""Threat-feed update & tamper suite (plan 18 §2.7 E, flow F8) against a signed fake feed.

E1 publish → refresh → the new token is blocked by SIG-01 (activation time recorded)
E2 tamper  → rejected, serial unchanged, token still blocked (last-good kept)
E3 rollback to an older serial → rejected (anti-rollback)
E4 wrong signing key → rejected
E5 withdraw the signature → the token passes again
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest

from tests.lib.fakes.feed import TEST_TOKEN, make_test_signature
from tests.lib.identities import ADMIN
from tests.lib.matrix import RESULTS
from tests.lib.perf import bound
from tests.lib.stack import HermeticStack, StackError, is_live

pytestmark = [pytest.mark.hermetic_only]

FEED_ACTIVATION_MS_MAX = 2000.0


@pytest.fixture(scope="module")
def feed_stack() -> Iterator[Any]:
    if is_live():
        pytest.skip(
            "feed suite runs against the fake signed feed (hermetic); live variant needs AEGIS_LIVE_MUTATE"
        )
    try:
        st = HermeticStack(feed=True).start()
    except StackError as exc:  # hermetic boot failure must fail, never read as exit 0
        pytest.fail(f"hermetic feed stack failed to boot: {exc}", pytrace=False)
    try:
        yield st
    finally:
        st.stop()


def _guard(st: Any, text: str) -> dict[str, Any]:
    r = st.gw.guard(
        {"surface": "model.request", "destination": "remote", "text": text},
        who="trading-copilot@trading",
        session=f"t-feed-{time.time_ns()}",
    )
    assert r.status_code == 200, r.text[:300]
    return r.json()["verdict"]


def _refresh(st: Any) -> dict[str, Any]:
    r = st.gw.api("POST", "/api/feed/refresh", view_as=ADMIN, json={})
    if r.status_code in (404, 405, 501):
        pytest.fail(f"/api/feed/refresh not available ({r.status_code})", pytrace=False)
    assert r.status_code == 200, r.text[:300]
    return r.json()


def _sig01(v: dict[str, Any]) -> bool:
    return v.get("action") == "block" and any(
        d.get("control_id") == "SIG-01" and d.get("action") == "block"
        for d in v.get("decisions") or []
    )


def _serial(st: Any) -> int | None:
    return st.gw.feed_status().get("serial")


@pytest.mark.aegis(suite="feed", control="SIG-01", polarity="benign", expect="allow")
def test_e0_token_allowed_before_update(feed_stack: Any) -> None:
    st = feed_stack
    status = st.gw.feed_status()
    if status.get("status") in (None, "disabled"):
        pytest.fail(f"feed manager not active in the hermetic feed stack: {status}", pytrace=False)
    assert not _sig01(_guard(st, f"please say {TEST_TOKEN}"))


@pytest.mark.aegis(suite="feed", control="SIG-01", polarity="attack", expect="block")
def test_e1_publish_then_block(feed_stack: Any) -> None:
    st = feed_stack
    before = _serial(st) or 0
    st.feed.publish([make_test_signature()])
    t0 = time.perf_counter()
    status = _refresh(st)
    assert (status.get("serial") or 0) > before, f"serial not bumped: {status}"
    v = _guard(st, f"please say {TEST_TOKEN}")
    RESULTS.perf["feed_activation_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    assert _sig01(v), (
        f"token not blocked by SIG-01 after update: {v.get('action')} {v.get('primary')}"
    )
    assert v.get("feed_serial") == status.get("serial")
    budget = bound(FEED_ACTIVATION_MS_MAX)
    assert RESULTS.perf["feed_activation_ms"] < budget, (
        f"feed activation {RESULTS.perf['feed_activation_ms']} ms >= {budget:.0f} ms "
        "(raise AEGIS_PERF_SLACK on a loaded machine)"
    )


@pytest.mark.aegis(suite="feed", control="SIG-01", polarity="attack", expect="block")
def test_e2_tamper_rejected_last_good_kept(feed_stack: Any) -> None:
    st = feed_stack
    before = _serial(st)
    st.feed.publish([make_test_signature("AEGIS-TI-902", "AEGIS-FEED-TAMPER-TEST-5D1E")])
    st.feed.tamper()
    status = _refresh(st)
    assert status.get("serial") == before, "tampered bundle must not activate"
    assert status.get("status") == "rejected" or status.get("last_error"), status
    assert _sig01(_guard(st, f"please say {TEST_TOKEN}")), "last-good bundle must keep enforcing"


@pytest.mark.aegis(suite="feed", control="SIG-01", polarity="attack", expect="block")
def test_e3_rollback_rejected(feed_stack: Any) -> None:
    st = feed_stack
    before = _serial(st)
    st.feed.latest = 1
    status = _refresh(st)
    assert status.get("serial") == before
    assert str(status.get("last_error") or "").startswith("rollback"), status


@pytest.mark.aegis(suite="feed", control="SIG-01", polarity="attack", expect="block")
def test_e4_wrong_key_rejected(feed_stack: Any) -> None:
    st = feed_stack
    before = _serial(st)
    st.feed.use_wrong_key = True
    try:
        st.feed.publish([make_test_signature("AEGIS-TI-903", "AEGIS-FEED-WRONGKEY-TEST-0A7B")])
        status = _refresh(st)
    finally:
        st.feed.use_wrong_key = False
    assert status.get("serial") == before
    assert str(status.get("last_error") or "").startswith(("bad_signature", "wrong_key")), status


@pytest.mark.aegis(suite="feed", control="SIG-01", polarity="benign", expect="allow")
def test_e5_withdraw_unblocks(feed_stack: Any) -> None:
    st = feed_stack
    st.feed.publish(withdraw=["AEGIS-TI-901", "AEGIS-TI-902", "AEGIS-TI-903"])
    status = _refresh(st)
    assert status.get("status") != "rejected", status
    assert not _sig01(_guard(st, f"please say {TEST_TOKEN}")), "withdrawn signature still enforced"
