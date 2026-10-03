"""AUD-V09: JSONL (re-verifiable lines), CSV (header + injection guard), OCSF (2004 / 6003), RBAC,
audited export + headers."""

from __future__ import annotations

import csv
import io
import json

from am_fakes import decision_event

from aegis.audit.chain import GENESIS, chain_hash
from aegis.audit.export import CSV_COLUMNS

ADMIN = {"X-Aegis-View-As": "u_tomasz"}


async def _seed(rt) -> None:
    await rt.audit.record(
        decision_event(action="block", control_id="INJ-02", reason="=cmd|' /C calc'!A0")
    )
    await rt.audit.record(decision_event())
    await rt.audit.record(decision_event(action="redact", control_id="DLP-01", reason="pii"))


async def test_jsonl_lines_reverify(am_rt, am_client):
    await _seed(am_rt)
    r = await am_client.get("/api/audit/export", params={"format": "jsonl"}, headers=ADMIN)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    assert 'filename="aegis-audit-' in r.headers["content-disposition"]
    assert r.headers["x-aegis-audit-verified"] == "ok" and r.headers["x-aegis-audit-records"] == "4"
    lines = r.text.splitlines()
    assert len(lines) == 4  # 3 decisions + the audited export event itself
    assert json.loads(lines[-1])["data"]["kind"] == "audit.export"
    assert r.headers["x-aegis-audit-head"] == json.loads(lines[-1])["hash"]
    prev = GENESIS
    for line in lines:
        rec = json.loads(line)
        assert chain_hash(rec["prev_hash"], rec) == rec["hash"] and rec["prev_hash"] == prev
        prev = rec["hash"]


async def test_jsonl_filters(am_rt, am_client):
    await _seed(am_rt)
    r = await am_client.get(
        "/api/audit/export", params={"format": "jsonl", "action": "block"}, headers=ADMIN
    )
    assert [json.loads(x)["action"] for x in r.text.splitlines()] == ["block"]
    r = await am_client.get(
        "/api/audit/export", params={"format": "jsonl", "control_id": "DLP-01"}, headers=ADMIN
    )
    assert [json.loads(x)["control_id"] for x in r.text.splitlines()] == ["DLP-01"]


async def test_csv_header_and_injection_guard(am_rt, am_client):
    await _seed(am_rt)
    r = await am_client.get("/api/audit/export", params={"format": "csv"}, headers=ADMIN)
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert list(rows[0].keys()) == CSV_COLUMNS
    assert rows[0]["reason"].startswith("'=cmd")
    assert rows[0]["controls"] == "INJ-02:block"


async def test_ocsf_classes(am_rt, am_client):
    await _seed(am_rt)
    r = await am_client.get(
        "/api/audit/export", params={"format": "ocsf", "event_type": "decision"}, headers=ADMIN
    )
    evs = [json.loads(x) for x in r.text.splitlines()]
    assert len(evs) == 3
    block, allow, redact = evs
    assert block["class_uid"] == 2004 and block["type_uid"] == 200401
    assert block["finding_info"]["analytic"]["uid"] == "INJ-02"
    assert block["disposition_id"] == 2 and block["metadata"]["version"] == "1.9.0"
    assert allow["class_uid"] == 6003 and allow["category_uid"] == 6
    assert redact["class_uid"] == 2004 and redact["disposition_id"] == 11


async def test_export_member_forbidden(am_rt, am_client):
    r = await am_client.get(
        "/api/audit/export", params={"format": "ocsf"}, headers={"X-Aegis-View-As": "u_piotr"}
    )
    assert r.status_code == 403 and r.json()["error"]["type"] == "forbidden"
