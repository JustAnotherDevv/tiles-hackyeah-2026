"""Mock MCP servers for the Aegis demo and tests (owner: mcp-proxy).

`python -m mocks.mock_mcp` serves acme-db, acme-crm, marketpulse, payments, mailer, web, weather,
poisoned and rugpull on :8792 at `/mcp/<name>`; see `mocks.mock_mcp.app`.
"""
