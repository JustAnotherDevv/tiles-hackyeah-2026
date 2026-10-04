"""One `build() -> MCPServer` per mock MCP server (fresh instances per app: the SDK session
manager can only run once per server object)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mocks.mock_mcp.servers import (
    acme_crm,
    acme_db,
    mailer,
    marketpulse,
    payments,
    poisoned,
    rugpull,
    weather,
    web,
)

BUILDERS: dict[str, Callable[[], Any]] = {
    "acme-db": acme_db.build,
    "acme-crm": acme_crm.build,
    "marketpulse": marketpulse.build,
    "payments": payments.build,
    "mailer": mailer.build,
    "web": web.build,
    "weather": weather.build,
    "poisoned": poisoned.build,
    "rugpull": rugpull.build,
}

__all__ = ["BUILDERS"]
