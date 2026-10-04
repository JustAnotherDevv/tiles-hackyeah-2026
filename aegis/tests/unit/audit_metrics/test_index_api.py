"""AUD-V04 shapes: /api/decisions, /api/decisions/{id}, /api/audit (paging, decision_id, seq_from),
/api/audit/verify; projection rows; outcome-phase update (A-08)."""

from __future__ import annotations

from am_fakes import AGENT, decision_event

from aegis.core.types import AuditEvent, DecisionDetail, DecisionSummary, Usage, new_id

SUMMARY_KEYS = set(DecisionSummary.model_fields)
DETAIL_KEYS = set(DecisionDetail.model_fields) | {"wire", "audit_seq", "audit_hash"}


async def test_decisions_list_detail_and_audit_link(am_rt, am_client):
    evs = [
        decision_event(),
        decision_event(action="block", control_id="INJ-02", reason="injection"),
        decision_event(action="redact", control_id="DLP-01", reason="pii"),
    ]
    for ev in evs:
        await am_rt.audit.record(ev)

    r = await am_client.get("/api/decisions")
    assert r.status_code == 200
    page = r.json()
    assert set(page) == {"items", "next_cursor"}
    assert len(page["items"]) == 3
    assert set(page["items"][0]) == SUMMARY_KEYS
    assert page["items"][0]["id"] == evs[-1].decision_id  # newest first

    blocked = (await am_client.get("/api/decisions", params={"action": "block"})).json()["items"]
    assert [d["id"] for d in blocked] == [evs[1].decision_id]
    by_ctl = (await am_client.get("/api/decisions", params={"control_id": "DLP-01"})).json()[
        "items"
    ]
    assert [d["id"] for d in by_ctl] == [evs[2].decision_id]

    r = await am_client.get(f"/api/decisions/{evs[1].decision_id}")
    assert r.status_code == 200
    det = r.json()
    assert set(det) == DETAIL_KEYS
    assert det["audit_seq"] == 2 and len(det["audit_hash"]) == 64
    assert det["decisions"][0]["control_id"] == "INJ-02"

    r = await am_client.get("/api/audit", params={"decision_id": evs[1].decision_id})
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["hash"] == det["audit_hash"] and items[0]["seq"] == 2
    assert items[0]["prev_hash"]
    AuditEvent.model_validate(items[0])

    r = await am_client.get("/api/decisions/dec_nope")
    assert r.status_code == 404 and r.json()["error"]["type"] == "not_found"


async def test_audit_paging_no_dups_or_gaps(am_rt, am_client):
    for i in range(25):
        await am_rt.audit.record(
            AuditEvent(
                event_id=new_id("evt"), event_type="system", reason=f"e{i}", data={"kind": "t"}
            )
        )
    await am_rt.audit.record(
        AuditEvent(
            event_id=new_id("evt"), event_type="approval.created", data={"approval_kind": "action"}
        )
    )
    seen: list[int] = []
    cursor = None
    while True:
        params = {"limit": 7, **({"cursor": cursor} if cursor else {})}
        page = (await am_client.get("/api/audit", params=params)).json()
        seen += [it["seq"] for it in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == list(range(26, 0, -1))
    appr = (await am_client.get("/api/audit", params={"event_type": "approval.*"})).json()["items"]
    assert [a["seq"] for a in appr] == [26]
    jump = (await am_client.get("/api/audit", params={"seq_from": 10, "limit": 3})).json()["items"]
    assert [a["seq"] for a in jump] == [10, 9, 8]


async def test_decision_paging_cursor(am_rt, am_client):
    for _ in range(12):
        await am_rt.audit.record(decision_event())
    ids: list[str] = []
    cursor = None
    while True:
        params = {"limit": 5, **({"cursor": cursor} if cursor else {})}
        page = (await am_client.get("/api/decisions", params=params)).json()
        ids += [d["id"] for d in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(ids) == 12 and len(set(ids)) == 12


async def test_outcome_updates_decision_row(am_rt, am_client):
    ev = decision_event()
    await am_rt.audit.record(ev)
    out = AuditEvent(
        event_id=new_id("evt"),
        event_type="decision",
        decision_id=ev.decision_id,
        request_id=ev.request_id,
        actor=AGENT,
        model="claude-sonnet-4-5",
        usage=Usage(input_tokens=1200, output_tokens=300, cost_usd=0.0081),
        data={
            "phase": "outcome",
            "status_code": 200,
            "upstream_ms": 812.5,
            "provider": "anthropic",
            "model_used": "claude-sonnet-4-5",
        },
    )
    await am_rt.audit.record(out)
    items = (await am_client.get("/api/decisions")).json()["items"]
    assert len(items) == 1  # outcome never creates a decision row
    assert (
        items[0]["cost_usd"] == 0.0081
        and items[0]["tokens"] == 1500
        and items[0]["upstream_ms"] == 812.5
    )
    body = am_rt.metrics.render()[0].decode()
    assert (
        'aegis_cost_usd_total{agent="research-bot",provider="anthropic",team="t_research"} 0.0081'
        in body
    )


async def test_verify_endpoint(am_rt, am_client):
    await am_rt.audit.record(decision_event())
    r = await am_client.get("/api/audit/verify")
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True and body["records"] == 1
    assert body["message"].startswith("chain OK (1 records")
