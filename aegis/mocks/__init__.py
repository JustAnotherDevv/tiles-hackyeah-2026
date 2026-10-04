"""Mock upstreams for the Aegis demo and tests (owner: demo-mocks-docs).

Shared helpers for the mocks owned here (`mock_llm` :8791, `exfil_sink` :8793, `mock_saas` :8794)
and for `scripts/run_stack.py` (which also starts mcp-proxy's `mock_mcp` :8792):

- `PORTS` / `PORT_ENV` / `default_port(name)`: default ports and their env overrides (Addendum A-56:
  `--port` flag > `AEGIS_<NAME>_PORT` env > default).
- `mock_data_dir(data_dir)`: `<AEGIS_DATA_DIR or data>/mocks` (created lazily on first write).
- `RequestLog`: newest-first ring buffer (500) + optional JSONL file; never stores auth values.
- `safe_headers(headers)`: header names + values, auth/cookie values replaced by `<redacted>`.
- `masked_preview(text)`: short preview with digits masked (for the exfil sink).
- `run_cli(create_app, name)`: `python -m mocks.<name> [--port N|0] [--port-file F] [--host H]
  [--data-dir D] [--log-level L]`.
- `serve_many(specs)`: several mock apps in ONE process / event loop (run_stack's lean mode).

Every `create_app()` is cheap and side-effect free; nothing here binds a port at import time.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import socket
import sys
import threading
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("mocks")

#: default ports (CONTRACTS section 6.6)
PORTS: dict[str, int] = {"mock_llm": 8791, "mock_mcp": 8792, "exfil_sink": 8793, "mock_saas": 8794}

#: env overrides (Addendum A-56 / A-57)
PORT_ENV: dict[str, str] = {
    "mock_llm": "AEGIS_MOCK_LLM_PORT",
    "mock_mcp": "AEGIS_MOCK_MCP_PORT",
    "exfil_sink": "AEGIS_EXFIL_SINK_PORT",
    "mock_saas": "AEGIS_MOCK_SAAS_PORT",
}

#: logical hosts that metadata-egress maps onto the mocks (CONTRACTS section 5.6)
HOST_MAP_HOSTS: dict[str, str] = {
    "exfil.test": "exfil_sink",
    "paste.test": "mock_saas",
    "pay.saas.test": "mock_saas",
    "crm.saas.test": "mock_saas",
}

#: header names whose VALUES are never recorded (A-56: names are kept, values redacted)
SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "cookie",
        "set-cookie",
        "x-aegis-agent-key",
        "x-aegis-key",
        "anthropic-api-key",
        "openai-api-key",
    }
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def default_port(name: str) -> int:
    """Port for mock `name`: env override (`AEGIS_MOCK_LLM_PORT`, ...) or the default."""
    env = PORT_ENV.get(name)
    raw = os.environ.get(env, "") if env else ""
    if raw.strip().isdigit():
        return int(raw)
    return PORTS[name]


def host_map(ports: Mapping[str, int] | None = None, host: str = "127.0.0.1") -> str:
    """`AEGIS_HOST_MAP` value for the given mock ports (defaults = current env/defaults)."""
    resolved = {name: (ports or {}).get(name) or default_port(name) for name in PORTS}
    return ",".join(f"{h}={host}:{resolved[m]}" for h, m in HOST_MAP_HOSTS.items())


def mock_data_dir(data_dir: str | os.PathLike[str] | None = None) -> Path:
    """`<data_dir>/mocks` (default `$AEGIS_DATA_DIR/mocks`, else `data/mocks` in the repo).

    Not created here; writers call `.mkdir(parents=True, exist_ok=True)` lazily.
    """
    if data_dir is not None:
        base = Path(data_dir)
    else:
        env = os.environ.get("AEGIS_DATA_DIR")
        base = Path(env) if env else REPO_ROOT / "data"
    if not base.is_absolute():
        base = (REPO_ROOT / base).resolve()
    return base / "mocks"


def utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def safe_headers(headers: Mapping[str, str] | Iterable[tuple[str, str]]) -> dict[str, str]:
    """Lower-cased header dict with credential/cookie values replaced by `<redacted>`."""
    items = headers.items() if isinstance(headers, Mapping) else headers
    out: dict[str, str] = {}
    for k, v in items:
        key = str(k).lower()
        out[key] = "<redacted>" if key in SENSITIVE_HEADERS else str(v)
    return out


_DIGIT = re.compile(r"\d")


def masked_preview(text: str | bytes | None, n: int = 120) -> str:
    """First `n` chars with every digit masked (`•`), whitespace collapsed."""
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    flat = " ".join(str(text).split())
    if len(flat) > n:
        flat = flat[: n - 1] + "…"
    return _DIGIT.sub("•", flat)


class RequestLog:
    """Newest-first ring buffer of request records (+ optional JSONL file, created lazily)."""

    def __init__(self, name: str, *, maxlen: int = 500, path: Path | None = None) -> None:
        self.name = name
        self.path = path
        self._items: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._seq = 0
        self.total = 0  # since the last clear (not capped by maxlen)

    def add(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            self.total += 1
            entry = {"seq": self._seq, "ts": utc_iso(), **record}
            self._items.append(entry)
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            except OSError as e:  # never fail a request because the log file is unwritable
                log.warning("mock log write failed name=%s err=%s", self.name, e)
        return entry

    def items(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            out = list(reversed(self._items))
        return out if limit is None or limit <= 0 else out[:limit]

    def clear(self) -> int:
        with self._lock:
            n = self.total
            self._items.clear()
            self.total = 0
        return n

    def __len__(self) -> int:
        return len(self._items)


# ---------------------------------------------------------------------------------------- serving
def bind_socket(host: str, port: int) -> socket.socket:
    """Bind a listening TCP socket (port 0 = ephemeral). Raises OSError when busy."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    sock.listen(128)
    sock.set_inheritable(True)
    return sock


def _uvicorn_server(app: Any, host: str, port: int, log_level: str) -> Any:
    import uvicorn

    class _Server(uvicorn.Server):
        # serve_many installs one signal handler for all servers
        def capture_signals(self):  # type: ignore[override]
            return contextlib.nullcontext()

    config = uvicorn.Config(
        app, host=host, port=port, log_level=log_level, access_log=False, lifespan="auto"
    )
    return _Server(config)


async def serve_many(
    specs: list[tuple[str, Any, socket.socket]],
    *,
    log_level: str = "warning",
    on_started: Callable[[], None] | None = None,
) -> None:
    """Serve several ASGI apps on pre-bound sockets in this event loop until SIGINT/SIGTERM."""
    servers = []
    for _name, app, sock in specs:
        host, port = sock.getsockname()[:2]
        servers.append(_uvicorn_server(app, host, port, log_level))

    def _stop(*_: Any) -> None:
        for s in servers:
            s.should_exit = True

    loop = asyncio.get_running_loop()
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):
                loop.add_signal_handler(sig, _stop)
    tasks = [
        asyncio.create_task(s.serve(sockets=[sock]))
        for s, (_n, _a, sock) in zip(servers, specs, strict=True)
    ]
    if on_started is not None:
        for _ in range(200):
            if all(s.started for s in servers) or any(t.done() for t in tasks):
                break
            await asyncio.sleep(0.02)
        on_started()
    try:
        await asyncio.gather(*tasks)
    finally:
        _stop()


def run_cli(
    create_app: Callable[..., Any],
    name: str,
    argv: list[str] | None = None,
    *,
    description: str | None = None,
) -> int:
    """Entry point shared by `python -m mocks.<name>`. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog=f"python -m mocks.{name}", description=description)
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"port (0 = ephemeral; default ${PORT_ENV.get(name, '')} or {PORTS.get(name)})",
    )
    parser.add_argument("--port-file", default=None, help="write the bound port to this file")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    parser.add_argument("--data-dir", default=None, help="data dir (default $AEGIS_DATA_DIR/data)")
    parser.add_argument("--log-level", default=os.environ.get("AEGIS_MOCK_LOG_LEVEL", "warning"))
    args = parser.parse_args(argv)

    port = default_port(name) if args.port is None else args.port
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    )
    try:
        sock = bind_socket(args.host, port)
    except OSError as e:
        print(
            f"[{name}] cannot bind {args.host}:{port} ({e.strerror or e}). "
            f"Is another process using it? Find it with: lsof -nP -iTCP:{port} -sTCP:LISTEN  "
            f"- or pick another port: --port 0 / {PORT_ENV.get(name, '--port')}=<n>",
            file=sys.stderr,
        )
        return 2
    bound = sock.getsockname()[1]
    if args.port_file:
        Path(args.port_file).write_text(str(bound), encoding="utf-8")
    app = create_app(data_dir=args.data_dir)
    print(f"[{name}] listening on http://{args.host}:{bound}", file=sys.stderr, flush=True)
    try:
        asyncio.run(serve_many([(name, app, sock)], log_level=args.log_level.lower()))
    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(OSError):
            sock.close()
    return 0


__all__ = [
    "HOST_MAP_HOSTS",
    "PORTS",
    "PORT_ENV",
    "SENSITIVE_HEADERS",
    "RequestLog",
    "bind_socket",
    "default_port",
    "host_map",
    "masked_preview",
    "mock_data_dir",
    "run_cli",
    "safe_headers",
    "serve_many",
    "utc_iso",
]
