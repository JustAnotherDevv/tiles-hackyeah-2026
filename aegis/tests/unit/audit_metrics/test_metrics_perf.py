"""AUD-V05 (/metrics), AUD-V07 (/api/perf), AUD-V13 (derived counters), AUD-12 (cost avoided),
AUD-V12 (record() micro-bench, marked `bench`)."""

from __future__ import annotations

import json
import re
import time

import pytest
from am_fakes import ctx, decision_event, interaction, verdict_for

from aegis.core.types import AuditEvent, Finding, Redaction, Usage, new_id
from aegis.metrics.cost import estimate, fallback_price


async def test_metrics_exposition(am_rt, am_client):
    m = am_rt.metrics
    m.observe_verdict(ctx({"ctl.DLP-01": 0.4, "ctl.INJ-02": 3.1}), interaction(), verdict_for())
    m.observe_verdict(
        ctx(),
        interaction(),
        verdict_for(
            "block",
            "INJ-02",
            findings=[
                Finding(
                    control_id="INJ-02",
                    detector="sig.x",
                    category="signature",
                    meta={"signature_id": "sig-ignore-prev"},
                )
            ],
        ),
    )
    m.observe_verdict(
        ctx(session_id="ses_zzz"),
        interaction(),
        verdict_for(
            "redact",
            "DLP-01",
            redactions=[
                Redaction(
                    segment_index=0,
                    path="text",
                    start=0,
                    end=11,
                    entity="PESEL",
                    placeholder="[PESEL_1]",
                    control_id="DLP-01",
                )
            ],
        ),
    )
    m.observe_overhead("request", 0.0004)
    m.inc("aegis_metadata_stripped_total", {"kind": "x-stainless"})
    m.inc("custom_thing", {"a": "b"})
    m.inc("approvals_total", {"kind": "action", "outcome": "approved"})  # derived -> ignored
    r = await am_client.get("/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    body = r.text
    for name in (
        "aegis_requests_total",
        "aegis_decisions_total",
        "aegis_gateway_overhead_seconds_bucket",
        "aegis_policy_version",
        "aegis_control_duration_seconds_bucket",
        "aegis_redactions_total",
        "aegis_signature_hits_total",
        "aegis_metadata_stripped_total",
        "aegis_custom_thing_total",
        "aegis_feed_serial",
        "aegis_killswitch_active",
    ):
        assert re.search(rf"^{name}", body, re.M), name
    assert 'le="0.0002"' in body
    assert "aegis_policy_version 7.0" in body
    assert not re.search(r'="(ses|req|dec)_', body)  # label guard
    assert 'aegis_approvals_total{kind="action",outcome="approved"}' not in body


def test_label_guard_cap():
    from aegis.metrics.prom import MAX_LABEL_SETS, guard_label

    assert guard_label("ses_123") == "other" and guard_label("x" * 81) == "other"
    assert guard_label("DLP-01") == "DLP-01"
    assert MAX_LABEL_SETS == 500


async def test_derived_counters_from_audit_events(am_rt):
    a = am_rt.audit
    await a.record(
        AuditEvent(
            event_id=new_id("evt"), event_type="approval.created", data={"approval_kind": "action"}
        )
    )
    await a.record(
        AuditEvent(
            event_id=new_id("evt"),
            event_type="approval.decided",
            data={"approval_kind": "action", "status": "approved"},
        )
    )
    await a.record(
        AuditEvent(event_id=new_id("evt"), event_type="policy.applied", data={"version": 8})
    )
    await a.record(
        AuditEvent(event_id=new_id("evt"), event_type="feed.rejected", data={"why": "sig"})
    )
    body = am_rt.metrics.render()[0].decode()
    assert 'aegis_approvals_total{kind="action",outcome="requested"} 1.0' in body
    assert 'aegis_approvals_total{kind="action",outcome="approved"} 1.0' in body
    assert 'aegis_policy_reloads_total{result="ok"} 1.0' in body
    assert 'aegis_feed_reloads_total{result="rejected"} 1.0' in body
    assert 'aegis_audit_records_total{event_type="approval.created"} 1.0' in body


async def test_perf_endpoint(am_rt, am_client):
    m = am_rt.metrics
    for i in range(20):
        m.observe_verdict(
            ctx({"ctl.DLP-01": 0.2 + i * 0.01, "ctl.INJ-02": 4.0 + i}),
            interaction(),
            verdict_for(latency_ms=1.0 + i * 0.1),
        )
    m.observe_upstream(
        "anthropic", "claude-sonnet-4-5", 0.8, Usage(input_tokens=100, output_tokens=50)
    )
    r = await am_client.get("/api/perf")
    p = r.json()
    assert set(p) == {
        "generated_at",
        "overhead_ms",
        "by_control",
        "upstream_ms",
        "rps_1m",
        "semantic",
        "bench",
    }
    assert (
        p["overhead_ms"]["count"] == 20 and p["overhead_ms"]["p95"] >= p["overhead_ms"]["p50"] > 0
    )
    p95s = [c["p95_ms"] for c in p["by_control"]]
    assert p95s == sorted(p95s, reverse=True) and p["by_control"][0]["control_id"] == "INJ-02"
    assert p["by_control"][0]["kind"] == "semantic"
    assert p["upstream_ms"][0]["provider"] == "anthropic"
    assert "mode" in p["semantic"] and p["bench"] is None
    assert p["rps_1m"] > 0


async def test_perf_bench_from_reports_dir(am_rt, am_client):
    rd = am_rt.settings.reports_dir
    rd.mkdir(parents=True)
    (rd / "bench.json").write_text(
        json.dumps({"schema": "aegis.bench/1", "headline": {"rps_det": 900}})
    )
    p = (await am_client.get("/api/perf")).json()
    assert p["bench"]["headline"]["rps_det"] == 900


def test_cost_avoided_estimates():
    price = fallback_price
    usd, reason = estimate(
        action="block",
        kind="model_call",
        direction="out",
        model="claude-sonnet-4-5",
        control_id="INJ-02",
        action_type=None,
        amount_usd=None,
        est_input_tokens=2000,
        max_output_tokens=1024,
        route_to=None,
        price=price,
    )
    assert reason == "policy_block" and usd == pytest.approx(3 * 2000 / 1e6 + 15 * 1024 / 1e6)
    usd, reason = estimate(
        action="block",
        kind="action",
        direction="out",
        model=None,
        control_id="ACT-02",
        action_type="spend.subscription",
        amount_usd=5000.01,
        est_input_tokens=None,
        max_output_tokens=None,
        route_to=None,
        price=price,
    )
    assert (usd, reason) == (5000.01, "spend_blocked")
    usd, reason = estimate(
        action="allow",
        kind="model_call",
        direction="out",
        model="claude-opus-4-1",
        control_id=None,
        action_type=None,
        amount_usd=None,
        est_input_tokens=1000,
        max_output_tokens=1000,
        route_to="claude-haiku-4-5",
        price=price,
    )
    assert reason == "downgrade" and usd > 0


async def test_cost_avoided_annotates_decision_and_kpi(am_rt, am_client):
    ev = decision_event(action="block", control_id="INJ-02", reason="injection")
    await am_rt.audit.record(ev)
    v = verdict_for("block", "INJ-02")
    v = v.model_copy(update={"id": ev.decision_id})
    am_rt.metrics.observe_verdict(
        ctx(), interaction(est_input_tokens=2000, max_output_tokens=1024), v
    )
    for t in list(am_rt.audit._tasks):
        await t
    st = (await am_client.get("/api/stats", params={"window": "1h"})).json()
    assert st["kpis"]["cost_avoided_usd"] == pytest.approx(0.0214, abs=1e-4)
    assert (
        'aegis_cost_avoided_usd_total{reason="policy_block"}' in am_rt.metrics.render()[0].decode()
    )


@pytest.mark.bench
@pytest.mark.skipif("not config.getoption('-m') or 'bench' not in config.getoption('-m')")
async def test_record_hot_path_p95(am_rt):
    am_rt.audit.test_mode = False  # production path: batched SQLite projection
    lat = []
    for _ in range(1000):
        ev = decision_event(action="redact", control_id="DLP-01", reason="pii")
        t0 = time.perf_counter()
        await am_rt.audit.record(ev)
        lat.append((time.perf_counter() - t0) * 1000)
    await am_rt.audit._drain()
    lat.sort()
    p95 = lat[int(0.95 * len(lat))]
    print(f"record() p50={lat[500]:.3f}ms p95={p95:.3f}ms")
    assert p95 < 1.5
