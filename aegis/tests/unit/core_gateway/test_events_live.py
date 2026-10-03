"""GW-V10 (slow): real HTTP SSE — uvicorn on an ephemeral port in a thread, first `decision`."""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
from gw_fakes import FakeControl, FakeRT, cfg, route_app

from aegis.api.routes import events, guard


@pytest.mark.slow
def test_sse_decision_over_real_http(tmp_path) -> None:
    import uvicorn

    rt = FakeRT(tmp_path, controls=[FakeControl("A-01", action="log")], configs=[cfg("A-01")])
    app = route_app(rt, events, guard)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        base = f"http://127.0.0.1:{port}"
        got: list[str] = []
        with httpx.Client(timeout=5) as c, c.stream(
                "GET", f"{base}/api/events?events=decision") as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            assert r.headers["x-accel-buffering"] == "no"
            httpx.post(f"{base}/v1/guard", json={"interaction": {"text": "hi"}}, timeout=5)
            for line in r.iter_lines():
                got.append(line)
                if line.startswith("data:"):
                    break
        assert "event: decision" in got and got[-1].startswith("data: {")
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
