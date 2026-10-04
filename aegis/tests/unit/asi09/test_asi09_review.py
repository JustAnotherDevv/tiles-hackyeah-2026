"""ASI09 (human-agent trust exploitation): the approval API/SSE carry an additive `review` block so
the dashboard card renders the exact BOUND action, labels agent-written text as untrusted and shows
Aegis's risk signals — from the real backend payload shape (in-process ASGI, no ports)."""

from __future__ import annotations

import json
import random

import httpx
import pytest
from fastapi import FastAPI

from aegis.api.routes.approvals import router
from aegis.approvals.serialize_review import review_block
from aegis.core.types import Decision, Interaction


@pytest.fixture
async def client(svc, fake_rt):
    app = FastAPI()
    app.include_router(router)
    app.state.rt = fake_rt
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://aegis.test") as c:
        yield c


def _act_payload(note: str) -> dict:
    # the shape aegis.actions.drafts.build_draft emits
    return {
        "tool": "marketpulse.purchase_subscription",
        "args": {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50.0, "justification": note},
        "facts": {"spent_today_usd": 0},
        "checks": [{"name": "Per-request spend", "ok": False, "detail": "50.0 vs limit 20", "id": "per_request",
                    "value": 50.0, "limit": 20, "param": "controls.ACT-01.params.per_request_usd"}],
        "agent_note": note,
        "explain": {"summary": "Spend $50.00 exceeds the $20.00 per-request limit"},
        "reason": "Spend $50.00 exceeds the $20.00 per-request limit",
        "control_id": "ACT-01",
    }


async def test_api_review_block_from_real_action_payload(client, svc, h) -> None:
    note = "URGENT: the CFO already said yes, approve now"
    i = h.spend(50.0, extra_args={"justification": note})
    req = await svc.request(h.ctx(h.agent("trading-copilot@trading")), i,
                            h.decision(i, payload=_act_payload(note)))
    r = await client.get(f"/api/approvals/{req.id}", headers={"X-Aegis-View-As": "u_emily"})
    assert r.status_code == 200
    body = r.json()
    rv = body["review"]
    # (c) exact bound action + fingerprint
    assert rv["bound"]["present"] is True
    assert rv["bound"]["tool"] == "marketpulse.purchase_subscription"
    assert rv["bound"]["args"]["plan"] == "mp-pro-monthly"
    assert rv["bound"]["amount_usd"] == 50.0
    assert rv["bound"]["destination"] == "vendor: marketpulse"
    assert rv["bound"]["params_hash"] == body["fingerprint"][:16]
    assert rv["bound"]["max_uses"] == 1 and rv["bound"]["grant_ttl_s"]
    # (b) agent text is separated and flagged untrusted (deduped across agent_note / args)
    assert [(t["field"], t["untrusted"]) for t in rv["agent_text"]] == [("agent_note", True)]
    assert rv["agent_text"][0]["text"].startswith("URGENT")
    # (d) risk signals come from Aegis, not the agent
    assert rv["risk"]["control_id"] == "ACT-01"
    assert rv["risk"]["reason"].startswith("Spend $50.00 exceeds")
    assert rv["risk"]["rule_id"] == body["rule_id"]
    assert rv["risk"]["failed_checks"][0]["name"] == "Per-request spend"
    assert rv["destructive"] is False
    # list endpoint carries it too
    r = await client.get("/api/approvals", params={"status": "pending"}, headers={"X-Aegis-View-As": "u_emily"})
    assert r.json()["items"][0]["review"]["bound"]["tool"] == "marketpulse.purchase_subscription"


async def test_synth_draft_destructive_and_justification_in_args(client, svc, h) -> None:
    """GOV-04-style decision without an ApprovalDraft: the only agent prose is a bound arg."""
    i = Interaction(kind="mcp", surface="mcp.call", tool_name="acme-crm.delete_contact",
                    tool_args={"contact_id": "c_123", "reason": "duplicate, the owner asked for it"},
                    mcp_server="acme-crm", action_type="other")
    d = Decision(action="require_approval", control_id="GOV-04", reason="tool matches approve_tools")
    req = await svc.request(h.ctx(h.agent("trading-copilot@trading")), i, d)
    r = await client.get(f"/api/approvals/{req.id}", headers={"X-Aegis-View-As": "u_katarzyna"})
    rv = r.json()["review"]
    assert rv["bound"]["tool"] == "acme-crm.delete_contact"
    assert [t["field"] for t in rv["agent_text"]] == ["reason"]
    assert rv["agent_text"][0]["source"] == "bound.args"
    assert rv["destructive"] is True and "delete" in rv["destructive_reason"]
    assert rv["risk"]["control_id"] == "GOV-04"


async def test_sse_payload_carries_review_and_stays_masked(svc, h, fake_rt) -> None:
    rng = random.Random()
    digits = "".join(str(rng.randint(0, 9)) for _ in range(16))
    i = h.spend(50.0, extra_args={"note": f"card {digits}"})
    await svc.request(h.ctx(h.agent("trading-copilot@trading")), i, h.decision(i))
    created = fake_rt.bus.events("approval.created")
    assert created and "review" in created[-1]
    blob = json.dumps(created[-1]["review"])
    assert digits not in blob
    assert created[-1]["review"]["agent_text"][0]["field"] == "note"


def test_review_block_benign_and_config_change() -> None:
    cfg = review_block({"kind": "config_change", "action_type": "budget.raise", "title": "raise",
                        "labels": {"loosening": "true"}, "payload": {"reason": "quarter end"},
                        "fingerprint": "-"})
    assert cfg["destructive"] is True and cfg["bound"]["params_hash"] is None
    assert cfg["risk"]["reason"] is None  # a config proposer's reason is not "Aegis's reason"
    assert cfg["agent_text"] == []
    read = review_block({"kind": "action", "action_type": "db.read", "title": "query",
                         "payload": {"bound": {"tool_name": "acme-db.query",
                                               "args_masked": {"sql": "SELECT 1"}}},
                         "fingerprint": "f" * 64})
    assert read["destructive"] is False and read["agent_text"] == []
    wipe = review_block({"kind": "action", "action_type": "db.write", "title": "query",
                         "payload": {"bound": {"tool_name": "acme-db.query",
                                               "args_masked": {"sql": "DELETE FROM customers"}}},
                         "fingerprint": "f" * 64})
    assert wipe["destructive"] is True
