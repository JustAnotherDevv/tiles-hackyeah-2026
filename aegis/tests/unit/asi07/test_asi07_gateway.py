"""ASI07 end to end on the REAL gateway: POST /a2a/{peer} -> mocks/mock_peer (in-process).

Positive: registered peer, mutual signatures, verified reply delivered.
Negative: unknown / typosquatted peer, caller not allowed, forged agent card, tampered,
unsigned, stale, spoofed-sender and replayed replies (A2A-01); injected peer reply, exfil
beacon, hop limit and delegation loop (A2A-02); forged inbound peer message (A2A-01, 401).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

from aegis.a2a import peers, signing

SEED = Path(__file__).resolve().parents[3] / "config" / "org.seed.yaml"


@cache
def _seed_keys() -> dict[str, str]:
    doc = yaml.safe_load(SEED.read_text())
    out: dict[str, str] = {}
    for k in doc.get("api_keys") or []:
        if not k.get("revoked_at") and k.get("principal") not in out:
            out[k["principal"]] = k["key"]
    return out


def _auth(agent: str) -> dict[str, str]:
    """Seed (fake, demo) agent key -> proven identity for GOV-01."""
    return {"X-Aegis-Agent": agent, "Authorization": f"Bearer {_seed_keys()[agent]}"}


def _msg(text: str = "Summarise public sources on EU AI Act timelines") -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 7, "method": "message/send",
            "params": {"message": {"role": "user", "messageId": "m1",
                                   "parts": [{"kind": "text", "text": text}]}}}


async def _mode(peer, mode: str, name: str | None = None) -> None:
    body = {"mode": mode}
    if name:
        body["name"] = name
    r = await peer.post("/_mock/mode", json=body)
    assert r.json()["ok"], r.text


async def _send(gw, peer_id: str = "research-agent", headers: dict[str, str] | None = None,
                body: Any = None):
    return await gw.post(f"/a2a/{peer_id}", json=body or _msg(),
                         headers={**_auth("trading-copilot@trading"), **(headers or {})})


def _text(r) -> str:
    return " ".join(p["text"] for p in r.json()["result"]["parts"])


def _blocked(r, control: str, needle: str = "") -> dict[str, Any]:
    assert r.status_code in (401, 403), r.text
    err = r.json()["error"]
    assert err["code"] == -32001, err
    aegis = err["data"]["aegis"]
    assert aegis["control"] == control, aegis
    assert needle.lower() in aegis["reason"].lower(), aegis["reason"]
    assert aegis["decision_id"].startswith("dec_")
    return aegis


async def _peer_log(peer) -> dict[str, Any]:
    return (await peer.get("/_mock/log")).json()


# ------------------------------------------------------------------ positive
async def test_registered_peer_roundtrip_mutually_verified(a2a) -> None:
    gw, peer, _rt = a2a
    r = await _send(gw)
    assert r.status_code == 200, r.text
    assert "no blockers found" in _text(r)
    assert r.headers["x-aegis-decision"] in ("allow", "log")
    assert r.headers.get("x-aegis-response-decision-id", "").startswith("dec_")
    assert not any(k.lower().startswith("x-a2a-") for k in r.headers)  # peer envelope stripped
    log = await _peer_log(peer)
    assert log["count"] == 1
    item = log["items"][0]
    assert item["verified"] is True  # the peer verified the gateway's signature
    assert item["hop"] == "1" and item["chain"] == "trading-copilot@trading"


async def test_peers_listing_has_no_key_material(a2a) -> None:
    gw, _peer, _rt = a2a
    r = await gw.get("/a2a/peers")
    assert r.status_code == 200
    data = r.json()
    ids = {p["id"] for p in data["peers"]}
    assert {"research-agent", "billing-agent"} <= ids
    assert peers.peer_key("research-agent") not in r.text


async def test_allowed_caller_reaches_restricted_peer(a2a) -> None:
    gw, _peer, _rt = a2a
    r = await _send(gw, "billing-agent")
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ A2A-01 negatives
async def test_unknown_peer_denied_without_contact(a2a) -> None:
    gw, peer, _rt = a2a
    r = await _send(gw, "shadow-agent")
    _blocked(r, "A2A-01", "unknown peer")
    assert (await _peer_log(peer))["count"] == 0


async def test_typosquatted_peer_denied_with_hint(a2a) -> None:
    gw, _peer, _rt = a2a
    _blocked(await _send(gw, "research-agnet"), "A2A-01", "typosquat")


async def test_caller_not_in_peer_allowlist(a2a) -> None:
    gw, peer, _rt = a2a
    r = await _send(gw, "billing-agent", headers=_auth("research-agent@research"))
    _blocked(r, "A2A-01", "not allowed")
    assert (await _peer_log(peer))["count"] == 0


async def test_forged_agent_card_denied(a2a) -> None:
    gw, peer, _rt = a2a
    await _mode(peer, "forged_card")
    _blocked(await _send(gw), "A2A-01", "agent card")


async def test_tampered_reply_blocked(a2a) -> None:
    gw, peer, _rt = a2a
    await _mode(peer, "tamper")
    r = await _send(gw)
    _blocked(r, "A2A-01", "signature mismatch")
    assert "wire 5000" not in r.text  # tampered content never reaches the agent


async def test_unsigned_reply_blocked(a2a) -> None:
    gw, peer, _rt = a2a
    await _mode(peer, "unsigned")
    _blocked(await _send(gw), "A2A-01", "unsigned")


async def test_stale_reply_blocked(a2a) -> None:
    gw, peer, _rt = a2a
    await _mode(peer, "stale")
    _blocked(await _send(gw), "A2A-01", "stale")


async def test_spoofed_sender_reply_blocked(a2a) -> None:
    gw, peer, _rt = a2a
    await _mode(peer, "wrong_sender")
    _blocked(await _send(gw), "A2A-01", "spoofed")


async def test_replayed_reply_nonce_blocked(a2a) -> None:
    gw, peer, _rt = a2a
    ok = await _send(gw)
    assert ok.status_code == 200, ok.text
    await _mode(peer, "replay")
    _blocked(await _send(gw), "A2A-01", "replayed nonce")


async def test_inbound_peer_message_with_forged_signature_401(a2a) -> None:
    gw, peer, _rt = a2a
    body = _msg("relayed task from research-agent")
    hdrs = signing.sign_headers("not-the-peer-key", sender="research-agent",
                                recipient="aegis-gateway", body=b"{}")
    r = await _send(gw, "billing-agent", headers=hdrs, body=body)
    assert r.status_code == 401, r.text
    _blocked(r, "A2A-01", "signature mismatch")
    assert (await _peer_log(peer))["count"] == 0


async def test_inbound_peer_message_validly_signed_is_relayed(a2a) -> None:
    import json

    gw, _peer, _rt = a2a
    body = _msg("relayed task from research-agent")
    raw = json.dumps(body).encode()
    hdrs = signing.sign_headers(peers.peer_key("research-agent"), sender="research-agent",
                                recipient="aegis-gateway", body=raw)
    r = await gw.post("/a2a/billing-agent", content=raw,
                      headers={"content-type": "application/json",
                               **_auth("trading-copilot@trading"), **hdrs})
    assert r.status_code == 200, r.text
    # the same signed message again = replay
    r2 = await gw.post("/a2a/billing-agent", content=raw,
                       headers={"content-type": "application/json",
                                **_auth("trading-copilot@trading"), **hdrs})
    _blocked(r2, "A2A-01", "replayed nonce")


# ------------------------------------------------------------------ A2A-02 negatives
async def test_injected_peer_reply_blocked(a2a) -> None:
    gw, peer, _rt = a2a
    await _mode(peer, "inject")
    r = await _send(gw)
    _blocked(r, "A2A-02", "peer reply")
    assert "customer database" not in r.text


async def test_exfil_beacon_in_peer_reply_stripped(a2a) -> None:
    gw, peer, _rt = a2a
    await _mode(peer, "exfil")
    r = await _send(gw)
    assert r.status_code == 200, r.text
    text = _text(r)
    assert "exfil.test" not in text
    assert "AEGIS-QUARANTINE" in text and "no blockers found" in text
    assert r.headers["x-aegis-redactions"] != "0"


async def test_hop_limit_blocks_deep_delegation(a2a) -> None:
    gw, peer, _rt = a2a
    r = await _send(gw, headers={"X-Aegis-Hop": "3",
                                 "X-Aegis-Chain": "planner@ops,router@ops,worker@ops"})
    _blocked(r, "A2A-02", "delegation depth")
    assert (await _peer_log(peer))["count"] == 0
    ok = await _send(gw, headers={"X-Aegis-Hop": "1", "X-Aegis-Chain": "planner@ops"})
    assert ok.status_code == 200, ok.text


async def test_delegation_loop_blocked(a2a) -> None:
    gw, peer, _rt = a2a
    r = await _send(gw, headers={"X-Aegis-Hop": "1", "X-Aegis-Chain": "research-agent"})
    _blocked(r, "A2A-02", "loop")
    assert (await _peer_log(peer))["count"] == 0
