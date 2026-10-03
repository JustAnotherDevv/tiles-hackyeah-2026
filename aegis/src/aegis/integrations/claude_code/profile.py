"""Claude Code demo profile generator (never machine-wide settings).

    uv run --frozen python -m aegis.integrations.claude_code.profile \
        [--gateway-url http://127.0.0.1:8787] [--out demo/claude] \
        [--variant all|demo|failclosed|hardened] [--if-stale] [--check] [--print-managed]

Writes (only under --out): settings.json (demo), settings.failclosed.json (hooks -> dead port,
model traffic still flows so Claude can explain the denial), settings.hardened.json (permission
backstops + disableBypassPermissionsMode), mcp.json (every policy MCP server via the Aegis MCP
proxy) and .agent_key (mode 600, the seed demo key). It refuses any path outside --out and never
touches ~/.claude, /Library/Application Support/ClaudeCode or a project's .claude/ directory; the
managed-settings equivalent is printed as text only (--print-managed).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
HOOK_SCRIPT = ROOT / "scripts" / "aegis-hook"
DEFAULT_OUT = ROOT / "demo" / "claude"
DEFAULT_GATEWAY = "http://127.0.0.1:8787"
DEAD_GATEWAY = "http://127.0.0.1:1"
AGENT_ID = "claude-code@platform"
TEAM_ID = "platform"
DEMO_KEY = "aegis_demo_cc_platform_0000000000000001_NOT_A_SECRET"

#: settings `timeout` (s) per event, curl --max-time is 110 (blocking) / 10 (fast)
BLOCKING_TIMEOUT = 120
FAST_TIMEOUT = 15
CURL_BLOCKING = 110
CURL_FAST = 10
HOLD_MAX = 60

#: (event, matcher, blocking)
HOOK_EVENTS: list[tuple[str, str | None, bool]] = [
    ("SessionStart", None, False),
    ("UserPromptSubmit", None, True),
    ("PreToolUse", "*", True),
    ("PostToolUse", "*", False),
    ("PostToolUseFailure", "*", False),
    ("ConfigChange", None, True),
    ("Stop", None, False),
    ("SessionEnd", None, False),
]

#: CONTRACTS section 4.3 fallback when config/policy.yaml cannot be parsed
FALLBACK_MCP_SERVERS = [
    "acme-db", "acme-crm", "marketpulse", "payments", "mailer", "web", "weather", "poisoned",
    "rugpull",
]

FORBIDDEN_PARTS = (
    "/Library/Application Support/ClaudeCode",
    "/etc/claude-code",
)


class ProfileError(RuntimeError):
    pass


# ---------------------------------------------------------------- building blocks
def hook_command(event: str, blocking: bool, *, gateway_url: str, script: Path = HOOK_SCRIPT) -> str:
    """Shell command Claude Code runs for an event. Blocking events are guarded with
    `|| exit 2` so a missing/crashing script still BLOCKS (exit 127 would fail open)."""
    cmd = f"AEGIS_URL={shlex.quote(gateway_url)} /bin/bash {shlex.quote(str(script))} {event}"
    return f"{cmd} || exit 2" if blocking else cmd


def build_hooks(gateway_url: str, script: Path = HOOK_SCRIPT) -> dict[str, Any]:
    hooks: dict[str, Any] = {}
    for event, matcher, blocking in HOOK_EVENTS:
        entry: dict[str, Any] = {}
        if matcher is not None:
            entry["matcher"] = matcher
        entry["hooks"] = [{
            "type": "command",
            "command": hook_command(event, blocking, gateway_url=gateway_url, script=script),
            "timeout": BLOCKING_TIMEOUT if blocking else FAST_TIMEOUT,
        }]
        hooks[event] = [entry]
    return hooks


def _abs_rule(path: Path) -> str:
    """Permission-rule path syntax: `//abs/path` = absolute filesystem path."""
    return "/" + str(path)


def build_settings(
    variant: str,
    *,
    gateway_url: str,
    out_dir: Path,
    script: Path = HOOK_SCRIPT,
) -> dict[str, Any]:
    if variant not in ("demo", "failclosed", "hardened"):
        raise ProfileError(f"unknown variant {variant!r}")
    hook_url = DEAD_GATEWAY if variant == "failclosed" else gateway_url
    key_file = out_dir / ".agent_key"
    env = {
        "ANTHROPIC_BASE_URL": gateway_url,
        "ANTHROPIC_CUSTOM_HEADERS": (
            f"X-Aegis-Agent: {AGENT_ID}\nX-Aegis-Team: {TEAM_ID}\nX-Aegis-Agent-Key: {DEMO_KEY}"
        ),
        "CLAUDE_CODE_GATEWAY_HINT_HEADERS": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "AEGIS_URL": hook_url,
        "AEGIS_AGENT": AGENT_ID,
        "AEGIS_AGENT_KEY_FILE": str(key_file),
        "AEGIS_HOOK_TIMEOUT": str(CURL_BLOCKING),
        "AEGIS_HOOK_TIMEOUT_FAST": str(CURL_FAST),
    }
    guarded = [out_dir / n for n in ("settings.json", "settings.failclosed.json",
                                     "settings.hardened.json", "mcp.json")]
    deny = ["Read(~/.ssh/**)", "Read(~/.aws/**)", f"Read({_abs_rule(key_file)})"]
    for p in [*guarded, key_file, script]:
        # Edit(...) rules cover every file-editing tool (Write too); Claude Code 2.1 warns on Write(...) rules
        deny += [f"Edit({_abs_rule(p)})"]
    permissions: dict[str, Any] = {"defaultMode": "default", "deny": deny}
    if variant == "hardened":
        permissions["deny"] = [
            *deny, "Read(**/.env)", "Read(**/.env.*)", "Bash(curl * | sh)", "Bash(curl * | bash)",
            "Bash(wget * | sh)", "WebFetch",
        ]
        permissions["disableBypassPermissionsMode"] = "disable"
    return {
        "$schema": "https://json.schemastore.org/claude-code-settings.json",
        "env": env,
        "permissions": permissions,
        "hooks": build_hooks(hook_url, script),
    }


def mcp_server_names(policy_path: Path | None = None) -> list[str]:
    path = policy_path or Path(os.environ.get("AEGIS_POLICY") or ROOT / "config" / "policy.yaml")
    if not path.is_absolute():
        path = ROOT / path
    try:
        import yaml

        from aegis.core.policy_schema import PolicyDoc

        doc = PolicyDoc.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        names = list(doc.mcp.servers)
        if names:
            return names
    except Exception:
        pass
    return list(FALLBACK_MCP_SERVERS)


def build_mcp(gateway_url: str, names: list[str]) -> dict[str, Any]:
    return {
        "mcpServers": {
            n: {
                "type": "http",
                "url": f"{gateway_url.rstrip('/')}/mcp/{n}",
                "headers": {"X-Aegis-Agent": AGENT_ID, "Authorization": f"Bearer {DEMO_KEY}"},
            }
            for n in names
        }
    }


def managed_settings_text(gateway_url: str) -> str:
    """Managed-settings equivalent, for the README only (never written by this tool)."""
    doc = {
        "env": {"ANTHROPIC_BASE_URL": gateway_url, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
        "allowManagedHooksOnly": True,
        "permissions": {"disableBypassPermissionsMode": "disable"},
        "hooks": build_hooks(gateway_url, Path("/opt/aegis/bin/aegis-hook")),
    }
    return (
        "# /Library/Application Support/ClaudeCode/managed-settings.json (macOS, admin-deployed)\n"
        "# NOT written by Aegis - shown for production rollout planning only.\n"
        + json.dumps(doc, indent=2)
    )


# ---------------------------------------------------------------- safety + writing
def _check_out_dir(out_dir: Path) -> Path:
    out = out_dir.resolve()
    s = str(out)
    home_claude = (Path.home() / ".claude").resolve()
    if out == home_claude or home_claude in out.parents:
        raise ProfileError(f"refusing to write under {home_claude}")
    if any(part in s for part in FORBIDDEN_PARTS):
        raise ProfileError(f"refusing to write managed-settings paths ({s})")
    if out.name == ".claude" or ".claude" in out.parts:
        raise ProfileError("refusing to write into a .claude/ directory")
    return out


def _confined(out: Path, name: str) -> Path:
    target = (out / name).resolve()
    if target.parent != out:
        raise ProfileError(f"refusing to write outside {out}: {target}")
    return target


def render(gateway_url: str, out_dir: Path, variants: list[str],
           policy_path: Path | None = None) -> dict[str, str]:
    """{file name: content} for the requested variants (pure)."""
    files: dict[str, str] = {}
    names = {"demo": "settings.json", "failclosed": "settings.failclosed.json",
             "hardened": "settings.hardened.json"}
    for v in variants:
        files[names[v]] = json.dumps(build_settings(v, gateway_url=gateway_url, out_dir=out_dir),
                                     indent=2) + "\n"
    files["mcp.json"] = json.dumps(build_mcp(gateway_url, mcp_server_names(policy_path)),
                                   indent=2) + "\n"
    files[".agent_key"] = DEMO_KEY + "\n"
    return files


def write_profile(
    out_dir: Path,
    *,
    gateway_url: str = DEFAULT_GATEWAY,
    variants: list[str] | None = None,
    if_stale: bool = False,
    policy_path: Path | None = None,
) -> list[Path]:
    """Write the profile files; returns the paths actually (re)written."""
    out = _check_out_dir(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, content in render(gateway_url, out, variants or ["demo", "failclosed", "hardened"],
                                policy_path).items():
        target = _confined(out, name)
        if if_stale and target.exists():
            try:
                if target.read_text(encoding="utf-8") == content:
                    continue
            except OSError:
                pass
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        if name == ".agent_key":
            os.chmod(tmp, 0o600)
        os.replace(tmp, target)
        written.append(target)
    return written


def check_profile(out_dir: Path, *, gateway_url: str = DEFAULT_GATEWAY) -> list[str]:
    """Problems with the generated profile ([] = OK)."""
    problems: list[str] = []
    out = out_dir.resolve()
    for name, expect_url in (("settings.json", gateway_url),
                             ("settings.failclosed.json", DEAD_GATEWAY),
                             ("settings.hardened.json", gateway_url)):
        path = out / name
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{name}: unreadable or invalid JSON ({type(exc).__name__})")
            continue
        env = doc.get("env", {})
        if env.get("ANTHROPIC_BASE_URL") != gateway_url:
            problems.append(f"{name}: ANTHROPIC_BASE_URL != {gateway_url}")
        if env.get("AEGIS_URL") != expect_url:
            problems.append(f"{name}: AEGIS_URL != {expect_url}")
        if doc.get("disableAllHooks"):
            problems.append(f"{name}: disableAllHooks is set")
        hooks = doc.get("hooks", {})
        for event, _matcher, blocking in HOOK_EVENTS:
            entries = hooks.get(event) or []
            cmds = [h for e in entries for h in e.get("hooks", [])]
            if not cmds:
                problems.append(f"{name}: no {event} hook")
                continue
            for h in cmds:
                cmd, timeout = h.get("command", ""), int(h.get("timeout", 0))
                if str(HOOK_SCRIPT) not in cmd:
                    problems.append(f"{name}: {event} hook does not call {HOOK_SCRIPT}")
                if blocking and not cmd.rstrip().endswith("|| exit 2"):
                    problems.append(f"{name}: {event} hook is not guarded with '|| exit 2'")
                curl = int(env.get("AEGIS_HOOK_TIMEOUT" if blocking else "AEGIS_HOOK_TIMEOUT_FAST",
                                   CURL_BLOCKING if blocking else CURL_FAST))
                if not timeout > curl:
                    problems.append(f"{name}: {event} settings timeout {timeout} <= curl {curl}")
                if blocking and not curl > HOLD_MAX:
                    problems.append(f"{name}: curl timeout {curl} <= approval hold {HOLD_MAX}")
    if not HOOK_SCRIPT.exists():
        problems.append(f"hook script missing: {HOOK_SCRIPT}")
    elif not os.access(HOOK_SCRIPT, os.X_OK):
        problems.append(f"hook script not executable: {HOOK_SCRIPT}")
    try:
        mcp = json.loads((out / "mcp.json").read_text(encoding="utf-8"))
        for n, s in mcp.get("mcpServers", {}).items():
            if s.get("url") != f"{gateway_url.rstrip('/')}/mcp/{n}":
                problems.append(f"mcp.json: {n} does not go through {gateway_url}/mcp/{n}")
    except (OSError, ValueError):
        problems.append("mcp.json: unreadable or invalid JSON")
    key = out / ".agent_key"
    if not key.exists():
        problems.append(".agent_key missing")
    elif key.stat().st_mode & 0o077:
        problems.append(".agent_key is readable by group/others (want 600)")
    return problems


# ---------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aegis.integrations.claude_code.profile",
                                 description=__doc__.split("\n\n")[0])
    ap.add_argument("--gateway-url", default=os.environ.get("AEGIS_URL", DEFAULT_GATEWAY))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--variant", default="all", choices=["all", "demo", "failclosed", "hardened"])
    ap.add_argument("--if-stale", action="store_true", help="only rewrite files whose content changed")
    ap.add_argument("--check", action="store_true", help="validate the profile (writes nothing)")
    ap.add_argument("--print-managed", action="store_true", help="print managed-settings text only")
    args = ap.parse_args(argv)
    gw = args.gateway_url.rstrip("/")
    out = Path(args.out)
    if args.print_managed:
        print(managed_settings_text(gw))
        return 0
    try:
        if args.check:
            problems = check_profile(out, gateway_url=gw)
            for p in problems:
                print(f"FAIL {p}")
            print("profile OK" if not problems else f"profile has {len(problems)} problem(s)")
            return 0 if not problems else 1
        variants = ["demo", "failclosed", "hardened"] if args.variant == "all" else [args.variant]
        written = write_profile(out, gateway_url=gw, variants=variants, if_stale=args.if_stale)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for p in written:
        print(f"wrote {p}")
    if not written:
        print("profile up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
