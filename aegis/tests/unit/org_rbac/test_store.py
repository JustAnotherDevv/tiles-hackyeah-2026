"""ORG-V03 / ORG-V04: SQLite store, seeding, restart behaviour and key privacy."""

from __future__ import annotations

import re
import sqlite3

from aegis.org import store
from aegis.org.seed import load_bundle
from aegis.org.service import create


async def test_seed_and_read_side(rt):
    org = rt.org
    assert (await org.org()).id == "acme-capital"
    assert len(await org.list_members()) == 8
    assert len(await org.list_agents()) == 5
    assert len(await org.list_teams()) == 3
    cc = await org.get_agent("claude-code@platform")
    assert cc is not None and cc.owner_member_id == "u_tomasz"
    assert (await org.get_agent("claude-code")).id == "claude-code@platform"
    assert await org.get_member("u_nobody") is None
    res = await org.resources()
    assert any(t["name"] == "customers" for t in res["databases"][0]["tables"])
    res["databases"].clear()  # copies: callers cannot mutate the cache
    assert (await org.resources())["databases"]
    seeds = [e for e in rt.audit.org_changes() if e.data.get("op") == "seed"]
    assert len(seeds) == 1 and seeds[0].data["counts"]["members"] == 8
    assert org.health() == "ok"


async def test_members_with_role(rt):
    admins = [m.id for m in await rt.org.members_with_role("admin")]
    assert admins == ["u_katarzyna", "u_marek", "u_emily"]
    research_admins = [m.id for m in await rt.org.members_with_role("admin", team_id="research")]
    assert research_admins == ["u_katarzyna", "u_emily"]
    owners = [m.id for m in await rt.org.members_with_role("owner", team_id="platform")]
    assert owners == ["u_katarzyna"]


async def test_restart_does_not_reseed_and_reset_does(rt, make_rt):
    m = await rt.org.get_member("u_olivia")
    m.title = "Lead Quant"
    await rt.org.write_member(m)
    await rt.org.stop()
    fake2 = make_rt()
    svc2 = create(fake2)
    await svc2.start()
    assert (await svc2.get_member("u_olivia")).title == "Lead Quant"
    assert not [e for e in fake2.audit.org_changes() if e.data.get("op") == "seed"]
    conn = fake2.db()
    try:
        store.apply_seed(conn, load_bundle(rt.settings.org_seed), reset=True)
    finally:
        conn.close()
    await svc2.reload()
    assert (await svc2.get_member("u_olivia")).title == "Quant Analyst"


async def test_no_plaintext_keys_in_db(rt):
    conn = sqlite3.connect(str(rt.tmp / "aegis.db"))
    try:
        dump = "\n".join(conn.iterdump())
        hmacs = [r[0] for r in conn.execute("SELECT key_hmac FROM api_keys")]
    finally:
        conn.close()
    assert "NOT_A_SECRET" not in dump
    assert "aegis_demo_" not in dump
    assert len(hmacs) == 6
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hmacs)


async def test_invalid_seed_on_empty_db_degrades(make_rt, tmp_path):
    bad = tmp_path / "broken.yaml"
    bad.write_text("org: {id: x}\nmembers: 5\n")
    fake = make_rt(org_seed=bad)
    svc = create(fake)
    await svc.start()
    assert svc.health() == "degraded"
    assert [m.id for m in await svc.list_members()] == ["u_katarzyna"]


async def test_hmac_rotation_rehashes_seed_keys(rt, make_rt, helpers):
    from aegis.core import crypto

    await rt.org.stop()
    crypto.configure(data_dir=rt.tmp, key="rotated-key")
    fake2 = make_rt()
    svc2 = create(fake2)
    await svc2.start()
    ident = await svc2.resolve_identity({"authorization": f"Bearer {helpers.KEYS['research']}"})
    assert ident.authenticated and ident.agent_id == "research-agent@research"
