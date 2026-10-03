"""`acme-db` (local): mock Postgres (`acme-prod-pg`, `acme-staging-pg`) over SQLite.

`query(sql, database)` runs ONE statement against `data/mocks/acme_db.sqlite` (seeded with
fictional PII: PESEL, IBAN, emails, test PANs). Rows come back as `structuredContent` plus a text
table, so the gateway must redact both (DLP-05). Writes commit; `POST /_mock/reset` reseeds.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from mocks.mock_mcp import seed_db
from mocks.mock_mcp.state import STATE

DATABASES = {
    "acme-prod-pg": ["customers", "payment_cards", "trades", "positions", "research_notes",
                     "market_prices"],
    "acme-staging-pg": ["customers_synthetic", "trades_synthetic", "market_prices"],
}
MAX_ROWS = 200


def _table(columns: list[str], rows: list[list[Any]]) -> str:
    if not columns:
        return "(no result set)"
    widths = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(str(c))
              for i, c in enumerate(columns)]
    line = " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(columns))
    sep = "-+-".join("-" * w for w in widths)
    body = [" | ".join(str(v).ljust(widths[i]) for i, v in enumerate(r)) for r in rows]
    return "\n".join([line, sep, *body])


def build() -> MCPServer:
    srv = MCPServer("acme-db", instructions="Acme Capital databases (mock). Use list_tables first.")

    @srv.tool()
    def list_tables() -> dict[str, Any]:
        """List databases and their tables."""
        STATE.log_call("acme-db", "list_tables", {})
        return {"databases": [{"id": db, "tables": tables} for db, tables in DATABASES.items()]}

    @srv.tool()
    def query(
        sql: Annotated[str, Field(description="A single SQL statement")],
        database: Annotated[str, Field(description="acme-prod-pg or acme-staging-pg")] = "acme-prod-pg",
    ) -> CallToolResult:
        """Run a single SQL statement against an Acme database and return the rows."""
        STATE.log_call("acme-db", "query", {"sql": sql, "database": database})
        if database not in DATABASES:
            return CallToolResult(content=[TextContent(type="text", text=f"unknown database {database}")],
                                  is_error=True)
        path = seed_db.ensure(STATE.db_path)
        con = sqlite3.connect(path)
        try:
            cur = con.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = [list(r) for r in cur.fetchmany(MAX_ROWS)] if columns else []
            con.commit()
            affected = cur.rowcount if not columns else len(rows)
        except sqlite3.Error as e:
            return CallToolResult(content=[TextContent(type="text", text=f"SQL error: {e}")],
                                  is_error=True)
        finally:
            con.close()
        structured = {"database": database, "columns": columns,
                      "rows": [dict(zip(columns, r, strict=True)) for r in rows],
                      "row_count": affected}
        text = _table(columns, rows) if columns else f"OK ({affected} rows affected)"
        return CallToolResult(content=[TextContent(type="text", text=text)],
                              structured_content=structured)

    return srv
