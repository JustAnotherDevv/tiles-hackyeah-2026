from __future__ import annotations

import pytest

from tests.eval.overlay import PROFILES, build_policy_doc, build_policy_text


@pytest.mark.parametrize("profile", PROFILES)
def test_overlay_validates_and_relaxes(profile):
    text = build_policy_text(profile=profile)  # validated with the frozen PolicyDoc
    assert f"profile={profile}" in text
    doc = build_policy_doc(profile=profile)
    assert doc["profile"] == profile
    assert doc["budgets"]["rate"]["requests_per_min"] is None
    assert doc["budgets"]["loops"]["repeat"] >= 10**6
    assert doc["budgets"]["kill_switch"]["global"] is False


def test_overlay_rewrites_mock_providers():
    doc = build_policy_doc(upstream_url="http://127.0.0.1:1234", slow_upstream_url="http://127.0.0.1:5678")
    assert doc["providers"]["mock-openai"]["base_url"] == "http://127.0.0.1:1234/v1"
    assert doc["providers"]["bench-slow"]["base_url"] == "http://127.0.0.1:5678/v1"
    assert doc["models"]["routes"][0]["match"] == "mock-slow-*"
