"""GW-V03 bus + GW-V10 events: replay, since, filter, drop-oldest, heartbeat, Last-Event-ID."""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

from aegis.api.routes.events import event_stream, parse_events
from aegis.core import bus as bus_mod
from aegis.core.bus import EventBus
from aegis.core.types import DecisionSummary, Destination, Identity, utcnow


async def _take(agen, n: int, timeout: float = 2.0) -> list:
    out = []

    async def run() -> None:
        async for item in agen:
            out.append(item)
            if len(out) >= n:
                return

    await asyncio.wait_for(run(), timeout)
    return out


async def test_publish_recent_since_filter() -> None:
    bus = EventBus()
    for n in range(5):
        bus.publish("decision" if n % 2 == 0 else "system", {"n": n})
    assert [m.id for m in bus.recent(3)] == [3, 4, 5]
    assert [m.data["n"] for m in bus.recent(10, {"system"})] == [1, 3]
    assert [m.id for m in bus.since(3)] == [4, 5]
    assert [m.id for m in bus.since(0, {"decision"})] == [1, 3, 5]


async def test_pydantic_payload_dumped_json() -> None:
    bus = EventBus()
    summary = DecisionSummary(id="dec_x", ts=utcnow(), request_id="r", action="block",
                              kind="model_call", surface="model.request", direction="out",
                              destination=Destination(), identity=Identity(), session_id="s",
                              source="test")
    msg = bus.publish("decision", summary)
    assert msg.data["id"] == "dec_x" and isinstance(msg.data["ts"], str)
    json.dumps(msg.data)


async def test_subscribe_replay_then_live() -> None:
    bus = EventBus()
    bus.publish("a", {"n": 1})
    bus.publish("b", {"n": 2})
    agen = bus.subscribe(replay=5)
    first = await _take(agen, 2)
    assert [m.event for m in first] == ["a", "b"]
    bus.publish("c", {"n": 3})
    nxt = await asyncio.wait_for(agen.__anext__(), 1)
    assert nxt.event == "c" and nxt.id == 3
    await agen.aclose()
    assert bus.subscriber_count == 0


async def test_subscribe_last_id_and_filter() -> None:
    bus = EventBus()
    for e in ("decision", "system", "decision", "decision"):
        bus.publish(e, {})
    agen = bus.subscribe({"decision"}, last_id=1)
    got = await _take(agen, 2)
    assert [m.id for m in got] == [3, 4]
    await agen.aclose()


async def test_slow_subscriber_drops_oldest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bus_mod, "QUEUE_SIZE", 3)
    bus = EventBus()
    agen = bus.subscribe()
    task = asyncio.ensure_future(agen.__anext__())  # registers the subscriber
    await asyncio.sleep(0)
    for n in range(10):  # publisher never blocks
        bus.publish("x", {"n": n})
    first = await asyncio.wait_for(task, 1)
    rest = await _take(agen, 2)
    ns = [first.data["n"]] + [m.data["n"] for m in rest]
    assert ns[-1] == 9 and len(ns) == 3
    await agen.aclose()


async def test_publish_from_thread() -> None:
    bus = EventBus()
    agen = bus.subscribe()
    task = asyncio.ensure_future(agen.__anext__())
    await asyncio.sleep(0)
    t = threading.Thread(target=lambda: bus.publish("from-thread", {"ok": True}))
    t.start()
    t.join()
    msg = await asyncio.wait_for(task, 1)
    assert msg.event == "from-thread"
    await agen.aclose()


async def test_bus_close_ends_subscribers() -> None:
    bus = EventBus()
    agen = bus.subscribe()
    task = asyncio.ensure_future(_take(agen, 5))
    await asyncio.sleep(0.01)
    bus.close()
    assert await asyncio.wait_for(task, 1) == []


# ------------------------------------------------------------------ SSE generator
async def test_event_stream_replay_filter_heartbeat() -> None:
    bus = EventBus()
    bus.publish("decision", {"id": "dec_1"})
    bus.publish("system", {"level": "info", "message": "hi"})
    stream = event_stream(bus, events={"decision", "heartbeat"}, replay=10, heartbeat_s=0.05)
    frames = await _take(stream, 2)
    assert frames[0]["event"] == "decision" and frames[0]["id"] == "1"
    assert json.loads(frames[0]["data"]) == {"id": "dec_1"}
    assert frames[1]["event"] == "heartbeat" and "ts" in json.loads(frames[1]["data"])
    bus.publish("decision", {"id": "dec_2"})
    nxt = await asyncio.wait_for(stream.__anext__(), 1)
    assert nxt["event"] == "decision" and nxt["id"] == "3"
    await stream.aclose()


async def test_event_stream_last_event_id_resume() -> None:
    bus = EventBus()
    for n in range(4):
        bus.publish("decision", {"n": n})
    stream = event_stream(bus, last_id=2, heartbeat_s=5)
    frames = await _take(stream, 2)
    assert [f["id"] for f in frames] == ["3", "4"]
    await stream.aclose()


def test_parse_events() -> None:
    assert parse_events(None) is None
    assert parse_events("decision, system,") == {"decision", "system"}


async def test_events_endpoint_headers(tmp_path) -> None:
    """Route wiring: SSE response object with no-buffering headers (body not consumed)."""
    from starlette.requests import Request

    from aegis.api.routes.events import events_endpoint
    from gw_fakes import FakeRT, route_app
    from aegis.api.routes import events

    rt = FakeRT(tmp_path)
    app = route_app(rt, events)
    scope = {"type": "http", "method": "GET", "path": "/api/events", "headers": [
        (b"last-event-id", b"5")], "query_string": b"", "app": app}
    req = Request(scope)
    resp = await events_endpoint(req, events="decision", replay=0, view_as=None,
                                 last_event_id=None)
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"
    assert resp.media_type == "text/event-stream"
