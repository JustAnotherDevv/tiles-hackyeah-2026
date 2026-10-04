"""AUD-V06 (/api/stats shape + buckets), AUD-V10 (warm-up), AUD-14 (posture), AUD-08 tick,
A-53 (/api/selftest*)."""

from __future__ import annotations

import json
from datetime import timedelta

from am_fakes import decision_event, fake_policy

from aegis.audit.chain import audit_files
from aegis.metrics import stats as st
from aegis.metrics import warmup as wu
from aegis.metrics.timing import utc_now

KPI_KEYS = {
    "requests",
    "allowed",
    "logged",
    "redacted",
    "blocked",
    "approvals_pending",
    "approvals_decided",
    "spend_usd",
    "spend_today_usd",
    "org_budget_used_pct",
    "tokens",
    "local_compute_s",
    "cost_avoided_usd",
    "active_agents",
    "p50_overhead_ms",
    "p95_overhead_ms",
    "degraded",
}
TOP_KEYS = {
    "window",
    "generated_at",
    "kpis",
    "timeseries",
    "by_control",
    "by_category",
    "by_destination",
    "by_entity",
    "top_agents",
}
BUCKET_KEYS = {"ts", "allow", "log", "redact", "require_approval", "block", "spend_usd", "tokens"}


async def test_stats_shape_windows_and_bad_window(am_rt, am_client):
    n = await wu.backfill(am_rt, days=7, per_day=900)
    assert n > 4000
    await am_rt.audit.record(decision_event(action="block", control_id="INJ-02", reason="x"))
    for window, buckets in (("1h", 60), ("24h", 96), ("7d", 56)):
        s = (await am_client.get("/api/stats", params={"window": window})).json()
        assert set(s) == TOP_KEYS and set(s["kpis"]) == KPI_KEYS
        assert len(s["timeseries"]) == buckets and set(s["timeseries"][0]) == BUCKET_KEYS
        assert [d["dest_class"] for d in s["by_destination"]] == ["local", "remote", "third_party"]
        assert set(s["by_control"][0]) == {"control_id", "family", "hits", "blocks", "redacts"}
    s24 = (await am_client.get("/api/stats", params={"window": "24h"})).json()
    nonempty = sum(
        1
        for b in s24["timeseries"]
        if sum(b[a] for a in ("allow", "log", "redact", "require_approval", "block"))
    )
    assert nonempty / 96 >= 0.8
    assert s24["kpis"]["cost_avoided_usd"] > 0  # widget/HarmonyOS consumer relies on it
    assert s24["kpis"]["requests"] > 100
    live = (await am_client.get("/api/stats", params={"window": "24h", "synthetic": "0"})).json()
    assert live["kpis"]["requests"] == 1 and live["kpis"]["blocked"] == 1
    r = await am_client.get("/api/stats", params={"window": "2d"})
    assert r.status_code == 400 and r.json()["error"]["type"] == "invalid_request"


async def test_synthetic_rows_never_in_chain_and_filterable(am_rt, am_client):
    await wu.backfill(am_rt, days=1, per_day=200)
    await am_rt.audit.record(decision_event())
    blob = b"".join(f.read_bytes() for f in audit_files(am_rt.audit.audit_dir))
    assert b"req_demo" not in blob and b"ses_demo_" not in blob
    all_items = (await am_client.get("/api/decisions", params={"limit": 1000})).json()["items"]
    assert any(i["request_id"].startswith("req_demo") for i in all_items)
    assert all(
        i["preview"].startswith("[demo]")
        for i in all_items
        if i["request_id"].startswith("req_demo")
    )
    live = (await am_client.get("/api/decisions", params={"synthetic": "0"})).json()["items"]
    assert len(live) == 1 and not live[0]["request_id"].startswith("req_demo")


async def test_warmup_endpoints_rbac(am_rt, am_client):
    s = (await am_client.get("/api/stats/warmup")).json()
    assert s["synthetic_rows"] == 0 and s["primer"]["state"] in {"idle", "skipped", "done"}
    r = await am_client.post(
        "/api/stats/warmup",
        json={"days": 1, "per_day": 100},
        headers={"X-Aegis-View-As": "u_piotr"},
    )
    assert r.status_code == 403 and r.json()["error"]["type"] == "forbidden"
    r = await am_client.post(
        "/api/stats/warmup",
        json={"days": 1, "per_day": 100},
        headers={"X-Aegis-View-As": "u_tomasz"},
    )
    assert r.status_code == 200 and r.json()["synthetic_rows"] > 0
    assert r.json()["oldest_ts"] < r.json()["newest_ts"]
    r = await am_client.delete("/api/stats/warmup", headers={"X-Aegis-View-As": "u_katarzyna"})
    assert r.status_code == 200 and r.json()["synthetic_rows"] == 0 and r.json()["removed"] > 0


async def test_auto_warmup_full_then_topup(am_rt):
    n = await wu.auto_warmup(am_rt, "auto")
    assert n > 0
    assert await wu.auto_warmup(am_rt, "auto") == 0  # newest row is fresh -> nothing to top up
    assert await wu.auto_warmup(am_rt, "off") == 0


def test_generate_rows_deterministic():
    now = utc_now()
    a = wu.generate_rows(now - timedelta(hours=6), now, 900, wu.FALLBACK_CAST, wu.price_fn(None))
    b = wu.generate_rows(now - timedelta(hours=6), now, 900, wu.FALLBACK_CAST, wu.price_fn(None))
    assert [r["id"][:16] for r in a] == [r["id"][:16] for r in b] and len(a) > 50
    assert all(r["synthetic"] == 1 and r["request_id"].startswith("req_demo") for r in a)


async def test_posture_score_and_disabled_control(am_rt, am_client):
    await am_rt.audit.verify()
    p = (await am_client.get("/api/stats/posture")).json()
    assert set(p) == {
        "generated_at",
        "score",
        "grade",
        "policy_version",
        "feed_serial",
        "components",
        "findings",
    }
    assert 0 <= p["score"] <= 100 and p["grade"] in {"A", "A-", "B+", "B", "C", "D"}
    ids = {c["id"] for c in p["components"]}
    assert {"controls", "feed", "audit", "models", "governance"} <= ids
    am_rt.policy = fake_policy(
        {
            "DLP-01": (True, "enforce"),
            "DLP-02": (False, "enforce"),
            "INJ-02": (True, "enforce"),
            "EXE-01": (True, "enforce"),
        }
    )
    p2 = (await am_client.get("/api/stats/posture")).json()
    assert p2["score"] < p["score"]
    assert any(f["control_id"] == "DLP-02" and f["severity"] == "high" for f in p2["findings"])


async def test_stats_tick_shape(am_rt):
    am_rt.metrics.perf.add_decision("block")
    tick = st.build_stats_tick(am_rt, st.TickState())
    assert set(tick) == {
        "ts",
        "rps",
        "decisions_1m",
        "spend_today_usd",
        "approvals_pending",
        "p50_overhead_ms",
        "p95_overhead_ms",
    }
    assert set(tick["decisions_1m"]) == {"allow", "log", "redact", "require_approval", "block"}
    assert tick["decisions_1m"]["block"] == 1


async def test_control_rollup(am_rt):
    await am_rt.audit.record(decision_event(action="block", control_id="INJ-02", reason="x"))
    roll = await st.control_rollup(am_rt)
    assert roll["INJ-02"]["hits"] == 1 and roll["INJ-02"]["blocks"] == 1


async def test_selftest_endpoints(am_rt, am_client):
    r = await am_client.get("/api/selftest")
    assert r.status_code == 404 and r.json()["error"]["type"] == "not_found"
    rd = am_rt.settings.reports_dir
    rd.mkdir(parents=True)
    (rd / "results.json").write_text(
        json.dumps({"schema": "aegis.selftest/1", "summary": {"passed": 3, "total": 4}})
    )
    (rd / "selftest.html").write_text("<html>ok</html>")
    body = (await am_client.get("/api/selftest")).json()
    assert body["schema"] == "aegis.selftest/1" and body["running"] is False
    r = await am_client.get("/api/selftest/report")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    r = await am_client.post("/api/selftest/run", headers={"X-Aegis-View-As": "u_piotr"})
    assert r.status_code == 403


async def test_sse_stats_ticker_publishes(am_rt, monkeypatch):
    import asyncio

    from aegis.api.routes import stats as stats_route

    monkeypatch.setattr(stats_route, "TICK_S", 0.02)
    task = asyncio.get_running_loop().create_task(stats_route._ticker(am_rt))
    await asyncio.sleep(0.2)
    task.cancel()
    ticks = [d for e, d in am_rt.bus.published if e == "stats"]
    assert len(ticks) >= 2
    assert set(ticks[0]["decisions_1m"]) == {"allow", "log", "redact", "require_approval", "block"}
