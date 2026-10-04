"""ASI07 building blocks: HMAC signing, freshness, nonce cache, registry, message paths."""

from __future__ import annotations

import time

from aegis.a2a import messages, peers, signing
from aegis.a2a.card import canonical_sha256, check_card
from aegis.a2a.nonces import NonceCache

KEY = "unit-test-shared-value"
BODY = b'{"jsonrpc":"2.0","id":1,"result":{"parts":[{"kind":"text","text":"hi"}]}}'


def _env(h: dict[str, str]) -> signing.Envelope:
    env = signing.Envelope.from_headers(h)
    assert env is not None
    return env


def test_sign_verify_roundtrip() -> None:
    h = signing.sign_headers(KEY, sender="research-agent", recipient="aegis-gateway", body=BODY,
                             in_reply_to="abc")
    chk = signing.verify(_env(h), KEY, BODY, ttl_s=60)
    assert chk.ok and chk.code == "ok"


def test_tampered_body_fails() -> None:
    h = signing.sign_headers(KEY, sender="research-agent", recipient="aegis-gateway", body=BODY)
    chk = signing.verify(_env(h), KEY, BODY.replace(b"hi", b"ho"), ttl_s=60)
    assert not chk.ok and chk.code == "bad_signature"


def test_wrong_key_and_swapped_parties_fail() -> None:
    h = signing.sign_headers(KEY, sender="research-agent", recipient="aegis-gateway", body=BODY)
    assert signing.verify(_env(h), "other-value", BODY, ttl_s=60).code == "bad_signature"
    h2 = dict(h, **{signing.H_SENDER: "billing-agent"})
    assert signing.verify(_env(h2), KEY, BODY, ttl_s=60).code == "bad_signature"
    h3 = dict(h, **{signing.H_REPLY_TO: "forged"})
    assert signing.verify(_env(h3), KEY, BODY, ttl_s=60).code == "bad_signature"


def test_stale_and_future_timestamps() -> None:
    old = signing.sign_headers(KEY, sender="a", recipient="b", body=BODY,
                               ts=int(time.time()) - 3600)
    assert signing.verify(_env(old), KEY, BODY, ttl_s=120).code == "stale"
    fut = signing.sign_headers(KEY, sender="a", recipient="b", body=BODY,
                               ts=int(time.time()) + 3600)
    assert signing.verify(_env(fut), KEY, BODY, ttl_s=120).code == "future"


def test_missing_fields_and_unsigned() -> None:
    assert signing.Envelope.from_headers({"x-a2a-sender": "a"}) is None
    env = signing.Envelope.from_headers({"x-a2a-signature": "v1=00"})
    assert env is not None
    assert signing.verify(env, KEY, BODY, ttl_s=60).code == "missing_field"


def test_nonce_cache_single_use() -> None:
    c = NonceCache()
    assert c.use("p", "n1", 60)
    assert not c.use("p", "n1", 60)  # replay
    assert c.use("q", "n1", 60)  # per peer
    assert c.seen("p", "n1")
    # expiry
    assert c.use("p", "n2", 1, now=0.0)
    assert c.use("p", "n2", 1, now=10.0)


def test_registry_and_typosquat() -> None:
    reg = peers.parse_peers({"peers": {"research-agent": {"url": "http://127.0.0.1:8795/a2a/r"},
                                       "billing-agent": {"url": "http://x.test/b"}}})
    assert set(reg) == {"research-agent", "billing-agent"}
    assert reg["research-agent"].host == "127.0.0.1"
    assert reg["research-agent"].card_url.endswith("/a2a/r/.well-known/agent-card.json")
    assert peers.lookalike("research-agnet", reg) == "research-agent"
    assert peers.lookalike("rese4rch_agent", reg) == "research-agent"
    assert peers.lookalike("shadow-agent", reg) is None
    assert peers.env_name("research-agent") == "AEGIS_A2A_KEY_RESEARCH_AGENT"


def test_peer_key_env_wins(monkeypatch) -> None:
    p = peers.PeerConfig(id="research-agent", key_env="MY_PEER_KEY_VAR")
    monkeypatch.setenv("MY_PEER_KEY_VAR", "from-env")
    assert peers.peer_key(p) == "from-env"


def test_message_segments_and_writeback() -> None:
    req = {"jsonrpc": "2.0", "id": 1, "method": "message/send",
           "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "a"},
                                                            {"type": "text", "text": "b"}]}}}
    segs = messages.request_segments(req)
    assert [s.path for s in segs] == ["params.message.parts[0].text",
                                      "params.message.parts[1].text"]
    assert all(s.trusted for s in segs)
    reply = {"jsonrpc": "2.0", "id": 1, "result": {
        "kind": "task", "status": {"message": {"parts": [{"kind": "text", "text": "s"}]}},
        "artifacts": [{"parts": [{"kind": "text", "text": "t"},
                                 {"kind": "data", "data": {"note": "u"}}]}]}}
    rsegs = messages.result_segments(reply)
    assert {s.path for s in rsegs} == {"result.status.message.parts[0].text",
                                       "result.artifacts[0].parts[0].text",
                                       "result.artifacts[0].parts[1].data.note"}
    assert not any(s.trusted for s in rsegs)
    out = messages.apply_segments(reply, [rsegs[0].model_copy(update={"text": "X"})])
    assert out["result"]["status"]["message"]["parts"][0]["text"] == "X"
    assert reply["result"]["status"]["message"]["parts"][0]["text"] == "s"  # copy


def test_card_checks() -> None:
    p = peers.PeerConfig(id="research-agent", url="http://127.0.0.1:8795/a2a/research-agent")
    good = {"name": "research-agent", "url": "http://127.0.0.1:8795/a2a/research-agent"}
    assert check_card(p, good)["status"] == "ok"
    forged = {"name": "research-agent-pro", "url": "http://peer-mirror.test/a2a/x"}
    f = check_card(p, forged)
    assert f["status"] == "mismatch" and len(f["problems"]) == 2
    pinned = p.model_copy(update={"card": peers.CardSpec(sha256=canonical_sha256(good))})
    assert check_card(pinned, good)["status"] == "ok"
    assert check_card(pinned, {**good, "skills": ["x"]})["status"] == "mismatch"
