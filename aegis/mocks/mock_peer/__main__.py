"""python -m mocks.mock_peer [--port N|0] [--port-file F] [--host 127.0.0.1]

Default port 8795 (env AEGIS_MOCK_PEER_PORT). Start it from the repo root with the same
AEGIS_DATA_DIR as the gateway so both derive the same demo peer keys (or export
AEGIS_A2A_KEY_RESEARCH_AGENT in both environments).
"""

from __future__ import annotations

import os
import sys

from mocks import run_cli
from mocks.mock_peer.app import create_app

if __name__ == "__main__":
    argv = sys.argv[1:]
    if not any(a == "--port" or a.startswith("--port=") for a in argv):
        argv += ["--port", os.environ.get("AEGIS_MOCK_PEER_PORT", "8795")]
    raise SystemExit(run_cli(create_app, "mock_peer", argv,
                             description="Aegis mock A2A peer agent (simulated)."))
