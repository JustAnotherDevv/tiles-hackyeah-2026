"""python -m mocks.mock_mcp [--port 8792] [--host 127.0.0.1] [--stdio NAME]"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    from mocks.mock_mcp.servers import BUILDERS

    ap = argparse.ArgumentParser(prog="python -m mocks.mock_mcp",
                                 description="Aegis mock MCP servers (Streamable HTTP, both eras).")
    ap.add_argument("--port", type=int, default=8792)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--stdio", choices=sorted(BUILDERS), help="serve ONE server over stdio instead")
    ap.add_argument("--log-level", default="warning")
    ns = ap.parse_args(argv)
    if ns.stdio:
        BUILDERS[ns.stdio]().run("stdio")
        return 0
    import uvicorn

    from mocks.mock_mcp.app import create_app

    app = create_app()
    print(f"[mock_mcp] http://{ns.host}:{ns.port}/mcp/<{'|'.join(BUILDERS)}>", file=sys.stderr, flush=True)
    uvicorn.run(app, host=ns.host, port=ns.port, log_level=ns.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
