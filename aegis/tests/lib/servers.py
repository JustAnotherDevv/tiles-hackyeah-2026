"""Ephemeral-port servers for the hermetic suite (never binds 8787 / 879x).

- `ThreadedUvicorn(app)`: serve an ASGI app on 127.0.0.1:0 in a daemon thread.
- `SubprocessServer(cmd, port, env)`: run a process, wait for its TCP port, kill on teardown/atexit.
- `free_port()`, `wait_tcp()`.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import signal
import socket
import subprocess
import threading
import time
from typing import Any

_ALIVE: set[Any] = set()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_tcp(port: int, host: str = "127.0.0.1", timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError), socket.create_connection((host, port), timeout=0.2):
            return True
        time.sleep(0.05)
    return False


class ThreadedUvicorn:
    """uvicorn in a background thread on an ephemeral port (no signal handlers)."""

    def __init__(self, app: Any, *, host: str = "127.0.0.1", port: int = 0, name: str = "srv"):
        import uvicorn

        self.name = name
        self.host = host
        self.config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
            lifespan="on",
            loop="asyncio",
            ws="none",
            timeout_graceful_shutdown=2,
        )
        self.server = uvicorn.Server(self.config)
        self.server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
        self.thread: threading.Thread | None = None
        self.port: int = 0
        self.error: BaseException | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _run(self) -> None:
        try:
            self.server.run()
        except BaseException as exc:
            self.error = exc

    def start(self, timeout: float = 20.0) -> ThreadedUvicorn:
        self.thread = threading.Thread(target=self._run, name=f"uvicorn-{self.name}", daemon=True)
        self.thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.error is not None:
                raise RuntimeError(f"{self.name} failed to start: {self.error!r}")
            if self.server.started and self.server.servers:
                sock = self.server.servers[0].sockets[0]
                self.port = int(sock.getsockname()[1])
                _ALIVE.add(self)
                return self
            if not self.thread.is_alive():
                raise RuntimeError(f"{self.name} exited during startup ({self.error!r})")
            time.sleep(0.02)
        self.stop()
        raise RuntimeError(f"{self.name} did not start within {timeout:.0f}s")

    def stop(self) -> None:
        self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout=8)
            if self.thread.is_alive():
                self.server.force_exit = True
                self.thread.join(timeout=3)
        _ALIVE.discard(self)


class SubprocessServer:
    """A child process listening on `port`; killed on stop() and at interpreter exit."""

    def __init__(
        self,
        cmd: list[str],
        port: int,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        name: str = "proc",
    ):
        self.cmd, self.port, self.name, self.cwd = cmd, port, name, cwd
        self.env = {**os.environ, **(env or {})}
        self.proc: subprocess.Popen[bytes] | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, timeout: float = 30.0) -> SubprocessServer:
        self.proc = subprocess.Popen(
            self.cmd,
            env=self.env,
            cwd=self.cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        _ALIVE.add(self)
        if not wait_tcp(self.port, timeout=timeout):
            err = b""
            if self.proc.poll() is not None and self.proc.stderr is not None:
                err = self.proc.stderr.read()[-800:]
            self.stop()
            raise RuntimeError(
                f"{self.name} did not listen on {self.port}: {err.decode(errors='replace')}"
            )
        return self

    def stop(self) -> None:
        p = self.proc
        if p is not None and p.poll() is None:
            with contextlib.suppress(Exception):
                os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(Exception):
                    os.killpg(p.pid, signal.SIGKILL)
                p.wait(timeout=3)
        _ALIVE.discard(self)


@atexit.register
def _stop_all() -> None:
    for srv in list(_ALIVE):
        with contextlib.suppress(Exception):
            srv.stop()


__all__ = ["SubprocessServer", "ThreadedUvicorn", "free_port", "wait_tcp"]
