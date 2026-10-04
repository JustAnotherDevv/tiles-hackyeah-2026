"""`payments` (third_party): create_charge(vendor, amount_usd, currency) -> ch_… (spend flows)."""

from __future__ import annotations

import secrets

from mcp.server.mcpserver import MCPServer

from mocks.mock_mcp.state import STATE


def build() -> MCPServer:
    srv = MCPServer("payments", instructions="Card-on-file payments (mock; no money moves).")

    @srv.tool()
    def create_charge(vendor: str, amount_usd: float, currency: str = "USD") -> dict[str, object]:
        """Charge the corporate card for a purchase from a vendor."""
        STATE.log_call(
            "payments",
            "create_charge",
            {"vendor": vendor, "amount_usd": amount_usd, "currency": currency},
        )
        return {
            "charge_id": f"ch_{secrets.token_hex(6)}",
            "vendor": vendor,
            "amount_usd": amount_usd,
            "currency": currency,
            "status": "succeeded",
        }

    return srv
