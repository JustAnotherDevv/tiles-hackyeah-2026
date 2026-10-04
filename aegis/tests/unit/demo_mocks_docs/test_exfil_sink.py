"""DEMO-V03 (sink): any path counts, /_mock/* never counts, CORS on hits, PNG for images."""

from __future__ import annotations


async def test_hits_counted_and_mock_paths_not(sink):
    assert (await sink.get("/_mock/hits")).json()["count"] == 0
    await sink.get("/collect?d=4111111111111111")
    await sink.post("/upload", content=b"secret 12345")
    await sink.get("/_mock/health")
    await sink.get("/_mock/unknown")
    d = (await sink.get("/_mock/hits")).json()
    assert d["count"] == 2
    newest = d["items"][0]
    assert newest["method"] == "POST" and newest["path"] == "/upload" and newest["body_len"] == 12
    assert "1" not in d["items"][1]["preview"]  # digits masked


async def test_cors_and_png(sink):
    r = await sink.get("/_mock/hits")
    assert r.headers["access-control-allow-origin"] == "*"
    r = await sink.get("/p.png?d=abc")
    assert r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"


async def test_clear_ui_health(sink):
    await sink.get("/x")
    assert (await sink.delete("/_mock/hits")).json()["cleared"] == 1
    assert (await sink.get("/_mock/hits")).json()["count"] == 0
    ui = await sink.get("/_mock/ui")
    assert ui.status_code == 200 and "Attacker received" in ui.text
    assert (await sink.get("/_mock/health")).json()["service"] == "exfil_sink"
