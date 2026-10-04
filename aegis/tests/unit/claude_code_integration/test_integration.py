"""CC-V05: the hook route against the real app (create_app + lifespan, in-process ASGI).

Hard guarantees: always 200, malformed blocking events fail closed, decision id header, session
bookkeeping, replay fixtures parse, GOV-06 scenes block, DLP-08 rehydrates locally. Integration is
complete, so nothing here skips on "not wired yet"; the observed outcome is printed (`pytest -s`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import asgi_lifespan
import httpx
import pytest

from aegis import app as app_mod
from aegis import settings as settings_mod

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "demo" / "claude"))
import replay  # noqa: E402

HDR = {"X-Aegis-Agent": "claude-code@platform", "X-Aegis-Hook-Deadline": "12",
       "Authorization": "Bearer aegis_demo_cc_platform_0000000000000001_NOT_A_SECRET"}


@pytest.fixture
async def live(tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_TEST_MODE", "1")
    monkeypatch.setenv("AEGIS_SEMANTIC", "off")
    settings = settings_mod.Settings(data_dir=tmp_path / "data", ui_dist=tmp_path / "dist")
    app = app_mod.create_app(settings)
    async with asgi_lifespan.LifespanManager(app, startup_timeout=60, shutdown_timeout=30):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as client:
            yield app, client


async def _send(client, event: str, payload: dict) -> tuple[dict, dict]:
    r = await client.post("/v1/hooks/claude-code", content=json.dumps(payload).encode(),
                          headers={**HDR, "X-Aegis-Hook-Event": event,
                                   "content-type": "application/json"})
    assert r.status_code == 200, r.text
    return r.json(), dict(r.headers)


async def test_malformed_blocking_event_fails_closed(live):
    _, client = live
    r = await client.post("/v1/hooks/claude-code", content=b"{not json",
                          headers={**HDR, "X-Aegis-Hook-Event": "PreToolUse"})
    assert r.status_code == 200
    h = r.json()["hookSpecificOutput"]
    assert h["permissionDecision"] == "deny" and "fail-closed" in h["permissionDecisionReason"]
    r = await client.post("/v1/hooks/claude-code", content=b"{not json",
                          headers={**HDR, "X-Aegis-Hook-Event": "PostToolUse"})
    assert r.status_code == 200 and r.json() == {}


SCENES = ["session_start", "read_readme", "git_status", "pipe_to_shell", "read_dotenv",
          "webfetch", "setup_md_post", "prompt_pii", "edit_hook_settings", "config_change"]


async def test_replay_scenes_in_process(live, capsys):
    app, client = live
    rt = app.state.rt
    t = replay.Templater("cc-v05-session", 1)
    outcomes: dict[str, list[tuple[str, str, bool]]] = {}
    try:
        for name in SCENES:
            fx = replay.load_fixture(name)
            for step in fx["steps"]:
                out, headers = await _send(client, step["event"], t.apply(step["payload"]))
                result, text = replay.classify(step["event"], out)
                ok = replay.matches(step.get("expect", {}), result, text)
                outcomes.setdefault(name, []).append((result, text[:160], ok))
                if step["event"] in ("PreToolUse", "UserPromptSubmit") and result != "fail_closed":
                    assert headers.get("x-aegis-decision-id", "").startswith("dec"), (name, headers)
    finally:
        t.cleanup()
    with capsys.disabled():
        for name, steps in outcomes.items():
            for result, text, ok in steps:
                print(f"\n  [{'OK ' if ok else '-- '}] {name:<20} {result:<8} {text}")
    # never fail closed on a healthy runtime
    assert not any(r == "fail_closed" for s in outcomes.values() for r, _, _ in s)
    # the session is registered and shared across events
    st = await client.get("/v1/hooks/claude-code/status")
    assert st.status_code == 200
    assert any(s["session_id"] == "cc-v05-session" for s in st.json()["sessions"])
    # GOV-06 (harness integrity) is loaded and enforcing in the shipped policy: its scenes match
    assert rt.controls.get("GOV-06") is not None, "GOV-06 control not loaded"
    cfg = rt.policy.snapshot().controls.get("GOV-06")
    assert cfg is not None and cfg.enabled and cfg.mode == "enforce", cfg
    assert outcomes["edit_hook_settings"][0][2], outcomes["edit_hook_settings"]
    assert outcomes["config_change"][0][2], outcomes["config_change"]
    assert outcomes["read_readme"][0][0] in ("allow", "modify")


async def test_local_rehydration_round_trip(live, capsys):
    """F1 'wow': PII tokenized on the way out, restored locally in the Write tool's input."""
    _, client = live
    sid = "cc-v05-rehydrate"
    out, _ = await _send(client, "UserPromptSubmit", {
        "hook_event_name": "UserPromptSubmit", "session_id": sid,
        "prompt": "Write a letter to Jan Kowalski, PESEL 44051401359, jan.kowalski@example.com"})
    out2, _ = await _send(client, "PreToolUse", {
        "hook_event_name": "PreToolUse", "session_id": sid, "tool_name": "Write",
        "tool_use_id": "toolu_rh", "cwd": "/tmp/aegis-demo/project",
        "tool_input": {"file_path": "/tmp/aegis-demo/project/letters/C-1003.md",
                       "content": "Dear [PERSON_1], PESEL [PESEL_1], mail [EMAIL_1]"}})
    with capsys.disabled():
        print("\n  prompt ->", out, "\n  write  ->", json.dumps(out2)[:400])
    hso = out2.get("hookSpecificOutput") or {}
    assert "updatedInput" in hso, f"DLP-08 did not request local rehydration: {out2}"
    assert "44051401359" in hso["updatedInput"]["content"]
    assert hso["permissionDecision"] == "allow" and "DLP-08" in hso["permissionDecisionReason"]
