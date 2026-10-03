"""Router, upstream header policy, timing helpers, block semantics (A-06/A-07)."""

from __future__ import annotations

from aegis.core.policy_schema import (
    ModelRoute,
    ModelsSection,
    PolicyDoc,
    PolicySnapshot,
    ProviderConfig,
)
from aegis.core.timing import Stopwatch, add_timing, server_timing_header, timed
from aegis.core.types import Decision, Mutation, RequestContext, Verdict
from aegis.proxy.blocking import block_info, decision_headers
from aegis.proxy.router import resolve_route
from aegis.proxy.upstream import outbound_headers, response_headers
from aegis.settings import Settings


def snap(doc: PolicyDoc | None = None) -> PolicySnapshot:
    return PolicySnapshot(version=1, sha256="x", doc=doc or PolicyDoc())


def test_builtin_routes() -> None:
    s = Settings()
    r = resolve_route("mock-echo", "anthropic", snap(), s)
    assert r.provider == "mock-anthropic" and r.dest_class == "remote"
    assert r.url("messages", "beta=true") == "http://127.0.0.1:8791/v1/messages?beta=true"
    assert r.url("count_tokens") == "http://127.0.0.1:8791/v1/messages/count_tokens"
    r = resolve_route("mock-echo", "openai", snap(), s)
    assert r.url("chat") == "http://127.0.0.1:8791/v1/chat/completions"
    r = resolve_route("claude-sonnet-4-5", "anthropic", snap(), s)
    assert r.provider == "anthropic" and r.cfg.passthrough_auth
    r = resolve_route("aegis-judge", "openai", snap(), s)
    assert r.provider == "ollama-openai" and r.dest_class == "local"
    r = resolve_route("gpt-oss:20b:cloud", "ollama", snap(), s)
    assert r.provider == "ollama" and r.dest_class == "remote"  # :cloud leaves the machine
    assert r.url("generate") == "http://127.0.0.1:11434/api/generate"
    assert resolve_route(None, "openai", snap(), s) is None


def test_enabled_if_env_and_ollama_url(monkeypatch) -> None:
    s = Settings(ollama_url="http://10.0.0.5:11434")
    r = resolve_route("gpt-4.1-mini", "openai", snap(), s)
    assert r.provider == "ollama-openai" and r.url_base == "http://10.0.0.5:11434/v1"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    r = resolve_route("gpt-4.1-mini", "openai", snap(), s)
    assert r.provider == "openai" and r.api_key == "sk-test-not-real"


def test_policy_routes_wire_filter_and_cross_wire_skip() -> None:
    doc = PolicyDoc(
        providers={"p-openai": ProviderConfig(wire="openai", base_url="http://up:1/v1")},
        models=ModelsSection(routes=[
            ModelRoute(match="claude-*", provider="p-openai"),  # wrong wire for anthropic
            ModelRoute(match="foo-*", provider="p-openai", wire="openai"),
        ]))
    r = resolve_route("claude-haiku-4-5", "anthropic", snap(doc), Settings())
    assert r.provider == "anthropic"  # cross-wire route skipped -> builtin fallback
    r = resolve_route("foo-1", "openai", snap(doc), Settings())
    assert r.provider == "p-openai" and r.url("chat") == "http://up:1/v1/chat/completions"
    r = resolve_route("x", "openai", snap(doc), Settings(), provider="mock-openai")
    assert r.provider == "mock-openai"


def test_outbound_headers_policy() -> None:
    inbound = {
        "Host": "127.0.0.1:8787", "Content-Length": "10", "Authorization": "Bearer sk-ant-oat01-x",
        "anthropic-beta": "oauth-2025-04-20", "X-Aegis-Agent": "a", "x-aegis-agent-key": "aegis_k",
        "Accept-Encoding": "gzip", "Cookie": "c=1", "x-stainless-retry-count": "0",
        "Connection": "keep-alive",
    }
    out = outbound_headers(inbound, wire="anthropic", passthrough_auth=True)
    assert out["authorization"] == "Bearer sk-ant-oat01-x"
    assert out["anthropic-beta"] == "oauth-2025-04-20"
    assert out["accept-encoding"] == "identity"
    assert out["x-stainless-retry-count"] == "0"
    for gone in ("host", "content-length", "x-aegis-agent", "x-aegis-agent-key", "cookie",
                 "connection"):
        assert gone not in out
    # aegis key in Authorization never forwarded, even with passthrough
    out = outbound_headers({"authorization": "Bearer aegis_demo_x"}, wire="openai",
                           passthrough_auth=True, api_key="sk-prov")
    assert out["authorization"] == "Bearer sk-prov"
    # no passthrough -> client creds dropped, provider key injected
    out = outbound_headers({"x-api-key": "sk-ant-api-client"}, wire="anthropic",
                           passthrough_auth=False, api_key="sk-ant-prov")
    assert out["x-api-key"] == "sk-ant-prov"
    out = outbound_headers({"authorization": "Bearer user"}, wire="openai",
                           passthrough_auth=False)
    assert "authorization" not in out
    # header mutations applied before the credential policy
    out = outbound_headers({"user-agent": "x", "x-claude-code-session-id": "s"},
                           wire="anthropic", passthrough_auth=True, mutations=[
                               Mutation(target="header", op="remove",
                                        path="x-claude-code-session-id"),
                               Mutation(target="header", op="set", path="x-tag", value="1"),
                               Mutation(target="body", op="set", path="max_tokens", value=1)])
    assert "x-claude-code-session-id" not in out and out["x-tag"] == "1"
    resp = response_headers({"content-type": "text/event-stream", "content-length": "5",
                             "content-encoding": "gzip", "request-id": "r",
                             "anthropic-ratelimit-unified-status": "allowed"})
    assert resp == {"content-type": "text/event-stream", "request-id": "r",
                    "anthropic-ratelimit-unified-status": "allowed"}


def test_timing_helpers() -> None:
    ctx = RequestContext(request_id="req_1", t0=0.0)
    add_timing(ctx, "ctl", 1.5)
    add_timing(ctx, "ctl", 0.5)
    add_timing(ctx, "ctl.DLP-01", 1.2)
    add_timing(ctx, "ctl.INJ-02", 0.8)
    with timed(ctx, "parse"):
        pass
    assert ctx.timings["ctl"] == 2.0 and "parse" in ctx.timings
    h = server_timing_header(ctx, total_ms=100.0, upstream_ms=90.0)
    assert h.startswith('aegis;dur=10.00;desc="gateway overhead", ctl;dur=2.00, upstream;dur=90.00')
    assert h.index("ctl-DLP-01") < h.index("ctl-INJ-02")
    sw = Stopwatch()
    assert sw.lap("a") >= 0 and "a" in sw.laps


def test_decision_headers_and_block_info() -> None:
    p = Decision(action="block", control_id="BUD-01", http_status=402,
                 error_type="budget_exceeded", meta={"response_headers": {
                     "X-Aegis-Budget-Remaining": "usd=0;scope=team:x", "set-cookie": "no"}})
    other = Decision(action="log", control_id="EXE-04", meta={"response_headers": {
        "x-aegis-budget-remaining": "loser", "x-aegis-loop": "1"}})
    mon = Decision(action="block", control_id="SIG-01", mode="monitor",
                   meta={"response_headers": {"x-aegis-mon": "1"}})
    v = Verdict(id="dec_9", request_id="r", interaction_id="i", action="block", primary=p,
                decisions=[other, p, mon])
    h = decision_headers([v])
    assert h == {"x-aegis-budget-remaining": "usd=0;scope=team:x", "x-aegis-loop": "1"}
    info = block_info(v)
    assert info.status == 402 and info.error_type == "budget_exceeded"
    assert info.headers["x-should-retry"] == "false"
    kill = Decision(action="block", control_id="EXE-04", http_status=403, error_type="killed")
    info = block_info(Verdict(id="d", request_id="r", interaction_id="i", action="block",
                              primary=kill), wire="openai")
    assert info.status == 429 and info.headers["retry-after"] == "3600"
