"""R1 / R12 / R4: ingress robustness of the real app (`create_app`, in-process ASGI).

- the body-size limit holds for chunked / streamed bodies (no Content-Length): 413 in the wire
  format of the path, and the route never evaluates the body;
- unhandled exceptions become the standard 500 envelope without leaking internals and without the
  exception escaping the ASGI app (which is what makes the server drop the keep-alive connection);
- malformed Claude Code hook bodies stay fail-closed and are logged as WARNING, not ERROR.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager

LIMIT = 262_144
#: deep enough for RecursionError in json.loads, small enough to stay under LIMIT (the hook
#: cases must reach the handler, not the size guard)
DEPTH = 20_000


@pytest.fixture
async def gw(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    from aegis import app as app_mod
    from aegis.settings import Settings

    monkeypatch.setattr(app_mod, "_max_body", lambda _app: LIMIT)
    app = app_mod.create_app(Settings())

    async def boom() -> None:
        raise RuntimeError("secret-internal-detail /etc/aegis/key")

    app.add_api_route("/api/_test_boom", boom, methods=["GET"])
    app.add_api_route("/v1/messages/_test_boom", boom, methods=["GET"])
    async with LifespanManager(app, startup_timeout=60) as manager:
        client = httpx.AsyncClient(transport=httpx.ASGITransport(manager.app),
                                   base_url="http://127.0.0.1:8787", timeout=30)
        async with client:
            yield client, app


def _chunks(total: int, size: int = 16_384) -> AsyncIterator[bytes]:
    async def gen() -> AsyncIterator[bytes]:
        body = json.dumps({"pad": "x" * total}).encode()
        for i in range(0, len(body), size):
            yield body[i:i + size]
    return gen()


@pytest.mark.parametrize(
    ("path", "check"),
    [
        ("/v1/messages", lambda b: b["type"] == "error"
         and b["error"]["type"] == "request_too_large"),
        ("/v1/chat/completions", lambda b: b["error"]["type"] == "payload_too_large"),
        ("/egress", lambda b: b["error"]["type"] == "payload_too_large"),
        ("/v1/guard", lambda b: b["error"]["type"] == "payload_too_large"),
        ("/api/policy/validate", lambda b: b["error"]["type"] == "payload_too_large"),
        ("/mcp/acme-db", lambda b: b["jsonrpc"] == "2.0" and b["error"]["code"] == -32600),
    ],
)
async def test_chunked_body_over_limit_is_413(gw, monkeypatch, path, check) -> None:
    client, app = gw
    calls: list[Any] = []
    pipeline = app.state.rt.pipeline
    orig = pipeline.evaluate

    async def spy(*a: Any, **k: Any) -> Any:
        calls.append(a)
        return await orig(*a, **k)

    monkeypatch.setattr(pipeline, "evaluate", spy)
    r = await client.post(path, content=_chunks(LIMIT * 3),
                          headers={"content-type": "application/json"})
    assert "content-length" not in r.request.headers
    assert r.status_code == 413, (r.status_code, r.text[:200])
    assert check(r.json()), r.text[:300]
    assert "too large" in r.text
    assert calls == []


async def test_content_length_fast_path_and_small_chunked_ok(gw) -> None:
    client, _ = gw
    r = await client.post("/v1/messages", content=b"x" * (LIMIT + 1),
                          headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["type"] == "request_too_large"
    # under the limit, chunked bodies pass the guard (the route then answers normally)
    r = await client.post("/api/policy/validate", content=_chunks(100),
                          headers={"content-type": "application/json"})
    assert r.status_code != 413, r.text[:200]


@pytest.mark.parametrize(
    ("path", "check"),
    [
        ("/api/_test_boom", lambda b: b["error"]["type"] == "internal_error"),
        ("/v1/messages/_test_boom", lambda b: b["type"] == "error"
         and b["error"]["type"] == "api_error"),
    ],
)
async def test_unhandled_error_is_enveloped_without_leaks(gw, caplog, path, check) -> None:
    client, _ = gw
    caplog.set_level(logging.ERROR)
    # ASGITransport re-raises app exceptions: reaching the asserts proves nothing escaped the app
    r = await client.get(path)
    assert r.status_code == 500
    assert check(r.json()), r.text
    assert "secret-internal-detail" not in r.text and "RuntimeError" not in r.text
    assert "Traceback" not in r.text
    errors = [rec for rec in caplog.records if rec.levelno >= logging.ERROR]
    assert len(errors) == 1  # logged once, server-side only
    # the same client keeps working after the 500
    assert (await client.get("/healthz")).status_code == 200


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":' * DEPTH + b"1" + b"}" * DEPTH,
        b'{"tool_name":"Bash","tool_input":"\xff"}',
        json.dumps({"hook_event_name": ["PreToolUse"], "tool_name": "Bash"}).encode(),
        json.dumps({"hook_event_name": "PreToolUse", "tool_name": {"x": 1},
                    "tool_input": 5}).encode(),
    ],
    ids=["deep", "utf8", "event-name-list", "wrong-types"],
)
async def test_malformed_hook_is_fail_closed_warning(gw, caplog, raw) -> None:
    client, _ = gw
    caplog.set_level(logging.WARNING)
    assert len(raw) < LIMIT
    r = await client.post("/v1/hooks/claude-code", content=raw,
                          headers={"content-type": "application/json",
                                   "X-Aegis-Hook-Event": "PreToolUse"})
    assert r.status_code == 200
    out = r.json()["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny", out
    assert "malformed hook payload" in out["permissionDecisionReason"]
    assert not [rec for rec in caplog.records if rec.levelno >= logging.ERROR]
