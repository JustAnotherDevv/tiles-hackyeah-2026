"""ACT-16 / ACT-V06: F3/F4 through the REAL in-process pipeline via ``POST /v1/guard``.

Uses the root contract fixtures (``client`` = in-process ASGI app on a temp data dir, test mode).
Integration is complete: a gateway that cannot boot fails here (no skip).
"""

from __future__ import annotations

from typing import Any

import pytest

from aegis.sdk.cast import agent_headers  # ASI03: X-Aegis-Agent + its key


@pytest.fixture
def gw(client: Any) -> Any:
    return client


async def _guard(
    gw: Any, interaction: dict[str, Any], agent: str, dry_run: bool = True
) -> dict[str, Any]:
    r = await gw.post(
        "/v1/guard",
        json={"interaction": interaction, "identity": {"agent_id": agent}, "dry_run": dry_run},
        headers=agent_headers(agent),
    )
    assert r.status_code == 200, r.text[:500]
    return r.json()


def _mcp(tool: str, args: dict[str, Any], dest: str = "third_party") -> dict[str, Any]:
    return {
        "kind": "mcp",
        "surface": "mcp.call",
        "destination": dest,
        "tool_name": tool,
        "tool_args": args,
        "mcp_server": tool.split(".", 1)[0],
    }


def _hook(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "tool_call",
        "surface": "tool.input",
        "destination": "local",
        "tool_name": tool,
        "tool_args": args,
    }


async def test_spend_50_admin(gw: Any) -> None:
    body = await _guard(
        gw,
        _mcp(
            "marketpulse.purchase_subscription",
            {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50},
        ),
        "trading-copilot@trading",
        dry_run=False,
    )
    v = body["verdict"]
    assert v["action"] == "require_approval", v
    assert v["primary"]["control_id"] == "ACT-01"
    appr = body.get("approval") or v.get("approval")
    assert appr and appr["required_role"] == "admin" and appr["rule_id"] == "spend-admin"


async def test_spend_over_cap_blocked(gw: Any) -> None:
    body = await _guard(
        gw,
        _mcp("payments.create_charge", {"vendor": "gpucloud", "amount_usd": 5000.01}),
        "chaos-agent@platform",
    )
    assert body["verdict"]["action"] == "block"


async def test_customers_and_cards(gw: Any) -> None:
    body = await _guard(
        gw,
        _mcp("acme-db.query", {"sql": "SELECT * FROM customers"}, "local"),
        "trading-copilot@trading",
    )
    assert body["verdict"]["action"] == "require_approval"
    body = await _guard(
        gw,
        _mcp("acme-db.query", {"sql": "SELECT pan FROM payment_cards"}, "local"),
        "trading-copilot@trading",
    )
    assert body["verdict"]["action"] == "block"


async def test_f3_commands_and_files(gw: Any) -> None:
    body = await _guard(
        gw, _hook("Bash", {"command": "echo cm0gLXJmIH4= | base64 -d | sh"}), "claude-code@platform"
    )
    v = body["verdict"]
    assert v["action"] == "block" and "rm -rf ~" in v["primary"]["reason"]
    body = await _guard(
        gw, _hook("Read", {"file_path": "/tmp/aegis-demo/project/.env"}), "claude-code@platform"
    )
    assert body["verdict"]["action"] == "block"
