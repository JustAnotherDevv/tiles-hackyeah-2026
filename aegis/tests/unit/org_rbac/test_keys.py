"""ORG-11/ORG-12: permissions matrix endpoint and agent API key lifecycle."""

from __future__ import annotations

import sqlite3

from aegis.controls.governance.gov01_identity import CONTROLS
from aegis.core.types import Interaction

GOV01 = CONTROLS[0]
INTERACTION = Interaction(kind="model_call", surface="model.request")
MAREK = {"X-Aegis-View-As": "u_marek"}
PIOTR = {"X-Aegis-View-As": "u_piotr"}


async def _gov01(rt, helpers, key: str):
    ident = await rt.org.resolve_identity({"Authorization": f"Bearer {key}"})
    ctx = helpers.ctx_for(ident, "proxy")
    return await GOV01.evaluate(ctx, INTERACTION, ctx.policy.controls["GOV-01"])


async def test_permissions_matrix_endpoint(client):
    r = await client.get("/api/org/permissions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body, "matrix must not be empty"


async def test_key_issue_use_revoke(client, rt, helpers):
    # members cannot see or issue keys
    r = await client.get("/api/agents/research-agent@research/keys", headers=PIOTR)
    assert r.status_code == 403
    r = await client.post("/api/agents/research-agent@research/keys", headers=PIOTR)
    assert r.status_code == 403

    r = await client.post("/api/agents/research-agent@research/keys", headers=MAREK)
    assert r.status_code == 201, r.text
    assert r.headers.get("cache-control") == "no-store"
    issued = r.json()
    plaintext, key_id = issued["key"], issued["key_id"]
    assert plaintext.startswith("aegis_")

    # plaintext is shown once: listing never returns it, and SQLite stores only the HMAC
    r = await client.get("/api/agents/research-agent@research/keys", headers=MAREK)
    assert r.status_code == 200 and plaintext not in r.text
    assert key_id in {k["key_id"] for k in r.json()["items"]}
    with sqlite3.connect(rt.tmp / "aegis.db") as conn:
        dump = "\n".join(conn.iterdump())
    assert plaintext not in dump

    ident = await rt.org.resolve_identity({"Authorization": f"Bearer {plaintext}"})
    assert ident.agent_id == "research-agent@research"
    assert (await _gov01(rt, helpers, plaintext)) is None

    # audit trail carries no key material
    assert plaintext not in str([e.data for e in rt.audit.org_changes()])

    r = await client.post(
        f"/api/agents/research-agent@research/keys/{key_id}/revoke", headers=MAREK
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "revoked"
    d = await _gov01(rt, helpers, plaintext)
    assert d is not None and d.action == "block"
    assert d.findings[0].detector == "gov.key_revoked"

    # wrong agent / unknown key -> 404
    r = await client.post(f"/api/agents/claude-code@platform/keys/{key_id}/revoke", headers=MAREK)
    assert r.status_code == 404
