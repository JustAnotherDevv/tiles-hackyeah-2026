"""Claude Code MCP config generator (all MCP traffic through the Aegis gateway).

    python -m aegis.mcp.claude_config [--gateway http://127.0.0.1:8787] [--agent claude-code@platform]
                                      [--servers acme-db,poisoned,rugpull] [--policy config/policy.yaml]
                                      [--out PATH]

HTTP servers → `{"type": "http", "url": "<gw>/mcp/<name>", "headers": {X-Aegis-Agent, Authorization}}`;
stdio servers → the `aegis.mcp.stdio` wrapper launching the registered command.
Use with `claude --mcp-config <file> --strict-mcp-config` so no un-proxied server is loaded.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_AGENT = "claude-code@platform"
DEMO_KEYS = {
    "claude-code@platform": "aegis_demo_cc_platform_0000000000000001_NOT_A_SECRET",
    "research-agent@research": "aegis_demo_research_agent_0000000000000002_NOT_A_SECRET",
    "trading-copilot@trading": "aegis_demo_trading_copilot_0000000000000003_NOT_A_SECRET",
    "chaos-agent@platform": "aegis_demo_chaos_agent_0000000000000004_NOT_A_SECRET",
}
CLAUDE_DEMO_SERVERS = ["acme-db", "acme-crm", "mailer", "web", "weather", "poisoned", "rugpull"]
REPO_ROOT = Path(__file__).resolve().parents[3]


def build_claude_config(
    snap: Any,
    *,
    gateway_url: str = "http://127.0.0.1:8787",
    agent_id: str = DEFAULT_AGENT,
    agent_key: str | None = None,
    servers: list[str] | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """`{"mcpServers": {...}}` for the registered servers (all of them when `servers` is None)."""
    root = Path(repo_root) if repo_root else REPO_ROOT
    gw = gateway_url.rstrip("/")
    registry = dict(getattr(getattr(getattr(snap, "doc", snap), "mcp", None), "servers", {}) or {})
    names = [s for s in (servers or list(registry)) if s in registry]
    key_default = agent_key or DEMO_KEYS.get(agent_id, "")
    out: dict[str, Any] = {}
    for name in names:
        cfg = registry[name]
        if getattr(cfg, "transport", "http") == "stdio":
            python = root / ".venv" / "bin" / "python"
            out[name] = {
                "type": "stdio",
                "command": str(python if python.exists() else "python3"),
                "args": ["-m", "aegis.mcp.stdio", "--server", name, "--gateway", gw, "--agent", agent_id,
                         "--", *list(cfg.command or [])],
                "env": {"PYTHONPATH": f"{root}:{root / 'src'}", "AEGIS_AGENT": agent_id,
                        "AEGIS_AGENT_KEY": key_default},
            }
        else:
            out[name] = {
                "type": "http",
                "url": f"{gw}/mcp/{name}",
                "headers": {"X-Aegis-Agent": agent_id,
                            "Authorization": f"Bearer ${{AEGIS_AGENT_KEY:-{key_default}}}"},
            }
    return {"mcpServers": out}


def _load_snapshot(policy_path: str | None) -> Any:
    """Policy snapshot: the running store if available, else parse the YAML file directly."""
    try:
        from aegis.core.runtime import get_runtime

        return get_runtime().policy.snapshot()
    except Exception:
        pass
    import yaml

    from aegis.core.policy_schema import PolicyDoc

    path = Path(policy_path) if policy_path else REPO_ROOT / "config" / "policy.yaml"
    if not path.exists():
        path = REPO_ROOT / "config" / "snippets" / "mcp-proxy.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    doc = PolicyDoc.model_validate({"mcp": data.get("mcp", {})})
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aegis.mcp.claude_config",
                                 description="Generate a Claude Code --mcp-config routed through Aegis.")
    ap.add_argument("--gateway", default="http://127.0.0.1:8787")
    ap.add_argument("--agent", default=DEFAULT_AGENT)
    ap.add_argument("--key", default=None, help="agent key (default: seed demo key / $AEGIS_AGENT_KEY)")
    ap.add_argument("--servers", default=None, help="comma-separated subset (default: all registered)")
    ap.add_argument("--policy", default=None, help="policy YAML (default config/policy.yaml)")
    ap.add_argument("--out", default=None, help="write to this file instead of stdout")
    ns = ap.parse_args(argv)
    snap = _load_snapshot(ns.policy)
    servers = [s.strip() for s in ns.servers.split(",") if s.strip()] if ns.servers else None
    cfg = build_claude_config(snap, gateway_url=ns.gateway, agent_id=ns.agent, agent_key=ns.key,
                              servers=servers)
    text = json.dumps(cfg, indent=2) + "\n"
    if ns.out:
        Path(ns.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
