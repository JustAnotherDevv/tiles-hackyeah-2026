"""META-V03: DLP-03 control (matrix gate, headers, body fields, text findings, profiles)."""

from __future__ import annotations

import json

import pytest

from aegis.controls.egress.dlp03_metadata import CONTROLS, MetadataStrip
from aegis.core.types import TextSegment
from aegis.egress import identifiers
from aegis.egress.headers import filter_response_headers, plan_headers
from aegis.egress.params import Dlp03Params, effective_params
from tests.unit.metadata_egress.helpers import (
    apply_all,
    make_cfg,
    make_ctx,
    make_interaction,
    make_snapshot,
)

CTL: MetadataStrip = CONTROLS[0]
VECTOR = ("Traceback in /Users/jdoe/acme-internal/trading/pnl.py on host jdoe-mbp.corp.local "
          "(10.20.30.40)")


@pytest.fixture(autouse=True)
def _fresh_sessions():
    identifiers.reset_local()
    yield
    identifiers.reset_local()


async def test_plugin_shape() -> None:
    assert (CTL.id, CTL.kind, CTL.priority) == ("DLP-03", "deterministic", 90)
    assert CTL.applies_to.surfaces == {"model.request", "mcp.call", "egress.request"}


async def test_research_vector_redacts() -> None:
    i = make_interaction(VECTOR)
    d = await CTL.evaluate(make_ctx(), i, make_cfg("DLP-03"))
    assert d is not None and d.action == "redact"
    out = apply_all(i, d.findings)[0]
    assert "jdoe" not in out and "10.20.30.40" not in out and "corp.local" not in out
    assert "/Users/[USERNAME_1]/acme-internal" in out
    assert all(f.category == "metadata" and f.excerpt and "jdoe" not in f.excerpt
               for f in d.findings)
    assert "jdoe" not in d.model_dump_json()


async def test_local_destination_untouched() -> None:
    i = make_interaction(VECTOR, dest="local",
                         headers={"x-forwarded-for": "10.1.2.3", "x-stainless-os": "MacOS"})
    assert await CTL.evaluate(make_ctx(), i, make_cfg("DLP-03")) is None


async def test_clean_request_returns_none() -> None:
    i = make_interaction("What is the P/E ratio of a bank?",
                         headers={"content-type": "application/json", "accept": "*/*"})
    assert await CTL.evaluate(make_ctx(), i, make_cfg("DLP-03")) is None


async def test_header_plan_exact() -> None:
    headers = {"x-forwarded-for": "10.1.2.3", "cookie": "s=1", "x-stainless-os": "MacOS",
               "anthropic-version": "2023-06-01", "anthropic-beta": "claude-code-20250219",
               "authorization": "<redacted>", "content-length": "10", "host": "api"}
    i = make_interaction("hello", headers=headers, meta={"wire": "anthropic"})
    d = await CTL.evaluate(make_ctx(), i, make_cfg("DLP-03"))
    assert d is not None and d.action == "redact"
    removed = sorted(m.path for m in d.mutations if m.target == "header" and m.op == "remove")
    assert removed == ["cookie", "x-forwarded-for", "x-stainless-os"]
    assert d.meta["headers_removed"] == removed
    assert "10.1.2.3" not in json.dumps(d.meta)


def test_plan_headers_kinds() -> None:
    h = {"user-agent": "python-httpx/0.28", "x-app": "cli", "authorization": "Bearer x",
         "cookie": "a", "accept": "application/json", "x-request-source": "agent"}
    eg = plan_headers(h, kind="egress", host="crm.saas.test")
    assert set(eg.remove) == {"authorization", "cookie"}
    assert eg.set == {"user-agent": "aegis/0.1"}
    eg2 = plan_headers({}, kind="egress")
    assert eg2.set == {"user-agent": "aegis/0.1"}  # egress always gets the neutral UA
    an = plan_headers(h, kind="anthropic")
    assert "user-agent" not in an.set and "authorization" not in an.remove
    strict = Dlp03Params.model_validate({"headers": {"mode": "allowlist"}}).headers
    al = plan_headers(h, kind="anthropic", params=strict)
    assert "x-request-source" in al.remove and "x-app" not in al.remove
    p = Dlp03Params.model_validate({"headers": {"pass_auth_hosts": ["*.saas.test"]}}).headers
    assert "authorization" not in plan_headers(h, kind="egress", params=p, host="crm.saas.test").remove


def test_filter_response_headers() -> None:
    out = filter_response_headers({"Content-Type": "application/json", "Set-Cookie": "a=b",
                                   "Server": "nginx", "ETag": "x", "X-Internal-Trace": "1"})
    assert out == {"content-type": "application/json", "etag": "x"}


async def test_user_id_pseudonymized_deterministically() -> None:
    uid = json.dumps({"device_id": "dev-0123456789", "account_uuid": "acc-0123456789",
                      "session_id": "ses-keepme"}, separators=(",", ":"))
    raw = {"metadata": {"user_id": uid}, "user": "jane.doe@acme-capital.example"}
    vals = []
    for _ in range(2):
        i = make_interaction("hello", raw=raw)
        d = await CTL.evaluate(make_ctx(), i, make_cfg("DLP-03"))
        assert d is not None
        muts = {m.path: m.value for m in d.mutations if m.target == "body"}
        vals.append(muts)
        assert "dev-0123456789" not in d.model_dump_json()
        assert "acc-0123456789" not in d.model_dump_json()
    assert vals[0] == vals[1]
    new = json.loads(vals[0]["metadata.user_id"])
    assert new["device_id"].startswith("anon-") and new["account_uuid"].startswith("anon-")
    assert new["session_id"] == "ses-keepme"
    assert vals[0]["user"].startswith("aegis-anon-")


async def test_already_pseudonymized_is_idempotent() -> None:
    raw = {"metadata": {"user_id": json.dumps({"device_id": "anon-abc", "session_id": "s"})}}
    i = make_interaction("hello", raw=raw)
    assert await CTL.evaluate(make_ctx(), i, make_cfg("DLP-03")) is None


async def test_matrix_allow_skips_text_but_strips_headers() -> None:
    snap = make_snapshot(destinations={"matrix": {
        "INTERNAL": {"local": "allow", "remote": "allow", "third_party": "redact"}}})
    i = make_interaction(VECTOR, headers={"x-stainless-os": "MacOS"})
    d = await CTL.evaluate(make_ctx(snap), i, make_cfg("DLP-03"))
    assert d is not None
    assert d.findings == []
    assert [m.path for m in d.mutations] == ["x-stainless-os"]


async def test_matrix_block_cell() -> None:
    snap = make_snapshot(destinations={"matrix": {
        "INTERNAL": {"local": "allow", "remote": "block", "third_party": "block"}}})
    d = await CTL.evaluate(make_ctx(snap), make_interaction(VECTOR), make_cfg("DLP-03"))
    assert d is not None and d.action == "block"


async def test_thinking_segment_untouched() -> None:
    segs = [TextSegment(path="messages[0].content[0].thinking", text=VECTOR, redactable=False),
            TextSegment(path="messages[0].content[1].text", text="hi /Users/jdoe/x")]
    i = make_interaction(segments=segs)
    d = await CTL.evaluate(make_ctx(), i, make_cfg("DLP-03"))
    assert d is not None
    assert all(f.segment_index == 1 for f in d.findings)


async def test_third_party_generalizes() -> None:
    i = make_interaction("log at /Users/jdoe/app on 192.168.1.20", surface="mcp.call",
                         dest="third_party")
    d = await CTL.evaluate(make_ctx(), i, make_cfg("DLP-03"))
    assert d is not None
    assert apply_all(i, d.findings)[0] == "log at ~/app on [PRIVATE_IP]"


async def test_learned_identifier_across_segments_and_turns() -> None:
    ctx = make_ctx(session_id="ses_learn")
    i1 = make_interaction("cwd /Users/jdoe/work")
    await CTL.evaluate(ctx, i1, make_cfg("DLP-03"))
    i2 = make_interaction("total 8\ndrwxr-xr-x 5 jdoe staff 160 trading")
    d = await CTL.evaluate(ctx, i2, make_cfg("DLP-03"))
    assert d is not None
    assert "jdoe" not in apply_all(i2, d.findings)[0]


async def test_exempt_agents_skip_text() -> None:
    cfg = make_cfg("DLP-03", params={"exempt_agents": ["claude-code@*"]})
    ctx = make_ctx(agent_id="claude-code@platform")
    assert await CTL.evaluate(ctx, make_interaction(VECTOR), cfg) is None


async def test_profiles() -> None:
    perm = make_snapshot(profile="permissive")
    i = make_interaction(VECTOR, headers={"x-stainless-os": "MacOS"})
    d = await CTL.evaluate(make_ctx(perm), i, make_cfg("DLP-03"))
    assert d is not None and d.findings == [] and d.mutations  # text off, headers still stripped
    strict = make_snapshot(profile="strict")
    i = make_interaction("hi", headers={"x-app": "cli", "x-request-source": "a",
                                        "anthropic-version": "2023-06-01"},
                         meta={"wire": "anthropic"})
    d = await CTL.evaluate(make_ctx(strict), i, make_cfg("DLP-03"))
    assert d is not None
    assert [m.path for m in d.mutations] == ["x-request-source"]
    cfg = make_cfg("DLP-03", params={"text": {"paths": False}})
    d = await CTL.evaluate(make_ctx(strict), make_interaction("/Users/jdoe/x"), cfg)
    assert d is None  # explicit param beats the profile


def test_legacy_seed_params_mapped() -> None:
    cfg = make_cfg("DLP-03", params={"strip_body_fields": ["metadata.user_id", "user"],
                                     "generalize": {"paths": True, "ips": False}})
    p = effective_params(Dlp03Params, cfg, "balanced")
    assert [r.path for r in p.body_fields] == ["metadata.user_id", "user"]
    assert p.text.private_ips is False and p.text.paths is True


async def test_mac_address() -> None:
    i = make_interaction("en0 ether 3c:22:fb:12:34:56 status: active")
    d = await CTL.evaluate(make_ctx(), i, make_cfg("DLP-03"))
    assert d is not None and [f.entity for f in d.findings] == ["MAC_ADDRESS"]
