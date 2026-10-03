"""CC-07: profile generator (settings*.json, mcp.json, .agent_key) - confined to a tmp dir."""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from aegis.integrations.claude_code import profile

GW = "http://127.0.0.1:8787"


@pytest.fixture
def out(tmp_path: Path) -> Path:
    o = tmp_path / "claude"
    profile.write_profile(o, gateway_url=GW)
    return o


def load(p: Path) -> dict:
    return json.loads(p.read_text())


def test_files_written_only_under_out(out: Path, tmp_path: Path):
    names = sorted(p.name for p in out.iterdir())
    assert names == [".agent_key", "mcp.json", "settings.failclosed.json", "settings.hardened.json",
                     "settings.json"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["claude"]
    assert stat.S_IMODE((out / ".agent_key").stat().st_mode) == 0o600
    assert profile.check_profile(out, gateway_url=GW) == []


def test_settings_env_and_hooks(out: Path):
    s = load(out / "settings.json")
    env = s["env"]
    assert env["ANTHROPIC_BASE_URL"] == GW and env["AEGIS_URL"] == GW
    assert "X-Aegis-Agent: claude-code@platform" in env["ANTHROPIC_CUSTOM_HEADERS"]
    assert "X-Aegis-Agent-Key: aegis_" in env["ANTHROPIC_CUSTOM_HEADERS"]  # SF-15
    assert env["CLAUDE_CODE_GATEWAY_HINT_HEADERS"] == "1"
    assert Path(env["AEGIS_AGENT_KEY_FILE"]).is_absolute()
    assert "disableAllHooks" not in s and "allowManagedHooksOnly" not in s
    for event, matcher, blocking in profile.HOOK_EVENTS:
        entry = s["hooks"][event][0]
        if matcher:
            assert entry["matcher"] == matcher
        h = entry["hooks"][0]
        assert h["type"] == "command" and str(profile.HOOK_SCRIPT) in h["command"]
        assert Path(str(profile.HOOK_SCRIPT)).is_absolute()
        assert h["command"].endswith(" || exit 2") == blocking
        # timeout ordering: settings > curl > gateway hold
        if blocking:
            assert h["timeout"] > int(env["AEGIS_HOOK_TIMEOUT"]) > profile.HOLD_MAX
        else:
            assert h["timeout"] > int(env["AEGIS_HOOK_TIMEOUT_FAST"])
        assert "aegis_demo" not in h["command"]  # key never on the command line


def test_failclosed_and_hardened_variants(out: Path):
    f = load(out / "settings.failclosed.json")
    assert f["env"]["AEGIS_URL"] == profile.DEAD_GATEWAY and f["env"]["ANTHROPIC_BASE_URL"] == GW
    assert profile.DEAD_GATEWAY in f["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    h = load(out / "settings.hardened.json")
    assert "Read(**/.env)" in h["permissions"]["deny"]
    assert h["permissions"]["disableBypassPermissionsMode"] == "disable"
    d = load(out / "settings.json")
    assert "Read(**/.env)" not in d["permissions"]["deny"]  # demo keeps the Aegis EXE-02 moment
    assert any(r.startswith("Edit(//") and r.endswith("settings.json)") for r in d["permissions"]["deny"])


def test_mcp_json_routes_through_gateway(out: Path):
    m = load(out / "mcp.json")["mcpServers"]
    assert "payments" in m and "acme-db" in m
    for name, srv in m.items():
        assert srv["type"] == "http" and srv["url"] == f"{GW}/mcp/{name}"
        assert srv["headers"]["X-Aegis-Agent"] == "claude-code@platform"
        assert srv["headers"]["Authorization"].startswith("Bearer aegis_")


def test_if_stale_is_idempotent(out: Path):
    assert profile.write_profile(out, gateway_url=GW, if_stale=True) == []
    (out / "mcp.json").write_text("{}")
    assert [p.name for p in profile.write_profile(out, gateway_url=GW, if_stale=True)] == ["mcp.json"]


def test_refuses_dangerous_out_dirs(tmp_path: Path):
    with pytest.raises(profile.ProfileError):
        profile.write_profile(Path.home() / ".claude" / "aegis-test-never")
    with pytest.raises(profile.ProfileError):
        profile.write_profile(tmp_path / "proj" / ".claude")
    assert not (Path.home() / ".claude" / "aegis-test-never").exists()
    assert not (tmp_path / "proj").exists()


def test_check_detects_tampering(out: Path):
    s = load(out / "settings.json")
    s["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = "true"
    s["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 5
    s["disableAllHooks"] = True
    (out / "settings.json").write_text(json.dumps(s))
    problems = profile.check_profile(out, gateway_url=GW)
    assert any("disableAllHooks" in p for p in problems)
    assert any("PreToolUse hook does not call" in p for p in problems)
    assert any("Stop settings timeout 5" in p for p in problems)


def test_guarded_command_missing_script_exit_2(tmp_path: Path):
    cmd = profile.hook_command("PreToolUse", True, gateway_url=profile.DEAD_GATEWAY,
                               script=tmp_path / "missing" / "aegis-hook")
    r = subprocess.run(["/bin/sh", "-c", cmd], input=b"{}", capture_output=True)
    assert r.returncode == 2
    cmd = profile.hook_command("PreToolUse", True, gateway_url=profile.DEAD_GATEWAY)
    r = subprocess.run(["/bin/sh", "-c", cmd], input=b'{"hook_event_name":"PreToolUse"}',
                       capture_output=True)
    assert r.returncode == 2 and b"fail-closed" in r.stderr


def test_managed_text_is_text_only(capsys):
    assert profile.main(["--print-managed"]) == 0
    assert "NOT written by Aegis" in capsys.readouterr().out


def test_committed_profile_is_valid():
    committed = profile.DEFAULT_OUT
    if not (committed / "settings.json").exists():
        pytest.skip("profile not generated")
    for name in ("settings.json", "settings.failclosed.json", "settings.hardened.json", "mcp.json"):
        json.loads((committed / name).read_text())
