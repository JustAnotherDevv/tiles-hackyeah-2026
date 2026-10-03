"""DEMO-V03 (saas): catalog price check, charges ledger, deterministic CRM with valid PESEL."""

from __future__ import annotations

from mocks.mock_llm import fakegen
from mocks.mock_saas import fakedata


async def test_subscription_price_check_and_charges(saas):
    ok = await saas.post("/payments/subscriptions",
                         json={"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50, "currency": "USD"})
    assert ok.status_code == 201 and ok.json()["status"] == "active" and ok.json()["id"].startswith("sub_")
    bad = await saas.post("/payments/subscriptions",
                          json={"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 4800})
    assert bad.status_code == 400 and bad.json()["error"] == "price mismatch"
    unknown = await saas.post("/payments/subscriptions", json={"vendor": "nope", "plan": "x", "amount_usd": 1})
    assert unknown.status_code == 404
    ch = await saas.post("/payments/charges", json={"vendor": "gpucloud", "amount_usd": 480, "currency": "USD"})
    assert ch.status_code == 201 and ch.json()["status"] == "succeeded"
    d = (await saas.get("/_mock/charges")).json()
    assert d["total_usd"] == 530.0 and d["count"] == 2


async def test_plans_include_seed_vendors():
    plans = {(p["vendor"], p["plan"]): p["amount_usd"] for p in fakedata.plans()}
    assert plans[("marketpulse", "mp-pro-monthly")] == 50.0
    assert plans[("gpucloud", "a100-cluster-week")] == 1500.0
    assert plans[("opendata-shop", "eu-equities-2025-csv")] == 12.0


async def test_crm_deterministic_with_valid_ids(saas):
    a, b = fakedata.contacts(7), fakedata.contacts(7)
    assert a == b and a != fakedata.contacts(8)
    assert all(fakegen.pesel_ok(c["pesel"]) and fakegen.iban_ok(c["iban"]) for c in a)
    d = (await saas.get("/crm/contacts")).json()
    assert d["count"] == len(a) and d["contacts"][0]["id"] == "C-1001"
    one = await saas.get("/crm/customers/C-1001")
    assert one.json()["name"] == a[0]["name"]
    assert (await saas.get("/crm/customers/C-9")).status_code == 404


async def test_paste_webhook_requests_reset(saas):
    p = (await saas.post("/paste", json={"content": "hello"})).json()
    assert p["url"].startswith("http://paste.test/p/")
    assert (await saas.get(f"/p/{p['id']}")).text == "hello"
    assert (await saas.post("/crm/webhook", json={"event": "x"})).json()["ok"] is True
    reqs = (await saas.get("/_mock/requests")).json()
    assert reqs["count"] == 3 and reqs["items"][0]["path"] == "/crm/webhook"
    assert (await saas.delete("/_mock/requests")).json()["cleared"] == 3
    await saas.post("/payments/charges", json={"amount_usd": 1})
    assert (await saas.post("/_mock/reset")).json()["ok"] is True
    assert (await saas.get("/_mock/charges")).json()["count"] == 0
    assert (await saas.get("/_mock/health")).json()["service"] == "mock_saas"
