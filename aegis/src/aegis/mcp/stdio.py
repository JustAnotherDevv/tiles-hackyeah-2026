"""stdio governance wrapper: sits between an MCP client and a local stdio MCP server.

    python -m aegis.mcp.stdio --server poisoned-stdio [--gateway http://127.0.0.1:8787]
        [--agent claude-code@platform] [--key-env AEGIS_AGENT_KEY] [--events-file F]
        -- python -m mocks.mock_mcp --stdio poisoned

1. Launch check BEFORE spawning: `POST /mcp/{server}/_stdio` with an `aegis/launch` message
   (control MCP-01 exact command match, EXE-01, SIG-03). Blocked or gateway unreachable → no
   spawn; the client's `initialize` gets a JSON-RPC error and the wrapper exits 1.
2. Pump: one reader per direction, sequential writes; every message is POSTed to `_stdio` and the
   reply `{action: forward|respond, message}` is acted on. stdout carries JSON-RPC only.
3. Fail closed when the gateway is unreachable: `tools/call` → isError "Aegis gateway unreachable
   (fail-closed)"; a `tools/list` result → `{"tools": []}`; lifecycle + notifications pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx

from aegis.mcp.events import JsonlSink
from aegis.mcp.jsonrpc import LEGACY, blocked_result, is_request, is_response, jsonrpc_error

LINE_LIMIT = 32 * 1024 * 1024
FAIL_CLOSED = "[Aegis] Aegis gateway unreachable (fail-closed)"


def _write(stream: Any, msg: Any) -> None:
    stream.write((json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode())


class StdioBridge:
    def __init__(self, server: str, gateway: str, agent: str | None, key: str | None,
                 sink: JsonlSink, client: httpx.AsyncClient | None = None) -> None:
        self.server = server
        self.url = f"{gateway.rstrip('/')}/mcp/{server}/_stdio"
        self.session = f"stdio-{uuid.uuid4().hex[:12]}"
        headers = {"content-type": "application/json"}
        if agent:
            headers["X-Aegis-Agent"] = agent
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self.http = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0), headers=headers)
        self.sink = sink
        self.pending: dict[Any, dict[str, Any]] = {}

    async def inspect(self, direction: str, message: dict[str, Any]) -> dict[str, Any] | None:
        try:
            resp = await self.http.post(self.url, json={"direction": direction, "message": message,
                                                        "session_id": self.session})
            if resp.status_code != 200:
                self.sink({"event": "gateway_error", "status": resp.status_code})
                return None
            return dict(resp.json())
        except (httpx.HTTPError, ValueError) as e:
            self.sink({"event": "gateway_unreachable", "error": type(e).__name__})
            return None

    async def launch_check(self, command: list[str]) -> tuple[bool, str]:
        reply = await self.inspect("out", {"jsonrpc": "2.0", "id": "aegis-launch",
                                           "method": "aegis/launch", "params": {"command": command}})
        if reply is None:
            return False, FAIL_CLOSED
        if reply.get("action") != "forward":
            err = (reply.get("message") or {}).get("error") or {}
            return False, str(err.get("message") or "[Aegis] launch blocked")
        return True, ""

    def fail_closed_out(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """Reply to send to the client when the gateway is down (None = pass through)."""
        if is_request(msg) and msg.get("method") == "tools/call":
            return blocked_result(msg.get("id"), LEGACY, FAIL_CLOSED, {"action": "block"})
        return None

    def fail_closed_in(self, msg: dict[str, Any]) -> dict[str, Any]:
        req = self.pending.get(msg.get("id")) if is_response(msg) else None
        if req is not None and req.get("method") == "tools/list" and "result" in msg:
            return {**msg, "result": {"tools": []}}
        if req is not None and req.get("method") == "tools/call" and "result" in msg:
            return blocked_result(msg.get("id"), LEGACY, FAIL_CLOSED, {"action": "block"})
        return msg


async def _stdin_reader() -> asyncio.StreamReader:
    reader = asyncio.StreamReader(limit=LINE_LIMIT)
    loop = asyncio.get_running_loop()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    return reader


async def _refuse_initialize(stdin: asyncio.StreamReader, out: Any, reason: str) -> None:
    """Answer the client's first request with the launch refusal, then exit."""
    try:
        line = await asyncio.wait_for(stdin.readline(), 10.0)
        msg = json.loads(line) if line else None
    except (TimeoutError, json.JSONDecodeError):
        msg = None
    if isinstance(msg, dict) and "id" in msg:
        _write(out, jsonrpc_error(msg["id"], -32001, reason))
        out.flush()


def _resolve(command: list[str]) -> list[str]:
    if command and command[0] in ("python", "python3"):
        return [sys.executable, *command[1:]]
    return command


async def run(bridge: StdioBridge, command: list[str]) -> int:
    stdin = await _stdin_reader()
    out = sys.stdout.buffer
    ok, reason = await bridge.launch_check(command)
    if not ok:
        bridge.sink({"event": "launch_blocked", "reason": reason})
        await _refuse_initialize(stdin, out, reason)
        return 1
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", os.pathsep.join(p for p in sys.path if p))
    child = await asyncio.create_subprocess_exec(
        *_resolve(command), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=None, limit=LINE_LIMIT, env=env)
    assert child.stdin and child.stdout

    async def client_to_server() -> None:
        while line := await stdin.readline():
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                child.stdin.write(line)
                await child.stdin.drain()
                continue
            reply = await bridge.inspect("out", msg) if isinstance(msg, dict) else None
            if reply is None:
                refusal = bridge.fail_closed_out(msg) if isinstance(msg, dict) else None
                if refusal is not None:
                    _write(out, refusal)
                    out.flush()
                    continue
                fwd = msg
            elif reply.get("action") == "respond":
                _write(out, reply.get("message"))
                out.flush()
                continue
            else:
                fwd = reply.get("message", msg)
            if is_request(fwd):
                bridge.pending[fwd["id"]] = fwd
            _write(child.stdin, fwd)
            await child.stdin.drain()
        child.stdin.close()

    async def server_to_client() -> None:
        while line := await child.stdout.readline():
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                bridge.sink({"event": "non_json_stdout", "bytes": len(line)})
                continue
            reply = await bridge.inspect("in", msg) if isinstance(msg, dict) else None
            new = bridge.fail_closed_in(msg) if reply is None else reply.get("message", msg)
            if is_response(msg):
                bridge.pending.pop(msg.get("id"), None)
            _write(out, new)
            out.flush()

    try:
        await asyncio.gather(client_to_server(), server_to_client())
    finally:
        if child.returncode is None:
            child.terminate()
    return await child.wait()


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        sys.exit("usage: python -m aegis.mcp.stdio --server NAME [--gateway URL] [--agent ID] "
                 "[--key-env VAR] [--events-file F] -- CMD ...")
    split = argv.index("--")
    ap = argparse.ArgumentParser(prog="python -m aegis.mcp.stdio")
    ap.add_argument("--server", required=True)
    ap.add_argument("--gateway", default=os.environ.get("AEGIS_URL", "http://127.0.0.1:8787"))
    ap.add_argument("--agent", default=os.environ.get("AEGIS_AGENT"))
    ap.add_argument("--key-env", default="AEGIS_AGENT_KEY")
    ap.add_argument("--events-file", type=Path)
    ns = ap.parse_args(argv[:split])
    stream = ns.events_file.open("a", encoding="utf-8") if ns.events_file else sys.stderr
    bridge = StdioBridge(ns.server, ns.gateway, ns.agent, os.environ.get(ns.key_env), JsonlSink(stream))
    sys.exit(asyncio.run(run(bridge, argv[split + 1:])))


if __name__ == "__main__":
    main()
