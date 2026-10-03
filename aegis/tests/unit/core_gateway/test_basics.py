"""GW-V03: paths, crypto, sessions, settings, log scrubbing, errors."""

from __future__ import annotations

import json
import logging
import os
import stat

import pytest

from aegis.core import crypto
from aegis.core.errors import (
    api_error,
    block_status,
    decision_headers,
    verdict_error,
    wire_body,
    wire_for_path,
)
from aegis.core.paths import get_path, glob_match, remove_path, set_path
from aegis.core.sessions import (
    SessionStore,
    generated_session_id,
    resolve_session_id,
    session_hint_from_body,
)
from aegis.core.types import Decision, Verdict
from aegis.log import SecretScrubFilter, scrub
from aegis.settings import Settings


# ------------------------------------------------------------------ paths
def test_get_set_remove_paths() -> None:
    doc = {"a": {"b": [{"id": "DLP-01", "x": 1}, {"id": "DLP-02", "x": 2}]},
           "budgets": {"limits": [{"scope": "team:x", "window": "day", "usd": 10},
                                  {"scope": "team:x", "window": "month", "usd": 99}]}}
    assert get_path(doc, "a.b[1].x") == 2
    assert get_path(doc, "a.b[-1].id") == "DLP-02"
    assert get_path(doc, "a.b[id=DLP-01].x") == 1
    assert get_path(doc, "budgets.limits[scope=team:x,window=month].usd") == 99
    assert get_path(doc, "a.missing.z", "dflt") == "dflt"
    set_path(doc, "a.b[id=DLP-02].x", 5)
    assert doc["a"]["b"][1]["x"] == 5
    set_path(doc, "new.deep.key", "v")
    assert doc["new"] == {"deep": {"key": "v"}}
    set_path(doc, 'headers["x.y"]', "dotted")
    assert doc["headers"]["x.y"] == "dotted"
    assert remove_path(doc, "a.b[0]") is True
    assert [i["id"] for i in doc["a"]["b"]] == ["DLP-02"]
    assert remove_path(doc, "a.b[9]") is False
    assert remove_path(doc, "nope.nope") is False
    assert remove_path(doc, "budgets.limits[scope=team:x,window=day]") is True
    assert len(doc["budgets"]["limits"]) == 1


def test_paths_on_models_and_messages() -> None:
    body = {"messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]}
    assert get_path(body, "messages[0].content[0].text") == "hi"
    set_path(body, "messages[0].content[0].text", "bye")
    assert body["messages"][0]["content"][0]["text"] == "bye"
    s = Settings(data_dir="x")
    assert get_path(s, "log_level") == "INFO"


def test_glob_match() -> None:
    assert glob_match("*", None)
    assert glob_match("*", "x")
    assert not glob_match("team-*", None)
    assert glob_match("claude-*", "claude-sonnet-5")
    assert not glob_match("Claude-*", "claude-x")  # case sensitive


# ------------------------------------------------------------------ crypto
def test_hmac_stable_per_key_and_purpose(tmp_path) -> None:
    crypto.configure(data_dir=tmp_path / "d1")
    a1 = crypto.hmac_hex("secret", purpose="fp")
    a2 = crypto.hmac_hex(b"secret", purpose="fp")
    b = crypto.hmac_hex("secret", purpose="approval")
    assert a1 == a2 and a1 != b and len(a1) == 64
    key_file = tmp_path / "d1" / "keys" / "hmac.key"
    assert key_file.is_file()
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    # persisted: a fresh load reads the same key
    crypto.reset_key_cache()
    assert crypto.hmac_hex("secret", purpose="fp") == a1
    # a different data dir = a different key
    crypto.configure(data_dir=tmp_path / "d2")
    assert crypto.hmac_hex("secret", purpose="fp") != a1
    # explicit key wins
    crypto.configure(data_dir=tmp_path / "d3", key="k" * 32)
    crypto.hmac_hex("x")
    assert crypto.key_source() == "env"
    assert not (tmp_path / "d3" / "keys" / "hmac.key").exists()


# ------------------------------------------------------------------ sessions
def test_session_resolution_order() -> None:
    h = {"X-Aegis-Session": "s1", "x-claude-code-session-id": "cc", "mcp-session-id": "m"}
    assert resolve_session_id(h, "body", "agent:a") == "s1"
    assert resolve_session_id({"x-claude-code-session-id": "cc", "mcp-session-id": "m"}) == "cc"
    assert resolve_session_id({"Mcp-Session-Id": "m"}) == "m"
    assert resolve_session_id({}, "hint", "agent:a") == "hint"
    gen = resolve_session_id({}, None, "agent:a")
    assert gen.startswith("ses_") and len(gen) == 24
    assert gen == resolve_session_id({}, None, "agent:a")  # deterministic per hour
    assert gen != resolve_session_id({}, None, "agent:b")
    assert generated_session_id("agent:a") == gen


def test_session_hint_from_body() -> None:
    body = {"metadata": {"user_id": json.dumps({"device_id": "d", "session_id": "abc"})}}
    assert session_hint_from_body(body) == "abc"
    assert session_hint_from_body({"session_id": "s"}) == "s"
    assert session_hint_from_body({"metadata": {"user_id": "plain"}}) is None
    assert session_hint_from_body(None) is None


def test_session_store_lru_and_touch() -> None:
    store = SessionStore(None, max_sessions=3)
    for n in range(5):
        store.touch(f"s{n}")
    assert [s.session_id for s in store.all()] == ["s2", "s3", "s4"]
    st = store.get("s4")
    st.data["taint"] = True
    assert store.get("s4").data["taint"] is True
    store.touch("s4")
    assert store.requests("s4") == 2


async def test_session_flush_to_db(tmp_path) -> None:
    from gw_fakes import FakeRT

    rt = FakeRT(tmp_path)
    store = SessionStore(rt)
    await store.start()
    store.touch("ses_1", source="proxy")
    assert await store.flush() == 1
    conn = rt.db()
    row = conn.execute("SELECT id, requests, source FROM sessions").fetchone()
    conn.close()
    assert tuple(row) == ("ses_1", 1, "proxy")
    await store.stop()


# ------------------------------------------------------------------ settings & log
def test_settings_from_env(tmp_path) -> None:
    s = Settings.from_env({"AEGIS_PORT": "0", "AEGIS_DEMO_MODE": "0", "AEGIS_DATA_DIR": "rel",
                           "ANTHROPIC_API_KEY": "k", "AEGIS_SEMANTIC_RAM_MB": "512"})
    assert s.port == 0 and s.demo_mode is False and s.data_dir.is_absolute()
    assert s.anthropic_api_key == "k" and s.semantic_ram_mb == 512
    assert s.env("ANTHROPIC_API_KEY") == "k"
    assert Settings(host="0.0.0.0", port=9).public_url == "http://127.0.0.1:9"


def test_secret_scrub_filter() -> None:
    assert "sk-ant-***" in scrub("token sk-ant-oat01-abcdef")
    assert "aegis_***" in scrub("key aegis_demo_123")
    assert "Bearer ***" in scrub("Authorization: Bearer abc.def")
    rec = logging.LogRecord("aegis.x", logging.INFO, __file__, 1, "auth %s", ("Bearer xyz",),
                            None)
    SecretScrubFilter().filter(rec)
    assert "xyz" not in rec.getMessage()


# ------------------------------------------------------------------ errors (A-06, A-07)
def test_block_status_stop_codes() -> None:
    assert block_status(Decision(control_id="X", action="block")) is None
    st, et, h = block_status(Decision(control_id="BUD-01", action="block", http_status=402,
                                      error_type="budget_exceeded"))
    assert (st, et, h["x-should-retry"]) == (402, "budget_exceeded", "false")
    st, et, h = block_status(Decision(control_id="EXE-04", action="block", error_type="killed"))
    assert st == 429 and et == "killed" and h["retry-after"] == "3600"
    assert h["x-should-retry"] == "false"  # kill switch never 403 (A-07)
    st, et, h = block_status(Decision(control_id="EXE-04", action="block", http_status=429,
                                      retry_after_s=30))
    assert (st, et, h["retry-after"]) == (429, "rate_limited", "30")
    st, et, _ = block_status(Decision(control_id="GOV-01", action="block",
                                      error_type="unauthenticated"))
    assert st == 401


def test_decision_headers_merge() -> None:
    d1 = Decision(control_id="BUD-01", action="allow",
                  meta={"response_headers": {"X-Aegis-Budget-Remaining": "usd=1",
                                             "set-cookie": "bad"}})
    d2 = Decision(control_id="ZZZ", action="block", retry_after_s=9,
                  meta={"response_headers": {"x-aegis-budget-remaining": "usd=2"}})
    v = Verdict(id="dec_1", request_id="r", interaction_id="i", action="block", primary=d2,
                decisions=[d1, d2])
    h = decision_headers(v, priority=lambda cid: 100)
    assert h["x-aegis-budget-remaining"] == "usd=2"  # primary wins
    assert "set-cookie" not in h
    assert h["retry-after"] == "9"


def test_wire_formats_and_envelope() -> None:
    a = wire_body("anthropic", "invalid_request", "bad", control_id="X")
    assert a["type"] == "error" and a["error"]["type"] == "invalid_request_error"
    assert a["aegis"]["control_id"] == "X" and "retry_after_s" in a["aegis"]
    o = wire_body("openai", "budget_exceeded", "stop")
    assert o["error"]["code"] == "budget_exceeded"
    assert wire_body("ollama", "policy_blocked", "x")["error"].startswith("[Aegis]")
    r = api_error(403, "forbidden", "nope", required_role="admin")
    body = json.loads(r.body)
    assert body["error"]["required_role"] == "admin" and r.status_code == 403
    assert wire_for_path("/v1/messages") == "anthropic"
    assert wire_for_path("/v1/chat/completions") == "openai"
    assert wire_for_path("/ollama/api/chat") == "ollama"
    assert wire_for_path("/api/policy") is None


@pytest.mark.parametrize(
    ("primary", "action", "status", "etype"),
    [
        (Decision(control_id="DLP-02", action="block", reason="AWS key"), "block", 403,
         "policy_blocked"),
        (Decision(control_id="ACT-01", action="require_approval"), "require_approval", 403,
         "approval_required"),
        (Decision(control_id="EXE-04", action="block", error_type="killed"), "block", 429,
         "killed"),
    ],
)
def test_verdict_error(primary: Decision, action: str, status: int, etype: str) -> None:
    v = Verdict(id="dec_1", request_id="r", interaction_id="i", action=action,  # type: ignore[arg-type]
                primary=primary, decisions=[primary])
    resp = verdict_error(v)
    assert resp.status_code == status
    assert json.loads(resp.body)["error"]["type"] == etype
