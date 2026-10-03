"""Standalone Aegis MCP proxy (spike). The gateway only needs the two include_router lines.

    uv run --python 3.13 --with mcp --with fastapi --with uvicorn --with httpx python app.py
    # -> http://127.0.0.1:8796/mcp/{crm,poisoned,rugpull}   admin: /aegis/mcp/{pins,events,reset}

Env: AEGIS_MCP_PORT (8796), AEGIS_MCP_POLICY (catalog.json), AEGIS_MCP_PINS (unset = in-memory).
Decision events are printed to stdout as JSON lines.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from aegis_mcp import Governor, JsonlSink, MemorySink, PinStore, Policy
from aegis_mcp.events import FanoutSink
from aegis_mcp.http_router import build_admin_router, build_mcp_router

HERE = Path(__file__).parent


def create_app() -> FastAPI:
    policy = Policy.load(os.environ.get("AEGIS_MCP_POLICY", HERE / "catalog.json"))
    memory = MemorySink()
    governor = Governor(policy, PinStore(os.environ.get("AEGIS_MCP_PINS") or None), FanoutSink(JsonlSink(), memory))
    app = FastAPI(title="aegis-mcp-proxy (spike)")
    app.include_router(build_mcp_router(governor))
    app.include_router(build_admin_router(governor, memory))
    return app


app = create_app()

if __name__ == "__main__":
    # Loopback only: a local Streamable HTTP endpoint must not be reachable from the network.
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("AEGIS_MCP_PORT", "8796")), log_level="warning")
