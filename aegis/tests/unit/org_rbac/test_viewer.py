"""ORG-V06: dashboard viewer resolution (view-as header / query / cookie / default)."""

from __future__ import annotations

import logging

import pytest

from aegis.org.service import create


@pytest.mark.parametrize(
    ("headers", "query", "member_id", "role"),
    [
        ({"X-Aegis-View-As": "admin"}, None, "u_emily", "admin"),
        ({"X-Aegis-View-As": "owner"}, None, "u_katarzyna", "owner"),
        ({"X-Aegis-View-As": "member"}, None, "u_piotr", "member"),
        ({"x-aegis-view-as": "u_marek"}, None, "u_marek", "admin"),
        ({}, {"view_as": "u_piotr"}, "u_piotr", "member"),
        ({"cookie": "foo=1; aegis_view_as=marek"}, None, "u_marek", "admin"),
        ({"X-Aegis-View-As": "Emily"}, None, "u_emily", "admin"),
        ({"Sec-Fetch-Site": "same-origin"}, None, "u_katarzyna", "owner"),
        ({"X-Aegis-View-As": "u_tomasz"}, {"view_as": "u_piotr"}, "u_tomasz", "member"),
    ],
)
async def test_resolve_viewer(rt, headers, query, member_id, role):
    viewer = await rt.org.resolve_viewer(headers, query)
    assert viewer.member_id == member_id
    assert viewer.role == role
    assert viewer.agent_id is None
    assert viewer.org_id == "acme-capital"
    assert viewer.display_name


@pytest.mark.parametrize("value", ["u_zz_nobody", "research-agent@research", "chaos-agent@platform"])
async def test_unknown_view_as_is_anonymous_never_owner(rt, caplog, value):
    """Security regression (INT-A): unknown ids and agent ids must never fall back to the
    default viewer (the owner in the demo seed) - they get an anonymous, least-privilege viewer."""
    with caplog.at_level(logging.WARNING, logger="aegis.org.identity"):
        viewer = await rt.org.resolve_viewer({"X-Aegis-View-As": value})
    assert viewer.member_id is None and viewer.role == "viewer" and not viewer.authenticated
    assert any("unknown view-as" in r.getMessage() for r in caplog.records) or value != "u_zz_nobody"


async def test_default_viewer_setting(make_rt):
    fake = make_rt()
    fake.settings.default_viewer = "u_marek"
    svc = create(fake)
    await svc.start()
    browser = {"Sec-Fetch-Site": "same-origin"}
    assert (await svc.resolve_viewer(browser)).member_id == "u_marek"


async def test_non_demo_mode_requires_admin_token(make_rt):
    fake = make_rt()
    fake.settings.demo_mode = False
    fake.settings.admin_token = "tok-123"
    svc = create(fake)
    await svc.start()
    anon = await svc.resolve_viewer({"X-Aegis-View-As": "owner"})
    assert anon.member_id is None and anon.display_name == "anonymous viewer"
    ok = await svc.resolve_viewer({"X-Aegis-View-As": "owner", "Authorization": "Bearer tok-123"})
    assert ok.member_id == "u_katarzyna" and ok.authenticated
