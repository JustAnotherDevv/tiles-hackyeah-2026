"""`mailer` (third_party): send_email(to, subject, body) - echoes what it RECEIVED, so
placeholders inserted by the gateway are visible."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mocks.mock_mcp.state import STATE


def build() -> MCPServer:
    srv = MCPServer("mailer", instructions="Outbound email gateway (mock; nothing is sent).")

    @srv.tool()
    def send_email(to: str, subject: str, body: str) -> str:
        """Send an email to a recipient. Returns the message id and what the mail server received."""
        STATE.log_call("mailer", "send_email", {"to": to, "subject": subject, "body": body})
        return f"queued msg_{abs(hash((to, subject))) % 10**8:08d} | to={to!r} | subject={subject!r} | body={body!r}"

    return srv
