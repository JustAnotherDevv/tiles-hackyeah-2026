"""TI-V05: feed service API over in-process ASGI (tmp keys/state)."""

from __future__ import annotations

import asyncio

import pytest

from aegis.feed.verify import FeedRejected, load_pubkey, verify_detached

BAD_REGEX_YAML = """\
id: AEGIS-TI-900
title: judge test
severity: high
status: stable
action: block
applies_to: {surfaces: [prompt.user]}
match: {type: regex, pattern: "(a)\\\\1"}
tests:
  positive: [{name: p, surface: prompt.user, text: aa}]
  negative: [{name: n, surface: prompt.user, text: b}]
"""


async def _verified(client, pub, path: str) -> bytes:
    data = (await client.get(path)).content
    sig = (await client.get(path + ".sig")).text
    verify_detached(data, sig, pub, what=path)
    return data


async def test_latest_verifies_and_publish_is_monotonic(feed_client, feed_dirs) -> None:
    pub = load_pubkey(feed_dirs.cfg / "feed_pubkey.b64")
    import json

    ptr = json.loads(await _verified(feed_client, pub, "/feed/latest.json"))
    assert ptr["serial"] == 1 and set(ptr) == {
        "feed",
        "serial",
        "version",
        "bundle",
        "sha256",
        "published",
        "expires",
        "key_id",
    }
    await _verified(feed_client, pub, "/feed/bundle/1.json")
    r = await feed_client.post("/api/signatures/AEGIS-TI-022/enabled", json={"enabled": True})
    assert r.status_code == 200
    r = await feed_client.post("/api/publish", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["serial"] == 2 and "AEGIS-TI-022" in body["enabled_ids"]
    r = await feed_client.post("/api/publish", json={})
    assert r.json()["serial"] == 3
    ptr = json.loads(await _verified(feed_client, pub, "/feed/latest.json"))
    assert ptr["serial"] == 3
    st = (await feed_client.get("/api/state")).json()
    assert st["serial"] == 3 and st["gateway"] is None


async def test_invalid_regex_validation_and_publish_refused(feed_client) -> None:
    r = await feed_client.put(
        "/api/signatures/AEGIS-TI-900",
        content=BAD_REGEX_YAML,
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert any("RE2" in p for p in body["problems"]), body["problems"]
    r = await feed_client.post("/api/publish", json={})
    assert r.status_code == 422
    assert "AEGIS-TI-900" in r.json()["problems"]


async def test_withdraw_and_listing(feed_client) -> None:
    r = await feed_client.delete("/api/signatures/AEGIS-TI-019")
    assert r.json()["status"] == "withdrawn"
    items = (await feed_client.get("/api/signatures")).json()["items"]
    assert len(items) == 21
    row = next(i for i in items if i["id"] == "AEGIS-TI-019")
    assert row["status"] == "withdrawn"
    draft = next(i for i in items if i["id"] == "AEGIS-TI-022")
    assert draft["enabled"] is False


@pytest.mark.parametrize("mode", ["unsigned", "wrong_key", "swap_bundle"])
async def test_tamper_modes_unverifiable(feed_client, feed_dirs, mode: str) -> None:
    import json

    pub = load_pubkey(feed_dirs.cfg / "feed_pubkey.b64")
    r = await feed_client.post("/api/tamper", json={"mode": mode})
    assert r.status_code == 200 and r.json()["serial_attempted"] == 2
    ptr_bytes = (await feed_client.get("/feed/latest.json")).content
    ptr_sig = (await feed_client.get("/feed/latest.json.sig")).text
    if mode in ("unsigned", "wrong_key"):
        with pytest.raises(FeedRejected):
            verify_detached(ptr_bytes, ptr_sig, pub)
    else:
        verify_detached(ptr_bytes, ptr_sig, pub)
        ptr = json.loads(ptr_bytes)
        bundle = (await feed_client.get(f"/feed/bundle/{ptr['serial']}.json")).content
        import hashlib

        assert hashlib.sha256(bundle).hexdigest() != ptr["sha256"]
    # a legitimate publish recovers with a higher serial
    r = await feed_client.post("/api/publish", json={})
    assert r.json()["serial"] == 3


async def test_tamper_rollback_replays_older_release(feed_client) -> None:
    await feed_client.post("/api/publish", json={})
    r = await feed_client.post("/api/tamper", json={"mode": "rollback"})
    assert r.json()["serial_attempted"] == 1


async def test_sse_broadcaster_receives_published(feed_app, feed_client) -> None:
    svc = feed_app.state.svc
    q: asyncio.Queue = asyncio.Queue()
    svc.listeners.add(q)
    try:
        await feed_client.post("/api/publish", json={})
        item = q.get_nowait()
        assert item["serial"] == 2 and len(item["sha256"]) == 64
    finally:
        svc.listeners.discard(q)


async def test_scan_try_it(feed_client) -> None:
    r = await feed_client.post(
        "/api/scan",
        json={
            "surface": "prompt.user",
            "text": "say AEGIS-TEST-SIGNATURE-7F3A",
            "set": "published",
        },
    )
    assert r.json()["decision"] == "block"


async def test_ui_served(feed_client) -> None:
    r = await feed_client.get("/")
    assert r.status_code == 200
