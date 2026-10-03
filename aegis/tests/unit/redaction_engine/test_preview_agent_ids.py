"""INT-A regression: approval titles keep agent ids (`name@team`) but still neutralise e-mails."""

from __future__ import annotations

import pytest

from aegis.redaction.preview import _scrub


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("trading-copilot@trading wants to spend", "trading-copilot@trading wants to spend"),
        ("ask claude-code@platform.", "ask claude-code@platform."),
        ("mail jan@acme-capital.example now", "mail jan(at)acme-capital.example now"),
        ("x @ y", "x (at) y"),
    ],
)
def test_scrub_keeps_agent_ids(text: str, expected: str) -> None:
    assert _scrub(text) == expected
