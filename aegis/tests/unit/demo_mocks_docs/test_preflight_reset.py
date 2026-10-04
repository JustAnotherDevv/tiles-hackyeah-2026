"""DEMO-07 pure logic: preflight verdict/exit codes, reset kill-scope parsing, degraded reset."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[3]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pf():
    return _load("aegis_demo_preflight", "demo/preflight.py")


@pytest.fixture(scope="module")
def rs():
    return _load("aegis_demo_reset_t", "demo/scenarios/reset.py")


def test_verdict_levels(pf):
    ok = [pf.Row("gateway", "ok"), pf.Row("mock_llm", "ok")]
    assert pf.verdict(ok) == ("READY", 0)
    banner, code = pf.verdict([*ok, pf.Row("RAM", "warn")])
    assert code == 1 and banner.startswith("READY (degraded: RAM")
    assert pf.verdict([*ok, pf.Row("smoke: PII redact", "fail")])[1] == 2
    assert pf.verdict([pf.Row("gateway", "fail")]) == ("NOT READY", 2)


def test_kill_scopes(rs):
    yaml_text = """
budgets:
  kill_switch: {global: true, teams: [trading], members: [], agents: [chaos-agent@platform], sessions: [ses_1]}
"""
    assert rs.kill_scopes(yaml_text) == ["global", "team:trading", "agent:chaos-agent@platform", "session:ses_1"]
    assert rs.kill_scopes("not: [valid") == []
    assert rs.kill_scopes("") == []


def test_reset_degrades_without_gateway(rs):
    from aegis.sdk import AegisAdmin

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=req)

    admin = AegisAdmin("http://gw.test", "u_katarzyna", transport=httpx.MockTransport(down))
    http = httpx.Client(transport=httpx.MockTransport(down))
    steps = rs.reset_demo("http://gw.test", admin=admin, http=http)
    names = [n for n, _, _ in steps]
    assert "approvals" in names and "kill switches" in names and "threat feed" in names
    assert all(st == "skip" for _, st, _ in steps), steps
