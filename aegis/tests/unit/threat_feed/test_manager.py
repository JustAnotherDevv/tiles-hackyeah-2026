"""TI-V06: gateway FeedManager pipeline against the in-process feed service."""

from __future__ import annotations

import json
from datetime import timedelta

import httpx

from aegis.core.types import utcnow
from aegis.feed.manager import FeedManager


async def test_seed_then_noop_then_publish(manager, rt, feed_client) -> None:
    st = manager.status()
    assert st.status == "seed" and st.serial == 1 and st.signatures_total == 20
    st = await manager.refresh("poll")
    assert st.status == "ok" and st.serial == 1  # sha equal -> no-op
    await feed_client.post("/api/signatures/AEGIS-TI-022/enabled", json={"enabled": True})
    await feed_client.post("/api/publish", json={})
    st = await manager.refresh("sse")
    assert st.status == "ok" and st.serial == 2
    upd = rt.bus.of("feed.updated")
    assert upd and upd[-1]["added"] == 1 and upd[-1]["added_ids"] == ["AEGIS-TI-022"]
    assert rt.audit.of("feed.updated")[-1].feed_serial == 2
    assert rt.metrics.gauges["aegis_feed_serial"] == 2
    assert st.history[-1]["serial"] == 2 and "verify_ms" in st.history[-1]


async def test_unsigned_tamper_rejected_once_and_keeps_serial(manager, rt, feed_client) -> None:
    await feed_client.post("/api/publish", json={})
    await manager.refresh("sse")
    assert manager.serial == 2
    await feed_client.post("/api/tamper", json={"mode": "unsigned"})
    for _ in range(3):
        st = await manager.refresh("poll")
    assert st.status == "rejected" and st.serial == 2
    assert st.last_error.startswith("bad_signature")
    rej = rt.bus.of("feed.rejected")
    assert len(rej) == 1 and rej[0]["kept_serial"] == 2 and rej[0]["serial_attempted"] == 3
    # recovery: a legitimate publish is applied
    await feed_client.post("/api/publish", json={})
    st = await manager.refresh("sse")
    assert st.status == "ok" and st.serial == 4


async def test_rollback_wrong_key_and_swap(manager, rt, feed_client) -> None:
    await feed_client.post("/api/publish", json={})
    await manager.refresh()
    await feed_client.post("/api/tamper", json={"mode": "rollback"})
    st = await manager.refresh("poll")
    assert st.status == "rejected" and st.last_error.startswith("rollback")
    await feed_client.post("/api/tamper", json={"mode": "wrong_key"})
    st = await manager.refresh("poll")
    assert st.last_error.startswith("wrong_key") and st.serial == 2
    await feed_client.post("/api/tamper", json={"mode": "swap_bundle"})
    st = await manager.refresh("poll")
    assert st.last_error.startswith("sha256_mismatch") and st.serial == 2


async def test_force_published_failing_vector_is_quarantined(
    manager, feed_dirs, feed_client
) -> None:
    ws = feed_dirs.svc.workspace
    text = ws.get_text("AEGIS-TI-000").replace(
        "AEGIS-TEST-SIGNATURE-7F3A", "AEGIS-TEST-SIGNATURE-XXXX", 1
    )
    await feed_client.put(
        "/api/signatures/AEGIS-TI-000", content=text, headers={"content-type": "text/plain"}
    )
    r = await feed_client.post("/api/publish", json={"force": True})
    assert r.status_code == 200
    st = await manager.refresh()
    assert st.serial == 2 and st.signatures_quarantined >= 1
    assert "AEGIS-TI-000" in manager.active.quarantined
    assert all(c.id != "AEGIS-TI-000" for cs in manager.active.by_surface.values() for c in cs)


async def test_uncompilable_bundle_rejected(manager, feed_dirs) -> None:
    # sign a bundle with a non-RE2 regex using the real key (feed-side validation bypassed)
    from feed_service.build import build_bundle_bytes

    svc = feed_dirs.svc
    seed = svc.seed()
    doc = json.loads(svc.dist_file("bundle-000001.json"))
    doc["signatures"][0]["match"] = {"type": "regex", "pattern": "(a)\\1"}
    data, header = build_bundle_bytes(
        doc["signatures"], doc["lists"], serial=5, ttl_h=1, kid=svc.key_id()
    )
    svc._write_release(data, header, seed)
    st = await manager.refresh("poll")
    assert st.status == "rejected" and st.last_error.startswith("schema") and st.serial == 1


async def test_expired_is_stale_but_enforcing(manager) -> None:
    a = manager.active
    object.__setattr__(a, "expires", utcnow() - timedelta(hours=1))
    st = manager.status()
    assert st.status == "stale" and st.serial == 1 and st.signatures_active > 0


async def test_restart_from_cache(manager, rt, feed_app, feed_client) -> None:
    await feed_client.post("/api/publish", json={})
    await manager.refresh()
    assert manager.serial == 2
    m2 = FeedManager(rt, transport=httpx.ASGITransport(app=feed_app))
    await m2.start()
    assert m2.serial == 2 and m2.status().status == "ok"
    await m2.stop()


async def test_operator_rollback_pins(manager, rt, feed_client) -> None:
    await feed_client.post("/api/publish", json={})
    await manager.refresh()
    st = await manager.rollback(1, reason="test")
    assert st.serial == 1 and manager.pinned
    await feed_client.post("/api/publish", json={})
    st = await manager.refresh("poll")
    assert st.serial == 1 and manager.pending_serial == 3
    st = await manager.refresh()  # api refresh clears the pin
    assert st.serial == 3


async def test_signatures_view_shape(manager) -> None:
    items = manager.signatures()
    assert len(items) == 20
    keys = {
        "id",
        "title",
        "severity",
        "status",
        "aliases",
        "tags",
        "surfaces",
        "action",
        "hits_24h",
    }
    assert keys <= set(items[0])
    assert manager.lists().get("malicious_versions")
