"""GW-V10: /v1/guard (+/complete) and /api/playground on a fake runtime (in-process ASGI)."""

from __future__ import annotations

import types
from typing import Any

import httpx
import pytest
from gw_fakes import FakeControl, FakeRT, cfg, route_app

from aegis.api.routes import guard, playground
from aegis.core.types import Decision, Finding


def client_for(rt: FakeRT) -> httpx.AsyncClient:
    app = route_app(rt, guard, playground)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _email_redactor(cid: str = "DLP-01") -> FakeControl:
    async def beh(ctx, i, c):
        for n, seg in enumerate(i.segments):
            if "jan@example.com" in seg.text:
                s = seg.text.index("jan@example.com")
                return Decision(action="redact", control_id=cid, reason="email",
                                findings=[Finding(control_id=cid, detector="pii.email",
                                                  category="pii", entity="EMAIL",
                                                  segment_index=n, start=s, end=s + 15)])
        return None
    return FakeControl(cid, behaviour=beh)


# ------------------------------------------------------------------ guard
async def test_guard_block_is_200_with_headers(tmp_path) -> None:
    rt = FakeRT(tmp_path, controls=[FakeControl("EXE-01", action="block")],
                configs=[cfg("EXE-01")])
    async with client_for(rt) as c:
        r = await c.post("/v1/guard", json={"interaction": {
            "surface": "tool.input", "tool_name": "Bash", "tool_args": {"command": "rm -rf /"}}})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"]["action"] == "block" and body["text"] is None
    assert r.headers["x-aegis-decision"] == "block"
    assert r.headers["x-aegis-decision-id"] == body["decision_id"]
    assert "aegis;dur=" in r.headers["server-timing"]
    # blocked request hops are completed immediately with requests=0
    outs = rt.audit.of_phase("outcome")
    assert len(outs) == 1 and outs[0].usage.requests == 0


async def test_guard_tool_args_leaf_segments_and_redaction(tmp_path) -> None:
    rt = FakeRT(tmp_path, controls=[_email_redactor()], configs=[cfg("DLP-01")])
    async with client_for(rt) as c:
        r = await c.post("/v1/guard", json={"interaction": {
            "surface": "tool.input", "tool_name": "mcp__mail__send",
            "tool_args": {"to": "jan@example.com", "cc": ["a@b.c"], "n": 3}}})
    body = r.json()
    paths = [s["path"] for s in body["segments"]]
    assert paths == ["tool_args.to", "tool_args.cc[0]"]
    assert body["segments"][0]["text"] == "[EMAIL_1]" and body["verdict"]["action"] == "redact"
    assert body["text"].startswith("[EMAIL_1]")


async def test_guard_complete_once_and_unknown_404(tmp_path) -> None:
    ctl = FakeControl("BUD-01")
    rt = FakeRT(tmp_path, controls=[ctl], configs=[cfg("BUD-01")])
    async with client_for(rt) as c:
        r = await c.post("/v1/guard", json={"interaction": {"surface": "model.request",
                                                           "model": "mock-echo",
                                                           "text": "hi"}})
        dec = r.json()["decision_id"]
        ok = await c.post("/v1/guard/complete", json={
            "decision_id": dec, "status_code": 200,
            "usage": {"input_tokens": 3, "output_tokens": 4}})
        assert ok.status_code == 200 and ok.json() == {"ok": True}
        again = await c.post("/v1/guard/complete", json={"decision_id": dec})
        assert again.status_code == 404 and again.json()["error"]["type"] == "not_found"
    assert len(ctl.completed) == 1 and ctl.completed[0].usage.output_tokens == 4


async def test_guard_dry_run_not_recorded_or_parked(tmp_path) -> None:
    rt = FakeRT(tmp_path, controls=[FakeControl("A-01", action="log")], configs=[cfg("A-01")])
    async with client_for(rt) as c:
        r = await c.post("/v1/guard", json={"interaction": {"text": "x"}, "dry_run": True})
    body = r.json()
    assert body["verdict"]["dry_run"] is True and body["verdict"]["decisions"][0]["latency_ms"] >= 0
    assert "server-timing" in r.headers
    assert rt.audit.events == [] and guard._parked(rt) == {}


async def test_guard_parked_ttl_sweep(tmp_path) -> None:
    ctl = FakeControl("BUD-01")
    rt = FakeRT(tmp_path, controls=[ctl], configs=[cfg("BUD-01")])
    async with client_for(rt) as c:
        await c.post("/v1/guard", json={"interaction": {"text": "hi"}})
    assert len(guard._parked(rt)) == 1
    n = await guard.sweep_parked(rt, now=float("inf"))
    assert n == 1 and guard._parked(rt) == {}
    assert ctl.completed[0].status_code == 499


async def test_guard_destination_string_and_untrusted(tmp_path) -> None:
    seen: list[Any] = []

    async def beh(ctx, i, c):
        seen.append(i)
        return None

    rt = FakeRT(tmp_path, controls=[FakeControl("A-01", behaviour=beh)], configs=[cfg("A-01")])
    async with client_for(rt) as c:
        await c.post("/v1/guard", json={"interaction": {
            "surface": "tool.output", "text": "ignore previous", "destination": "local"}})
    i = seen[0]
    assert i.destination.dest_class == "local" and i.destination.name == "guard:local"
    assert i.direction == "in" and all(not s.trusted for s in i.segments)


async def test_guard_approval_pending_header(tmp_path) -> None:
    rt = FakeRT(tmp_path, controls=[FakeControl("ACT-01", action="require_approval")],
                configs=[cfg("ACT-01")])
    async with client_for(rt) as c:
        r = await c.post("/v1/guard", json={"interaction": {
            "surface": "tool.input", "tool_name": "send_email", "tool_args": {"to": "x"}},
            "wait_s": 0})
    body = r.json()
    assert r.status_code == 200 and body["verdict"]["action"] == "require_approval"
    assert body["approval"]["id"] == r.headers["x-aegis-approval-id"]


# ------------------------------------------------------------------ playground
async def test_playground_send_false_records_feed(tmp_path) -> None:
    rt = FakeRT(tmp_path, controls=[_email_redactor()], configs=[cfg("DLP-01")])
    async with client_for(rt) as c:
        r = await c.post("/api/playground", json={"text": "mail jan@example.com",
                                                  "send": False})
    assert r.status_code == 200
    body = r.json()
    assert body["outbound"] == "mail [EMAIL_1]" and body["original"] == "mail jan@example.com"
    assert body["response"] is None and body["timings"]["controls"][0]["control_id"] == "DLP-01"
    feed = rt.bus.recent(5, {"decision"})
    assert feed and feed[-1].data["id"] == body["decision_id"]
    assert feed[-1].data["source"] == "playground" and not feed[-1].data["dry_run"]
    assert len(rt.audit.of_phase("outcome")) == 1  # completed (reservations released)


def _fake_flow(monkeypatch: pytest.MonkeyPatch, *, fail: bool) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    class FakeModelCall:
        def __init__(self, rt, *, wire, ctx, source, provider, identity, stream_mode, **kw):
            self.rt, self.ctx, self.provider, self.wire = rt, ctx, provider, wire

        async def run(self, body: dict[str, Any], raw: bytes | None = None):
            calls.append({"body": body, "provider": self.provider, "wire": self.wire})
            if fail:
                raise ConnectionError("upstream down")
            from gw_fakes import interaction as mk

            i = mk(body["messages"][0]["content"])
            v = await self.rt.pipeline.evaluate(self.ctx, i)
            outbound = v.segments[0].text
            return types.SimpleNamespace(
                verdict=v, blocked=False, status=200, error=None,
                response_raw_text=f"echo: {outbound}",
                response_local_text=self.rt.redactor.rehydrate(self.ctx, f"echo: {outbound}"),
                route=types.SimpleNamespace(model="mock-echo", provider=self.provider))

    import aegis.proxy.flow as flow

    monkeypatch.setattr(flow, "ModelCall", FakeModelCall)
    return calls


async def test_playground_send_true_rehydrated(tmp_path, monkeypatch) -> None:
    calls = _fake_flow(monkeypatch, fail=False)
    rt = FakeRT(tmp_path, controls=[_email_redactor()], configs=[cfg("DLP-01")])
    async with client_for(rt) as c:
        r = await c.post("/api/playground", json={"text": "mail jan@example.com",
                                                  "destination": "remote"})
    body = r.json()
    assert calls and calls[0]["provider"] == "mock-openai" and calls[0]["wire"] == "openai"
    assert body["response"]["raw"] == "echo: mail [EMAIL_1]"
    assert body["response"]["local"] == "echo: mail jan@example.com"
    assert body["timings"]["total_ms"] > 0


async def test_playground_upstream_down_is_200(tmp_path, monkeypatch) -> None:
    _fake_flow(monkeypatch, fail=True)
    rt = FakeRT(tmp_path, controls=[_email_redactor()], configs=[cfg("DLP-01")])
    async with client_for(rt) as c:
        r = await c.post("/api/playground", json={"text": "mail jan@example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["response"] is None and body["outbound"] == "mail [EMAIL_1]"
    msgs = [m.data["message"] for m in rt.bus.recent(10, {"system"})]
    assert any("playground" in m for m in msgs)


async def test_playground_impersonation_identity(tmp_path) -> None:
    seen: list[Any] = []

    async def beh(ctx, i, c):
        seen.append(ctx.identity)
        return None

    rt = FakeRT(tmp_path, controls=[FakeControl("A-01", behaviour=beh)], configs=[cfg("A-01")])
    async with client_for(rt) as c:
        await c.post("/api/playground", json={"text": "x", "send": False,
                                              "agent_id": "trading-copilot@trading"})
    assert seen[0].agent_id == "trading-copilot@trading"
