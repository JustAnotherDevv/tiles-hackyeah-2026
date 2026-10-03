"""ORG-V02 / ORG-V03: seed parsing, contract mapping and the --check CLI."""

from __future__ import annotations

from pathlib import Path

import yaml

from aegis.org import seed
from aegis.org.seed import SeedError, load_bundle, main, map_models, map_tool


def test_check_summary(capsys, helpers):
    assert main(["--check", "--path", str(helpers.SEED)]) == 0
    out = capsys.readouterr().out.strip()
    assert out == (
        "org acme-capital: teams=3 members=8 (owners=1 admins=2) agents=5 "
        "(inactive=1) keys=6 (revoked=1 expired=1)"
    )


def test_broken_sponsor_reports_path(tmp_path: Path, capsys, helpers):
    data = yaml.safe_load(helpers.SEED.read_text())
    data["agents"][1]["sponsor"] = "u_nobody"
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(data))
    assert main(["--check", "--path", str(bad)]) == 1
    assert "agents[1].sponsor" in capsys.readouterr().err


def test_no_owner_is_invalid(tmp_path: Path, helpers):
    data = yaml.safe_load(helpers.SEED.read_text())
    for m in data["members"]:
        if m["role"] == "owner":
            m["role"] = "admin"
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(data))
    try:
        load_bundle(bad)
    except SeedError as exc:
        assert any("owner" in msg for _, msg in exc.errors)
    else:  # pragma: no cover
        raise AssertionError("expected SeedError")


def test_mapping(helpers):
    b = load_bundle(helpers.SEED)
    agents = {a.id: a for a in b.agents}
    members = {m.id: m for m in b.members}
    cc = agents["claude-code@platform"]
    assert cc.kind == "claude-code"
    assert cc.owner_member_id == "u_tomasz"
    assert cc.name == "Claude Code (Platform)"
    assert agents["research-agent@research"].max_destination == "local"
    assert agents["research-agent@research"].kind == "scripted"
    assert agents["trading-copilot@trading"].kind == "sdk"
    assert agents["chaos-agent@platform"].kind == "other"
    assert agents["chaos-agent@platform"].meta["seed_kind"] == "red_team"
    assert not agents["legacy-bot@platform"].active
    research_tools = agents["research-agent@research"].allowed_tools
    assert "acme-db.*" in research_tools
    assert not any(t.startswith("mcp__") for a in b.agents for t in a.allowed_tools)
    assert members["u_emily"].meta["teams"] == ["trading", "research"]
    assert members["u_emily"].team_id == "trading"
    assert members["u_marek"].meta["owner_delegate"] is True
    assert "gpt-4.1-mini" not in agents["trading-copilot@trading"].allowed_models
    tables = b.resources["databases"][0]["tables"]
    customers = next(t for t in tables if t["name"] == "customers")
    assert customers["sensitivity"] == "CONFIDENTIAL"
    assert b.view_as_aliases == {"owner": "u_katarzyna", "admin": "u_emily", "member": "u_piotr"}
    assert b.default_viewer == "u_katarzyna"
    principals = {k.key_id: k.principal for k in b.keys}
    assert principals["key_research_01"] == "agent:research-agent@research"
    assert all(k.expires_at is None or k.expires_at.tzinfo is not None for k in b.keys)


def test_legacy_formats():
    assert map_models(
        [
            "anthropic/claude-sonnet-5-5",
            "ollama/qwen3.5:0.8b",
            "mock/echo-llm",
            "meta-llama/llama-3",
        ]
    ) == ["claude-sonnet-5-5", "qwen3.5:0.8b", "aegis-judge*", "mock-echo", "meta-llama/llama-3"]
    assert map_tool("mcp__acme-db__query") == "acme-db.query"
    assert map_tool("mcp__*__send_*") == "*.send_*"
    assert map_tool("Bash") == "Bash"
    assert seed.map_dest("T0") == "local"
    assert seed.map_dest("T2") == "third_party"
    assert seed.map_dest("remote") == "remote"
