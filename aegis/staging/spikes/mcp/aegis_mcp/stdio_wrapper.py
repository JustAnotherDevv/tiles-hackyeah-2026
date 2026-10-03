"""stdio governance wrapper: sits between an MCP client and a local stdio MCP server.

    python -m aegis_mcp.stdio_wrapper --server poisoned --policy catalog.json -- python fake_servers.py --stdio poisoned

Claude Code launches the wrapper instead of the real server (.mcp.json "command"), the wrapper
launches the real server and pumps newline-delimited JSON-RPC both ways through the same
Governor the HTTP router uses.

Rules that matter on stdio:
  * stdout carries ONLY JSON-RPC. Decision events go to stderr (or --events-file).
  * Keep per-direction message order: one reader task per direction, writes are sequential.
  * Requests are correlated to responses by id (pending map) so results can be governed.
  * Fail closed: if governance raises on a tools/call, answer with an error instead of forwarding.

In the gateway the spike's in-process Governor would be replaced by a loopback call to the
central gateway (POST /v1/mcp/decide) so pins/events/dashboard stay central; keep a tiny local
allow-cache for hot paths and fail closed for tools/call when the gateway is down.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .events import JsonlSink
from .governor import Ctx, Governor
from .pins import PinStore
from .policy import Policy
from .protocol import LEGACY, detect_era, is_request, is_response, jsonrpc_error

LINE_LIMIT = 32 * 1024 * 1024


async def _stdin_reader() -> asyncio.StreamReader:
    reader = asyncio.StreamReader(limit=LINE_LIMIT)
    loop = asyncio.get_running_loop()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    return reader


def _write(stream: Any, msg: Any) -> None:
    stream.write((json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode())


async def run(server: str, command: list[str], governor: Governor) -> int:
    child = await asyncio.create_subprocess_exec(
        *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=None, limit=LINE_LIMIT)
    assert child.stdin and child.stdout
    stdin = await _stdin_reader()
    out = sys.stdout.buffer
    ctx = Ctx(server, transport="stdio", era=LEGACY)
    pending: dict[Any, dict[str, Any]] = {}

    async def client_to_server() -> None:
        while line := await stdin.readline():
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                child.stdin.write(line)  # not ours to judge; the server will answer with a parse error
                continue
            if is_request(msg):
                ctx.era = detect_era({}, msg) if msg.get("method") != "initialize" else LEGACY
            try:
                verdict = governor.on_client_message(ctx, msg)
            except Exception as e:  # fail closed for requests, pass lifecycle through
                if is_request(msg):
                    _write(out, jsonrpc_error(msg["id"], -32603, f"aegis: governance error ({type(e).__name__})"))
                    out.flush()
                    continue
                verdict = None
            if verdict is not None and verdict.action == "respond":
                _write(out, verdict.message)
                out.flush()
                continue
            fwd = msg if verdict is None else verdict.message
            if is_request(fwd):
                pending[fwd["id"]] = fwd
            _write(child.stdin, fwd)
            await child.stdin.drain()
        child.stdin.close()

    async def server_to_client() -> None:
        while line := await child.stdout.readline():
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                print(f"[aegis-stdio] dropped non-JSON line from server stdout ({len(line)} bytes)", file=sys.stderr)
                continue
            request = pending.pop(msg.get("id"), None) if is_response(msg) else None
            _write(out, governor.on_server_message(ctx, msg, request))
            out.flush()

    await asyncio.gather(client_to_server(), server_to_client())
    return await child.wait()


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        sys.exit("usage: python -m aegis_mcp.stdio_wrapper --server NAME [--policy FILE] [--pins FILE] -- CMD ...")
    split = argv.index("--")
    ap = argparse.ArgumentParser(prog="aegis-mcp-stdio")
    ap.add_argument("--server", required=True)
    ap.add_argument("--policy", type=Path)
    ap.add_argument("--pins", type=Path, help="persistent pin store (JSON); default in-memory")
    ap.add_argument("--events-file", type=Path, help="append decision events here instead of stderr")
    ns = ap.parse_args(argv[:split])
    policy = Policy.load(ns.policy) if ns.policy else Policy()
    events_stream = ns.events_file.open("a", encoding="utf-8") if ns.events_file else sys.stderr
    governor = Governor(policy, PinStore(ns.pins), JsonlSink(events_stream))
    sys.exit(asyncio.run(run(ns.server, argv[split + 1:], governor)))


if __name__ == "__main__":
    main()
