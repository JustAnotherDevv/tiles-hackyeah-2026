"""ROG-01 through the REAL gateway (/v1/guard, in-process, golden policy + asi-10 snippet).

* the demo trading_copilot pattern over several sessions: ROG-01 never steps in;
* the F6 runaway loop (identical web.fetch_url): EXE-04 decides, ROG-01 stays out of the way;
* a sub-agent spawn storm: ROG-01 answers 429 ``killed`` and quarantines the session through the
  budgets ledger's runtime kill switch -> the next call of that session is 429 killed;
* self-modification of the Aegis policy file: approval routed by ROG-01.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from aegis.core import crypto
from aegis.rogue.store import STORE
from tests.lib.identities import headers_for
from tests.lib.stack import HMAC_TEST_KEY
from tests.unit.asi10.conftest import CLAUDE, TRADING, snippet_controls

ROOT = Path(__file__).resolve().parents[3]
CHAOS = "chaos-agent@platform"


def _reset() -> None:
    STORE.reset()
    try:
        from aegis.controls.resilience._state import STATE

        STATE.reset()
    except Exception:
        pass


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data = tmp_path / "data"
    policy = tmp_path / "policy.yaml"
    shutil.copy(ROOT / "config" / "policy.golden.yaml", policy)
    doc = yaml.safe_load(policy.read_text())
    new = {c["id"]: c for c in snippet_controls()}
    doc["controls"] = [c for c in doc.get("controls", []) if c.get("id") not in new]
    doc["controls"].extend(new.values())
    policy.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    for k, v in {
        "AEGIS_DATA_DIR": str(data), "AEGIS_POLICY": str(policy), "AEGIS_SEMANTIC": "off",
        "AEGIS_FEED_URL": "disabled", "AEGIS_TEST_MODE": "1", "AEGIS_DEMO_MODE": "1",
        "AEGIS_HMAC_KEY": HMAC_TEST_KEY, "AEGIS_WARMUP": "off", "AEGIS_PORT": "0",
        "AEGIS_REPORTS_DIR": str(tmp_path / "reports"),
    }.items():
        monkeypatch.setenv(k, v)
    from aegis.app import create_app
    from aegis.settings import Settings, get_settings

    get_settings.cache_clear()
    _reset()
    crypto.configure(data_dir=data)
    try:
        with TestClient(create_app(Settings.from_env())) as c:
            yield c
    finally:
        _reset()
        crypto.configure(data_dir=None)
        crypto.reset_key_cache()
        get_settings.cache_clear()


def guard(client, who: str, session: str, complete: bool = True, **inter) -> dict:
    inter.setdefault("kind", {"tool": "tool_call", "mcp": "mcp", "a2a": "a2a"}[
        inter["surface"].split(".")[0]])
    h = {**headers_for(who), "X-Aegis-Session": session, "X-Aegis-Wait": "0"}
    r = client.post("/v1/guard", json={"interaction": inter, "session_id": session, "wait_s": 0},
                    headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    if complete and body["verdict"]["action"] in ("allow", "log", "redact"):
        client.post("/v1/guard/complete", json={"decision_id": body["decision_id"],
                                                "status_code": 200})
    return body


def rog(body: dict) -> list[dict]:
    return [d for d in body["verdict"].get("decisions") or []
            if d.get("control_id") == "ROG-01" and d.get("action") != "allow"]


def primary(body: dict) -> tuple[str, str | None, dict]:
    v = body["verdict"]
    p = v.get("primary") or {}
    return v["action"], p.get("control_id"), p


def mcp(tool: str, args: dict) -> dict:
    return {"surface": "mcp.call", "tool_name": tool, "tool_args": args}


def test_rog01_registered_and_enforcing(client) -> None:
    rt = client.app.state.rt
    snap = rt.policy.snapshot()
    cfg = snap.controls["ROG-01"]
    assert cfg.enabled and cfg.mode == "enforce"
    assert "ROG-01" in {c.id for c in rt.registry.all()} if hasattr(rt, "registry") else True


def test_trading_copilot_demo_pattern_unaffected(client) -> None:
    for n in range(5):
        session = f"s-trade-{n}-{uuid.uuid4().hex[:6]}"
        for call in (
            mcp("marketpulse.get_quote", {"ticker": "PKO"}),
            mcp("marketpulse.get_quote", {"ticker": "PZU"}),
            mcp("marketpulse.get_news", {"ticker": "KGH"}),
            mcp("acme-db.query", {"sql": "SELECT name, email FROM customers LIMIT 5"}),
            mcp("mailer.send_email", {"to": "emily.carter@acme-capital.example",
                                      "subject": "Q3", "body": "Q3 summary"}),
            mcp("mailer.send_email", {"to": f"client{n}@example.com", "subject": "Refund",
                                      "body": "Your refund was sent."}),
            mcp("marketpulse.purchase_subscription",
                {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50}),
        ):
            body = guard(client, TRADING, session, **call)
            assert not rog(body), (call["tool_name"], rog(body))


def test_f6_runaway_loop_still_decided_by_exe04(client) -> None:
    session = f"s-chaos-{uuid.uuid4().hex[:6]}"
    seen = []
    for _ in range(6):
        body = guard(client, CHAOS, session, **mcp("web.fetch_url",
                                                   {"url": "http://news.example/markets"}))
        action, cid, _ = primary(body)
        seen.append((action, cid))
        assert not rog(body)
    assert ("block", "EXE-04") in seen


def test_spawn_storm_is_killed_and_session_quarantined(client) -> None:
    session = f"s-storm-{uuid.uuid4().hex[:6]}"
    out = []
    for k in range(16):
        body = guard(client, CLAUDE, session, surface="tool.input", tool_name="Task",
                     tool_args={"description": f"worker {k}", "prompt": f"replicate part {k}"})
        out.append(primary(body))
    assert out[7][:2] == ("require_approval", "ROG-01"), out[7]
    action, cid, p = out[-1]
    assert (action, cid) == ("block", "ROG-01"), out[-1]
    assert p["http_status"] == 429 and p["error_type"] == "killed"
    assert "spawn" in p["reason"] and "quarantined" in p["reason"]
    led = client.app.state.rt.ledger
    assert led.kills.get(session) is not None or session in str(led.kill_switch_view())
    body = guard(client, CLAUDE, session, surface="tool.input", tool_name="Read",
                 tool_args={"file_path": "/tmp/aegis-demo/README.md"})
    action, cid, p = primary(body)
    assert action == "block" and p["error_type"] == "killed" and cid in ("EXE-04", "ROG-01")
    # another session of the same agent keeps working
    body = guard(client, CLAUDE, f"s-ok-{uuid.uuid4().hex[:6]}", surface="tool.input",
                 tool_name="Read", tool_args={"file_path": "/tmp/aegis-demo/README.md"})
    assert primary(body)[0] in ("allow", "log", "redact")


def test_self_modification_of_policy_needs_approval(client) -> None:
    body = guard(client, CLAUDE, f"s-sm-{uuid.uuid4().hex[:6]}", surface="tool.input",
                 tool_name="Edit", tool_args={"file_path": "/tmp/aegis-demo/config/policy.yaml",
                                              "old_string": "mode: enforce",
                                              "new_string": "mode: off"})
    action, cid, p = primary(body)
    assert (action, cid) == ("require_approval", "ROG-01"), (action, cid, p.get("reason"))
    assert "self-modification" in p["reason"]
