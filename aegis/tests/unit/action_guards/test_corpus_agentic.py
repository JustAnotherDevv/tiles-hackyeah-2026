"""Corpus parity (ACT-V04): the ~30 ``tool_input`` rows of staging/corpora/handwritten/agentic_tools.jsonl
(copied verbatim into data/agentic_tools.jsonl) mapped to contract tool calls.

Map: ``Bash`` -> Bash (claude-code), ``read_file(p)`` -> Read, ``write_file(p, c)`` -> Write,
``http_get(u)`` -> WebFetch (chaos-agent; claude-code's allowlist denies WebFetch), ``sql_query`` ->
``acme-db.query``, free-text spend rows -> structured spend tools. Overrides are listed with reasons.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from .conftest import Harness, make_interaction

DATA = Path(__file__).parent / "data" / "agentic_tools.jsonl"
ROWS = [json.loads(line) for line in DATA.read_text().splitlines() if line.strip()]

SKIP = {
    "AGT-EXF-006": "DNS/subdomain exfil of a secret is DLP-04 (metadata-egress), not an action guard"
}
OVERRIDES = {
    "AGT-SPEND-003": (
        "require_approval",
        "corpus 'allow' = self band; balanced auto_allow_max_usd is 0, so ACT-01 "
        "asks the requester's sponsor ($15 -> rule spend-self)",
    ),
}
SPEND = {
    "AGT-SPEND-001": (
        "marketpulse.purchase_subscription",
        {"vendor": "datafeeds-inc", "plan": "pro-monthly", "amount_usd": 50},
    ),
    "AGT-SPEND-002": ("payments.transfer_funds", {"amount_usd": 5000, "iban": "PL61 **** 2874"}),
    "AGT-SPEND-003": ("payments.create_charge", {"vendor": "opendata-shop", "amount_usd": 15}),
}


def _call(row: dict[str, Any]) -> tuple[str, dict[str, Any], str, str]:
    tool, text = row["tool"], row["text"]
    if row["id"] in SPEND:
        name, args = SPEND[row["id"]]
        return name, args, "mcp.call", "chaos-agent@platform"
    if tool == "Bash":
        return "Bash", {"command": text}, "tool.input", "claude-code@platform"
    if tool == "sql_query":
        return "acme-db.query", {"sql": text}, "mcp.call", "chaos-agent@platform"
    m = re.match(r'^(\w+)\("([^"]*)"(?:,\s*"([^"]*)")?\)', text)
    assert m, row["id"]
    if tool == "read_file":
        return "Read", {"file_path": m.group(2)}, "tool.input", "claude-code@platform"
    if tool == "write_file":
        return (
            "Write",
            {"file_path": m.group(2), "content": m.group(3) or ""},
            "tool.input",
            "claude-code@platform",
        )
    if tool == "http_get":
        return "WebFetch", {"url": m.group(2)}, "tool.input", "chaos-agent@platform"
    raise AssertionError(f"unmapped tool {tool}")


@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
async def test_corpus_row(h: Harness, row: dict[str, Any]) -> None:
    if row["id"] in SKIP:
        pytest.skip(SKIP[row["id"]])
    expect, why = OVERRIDES.get(row["id"], (row["expected_action"], ""))
    name, args, surface, agent = _call(row)
    r = await h.run(
        make_interaction(name, args, surface=surface, dest="local"),
        agent,
        meta={"cwd": "/tmp/aegis-demo/project"},
    )
    got = r.action
    ok = got == expect or (expect == "allow" and got == "log")
    print(
        f"{row['id']:<14} {name:<36} expect={expect:<17} got={got:<17} by={getattr(r.primary, 'control_id', '-')}"
        + (f"  [override: {why}]" if why else "")
    )
    assert ok, (row["id"], got, {k: (d.action, d.reason) for k, d in r.decisions.items()})
