"""GOV-06 "Agent harness integrity (Claude Code)" - control unit tests + handler integration."""

from __future__ import annotations

import json
from typing import Any

import pytest

from aegis.core.policy_schema import ControlConfig
from aegis.core.types import (
    Destination,
    Identity,
    Interaction,
    RequestContext,
    Verdict,
    new_id,
)
from aegis.integrations.claude_code import gov06
from aegis.integrations.claude_code.handler import handle_hook_ex

from .conftest import FakeRuntime, make_snapshot

CTL = gov06.HarnessIntegrity()
SEED_PARAMS: dict[str, Any] = {
    "agents": ["claude-code@*"],
    "protected_paths": ["**/demo/claude/settings*.json", "**/demo/claude/mcp.json",
                        "**/demo/claude/.agent_key", "**/.claude/settings*.json",
                        "**/scripts/aegis-hook"],
    "config_change_keys": ["hooks", "env.ANTHROPIC_BASE_URL", "env.ANTHROPIC_CUSTOM_HEADERS",
                           "permissions.defaultMode", "disableAllHooks"],
    "block_bypass_permissions": False,
    "budget_exhausted_prompt": "block",
}


def cfg(**params: Any) -> ControlConfig:
    return ControlConfig(id="GOV-06", name="Agent harness integrity (Claude Code)", action="block",
                         severity="high", params={**SEED_PARAMS, **params})


def ctx(agent: str = "claude-code@platform") -> RequestContext:
    return RequestContext(request_id=new_id("req"), identity=Identity(agent_id=agent), source="hook")


def tool(name: str, args: dict[str, Any], **cc: Any) -> Interaction:
    return Interaction(kind="tool_call", surface="tool.input",
                       destination=Destination(name=f"local:{name}", dest_class="local"),
                       tool_name=name, tool_args=args,
                       meta={"claude_code": {"raw_tool_name": name, **cc}})


async def test_policy_seed_case_edit_hook_settings_blocked():
    # docs/seed-fixes/policy.yaml GOV-06 test `edit-hook-settings-blocked` (no meta: scope by agent)
    i = Interaction(kind="tool_call", surface="tool.input",
                    destination=Destination(name="local", dest_class="local"), tool_name="Edit",
                    tool_args={"file_path": "/tmp/aegis-demo/demo/claude/settings.json",
                               "old_string": "aegis-hook", "new_string": "true"})
    d = await CTL.evaluate(ctx(), i, cfg())
    assert d is not None and d.action == "block" and d.control_id == "GOV-06"
    assert "protected harness file" in d.reason


@pytest.mark.parametrize("name,args,blocked", [
    ("Write", {"file_path": "/repo/scripts/aegis-hook", "content": "exit 0"}, True),
    ("MultiEdit", {"file_path": "/home/x/.claude/settings.local.json", "edits": []}, True),
    ("Edit", {"file_path": "demo/claude/mcp.json", "old_string": "a", "new_string": "b"}, True),
    ("Edit", {"file_path": "/repo/src/payments/refunds.py", "old_string": "a", "new_string": "b"}, False),
    ("Read", {"file_path": "/repo/demo/claude/settings.json"}, False),
    ("Bash", {"command": "sed -i '' 's/aegis-hook/true/' ../demo/claude/settings.json"}, True),
    ("Bash", {"command": "echo '{}' > /repo/demo/claude/settings.failclosed.json"}, True),
    ("Bash", {"command": "chmod -x /repo/scripts/aegis-hook"}, True),
    ("Bash", {"command": "cat /repo/demo/claude/settings.json"}, False),
    ("Bash", {"command": "rm -rf build/ && ls"}, False),
])
async def test_protected_paths(name, args, blocked):
    d = await CTL.evaluate(ctx(), tool(name, args), cfg())
    assert (d is not None and d.action == "block") is blocked


async def test_scope_other_agents_ignored():
    i = Interaction(kind="tool_call", surface="tool.input",
                    destination=Destination(name="local", dest_class="local"), tool_name="Write",
                    tool_args={"file_path": "/repo/scripts/aegis-hook"})
    assert await CTL.evaluate(ctx("research-agent@research"), i, cfg()) is None
    # ... unless the interaction comes from Claude Code (meta.client)
    i.meta["client"] = "claude-code"
    assert await CTL.evaluate(ctx("research-agent@research"), i, cfg()) is not None


async def test_bypass_mode_only_when_strict():
    i = tool("Bash", {"command": "ls"}, permission_mode="bypassPermissions")
    assert await CTL.evaluate(ctx(), i, cfg()) is None
    d = await CTL.evaluate(ctx(), i, cfg(block_bypass_permissions=True))
    assert d is not None and "bypassPermissions" in d.reason


def _cfg_change(keys: list[str], *, source: str = "project_settings", problem: str | None = None) -> Interaction:
    return Interaction(kind="config_change", surface="config.change",
                       destination=Destination(name="local:claude-code-settings", dest_class="local"),
                       meta={"client": "claude-code", "claude_code": {"hook_event": "ConfigChange"},
                             "config_change": {"source": source, "file": "settings.json",
                                               "changed_keys": keys, "problem": problem}})


async def test_config_change():
    d = await CTL.evaluate(ctx(), _cfg_change(["hooks"]), cfg())
    assert d is not None and d.action == "block" and "hooks" in d.reason
    d = await CTL.evaluate(ctx(), _cfg_change(["env.ANTHROPIC_BASE_URL"]), cfg())
    assert d is not None
    assert await CTL.evaluate(ctx(), _cfg_change(["model"]), cfg()) is None
    assert await CTL.evaluate(ctx(), _cfg_change(["hooks"], source="policy_settings"), cfg()) is None
    d = await CTL.evaluate(ctx(), _cfg_change([], problem="settings file unreadable"), cfg())
    assert d is not None and "unreadable" in d.reason
    # a policy proposal (no meta.config_change) is GOV-05's job
    plain = Interaction(kind="config_change", surface="config.change",
                        destination=Destination(name="local", dest_class="local"))
    assert await CTL.evaluate(ctx(), plain, cfg()) is None


async def test_budget_exhausted_prompt():
    i = Interaction(kind="model_call", surface="prompt.user",
                    destination=Destination(name="anthropic", dest_class="remote"),
                    meta={"claude_code": {"budget_exhausted": {
                        "scope": "agent:claude-code@platform", "state": "hard", "limit": 0.0001,
                        "window": "day", "dimension": "usd"}}})
    d = await CTL.evaluate(ctx(), i, cfg())
    assert d is not None and d.http_status == 402 and d.error_type == "budget_exceeded"
    assert d.meta["response_headers"] == {"x-should-retry": "false"}
    assert await CTL.evaluate(ctx(), i, cfg(budget_exhausted_prompt="allow")) is None


def test_discovered_as_control():
    from aegis.core.discovery import discover_controls

    ids = {c.id for c in discover_controls()}
    assert "GOV-06" in ids


# ---------------------------------------------------------------- handler with GOV-06 active
class Gov06Pipeline:
    """Runs the real GOV-06 control and turns its decision into a verdict."""

    def __init__(self, c: ControlConfig) -> None:
        self.cfg = c
        self.evaluated: list[Interaction] = []
        self.completed: list[Any] = []

    def new_context(self, **kw: Any) -> RequestContext:
        return RequestContext(request_id=new_id("req"), session_id=kw.get("session_id") or "d",
                              identity=kw["identity"], source="hook")

    async def evaluate(self, ctx: RequestContext, i: Interaction, **_: Any) -> Verdict:
        self.evaluated.append(i)
        d = await CTL.evaluate(ctx, i, self.cfg)
        if d is not None:
            d.meta.setdefault("response_headers", {})["x-aegis-test"] = "1"
        return Verdict(id=new_id("dec"), request_id=ctx.request_id, interaction_id=i.id,
                       action=d.action if d else "allow", primary=d,  # type: ignore[arg-type]
                       decisions=[d] if d else [], policy_version=7)

    async def complete(self, ctx: Any, i: Any, v: Any, o: Any) -> None:
        self.completed.append((i, v, o))


@pytest.fixture
def rt6() -> FakeRuntime:
    c = cfg()
    rt = FakeRuntime(make_snapshot(gov06={"params": c.params}))
    rt.pipeline = Gov06Pipeline(c)  # type: ignore[assignment]
    rt.controls = _Controls()  # type: ignore[assignment]
    return rt


class _Controls:
    def get(self, control_id: str) -> Any:
        return CTL if control_id == "GOV-06" else None


HDR = {"x-aegis-agent": "claude-code@platform", "x-aegis-hook-deadline": "110"}


async def test_handler_config_change_is_a_gov06_decision(rt6, tmp_path):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"hooks": {}, "model": "haiku"}))
    body = {"hook_event_name": "ConfigChange", "session_id": "s9", "source": "project_settings",
            "file_path": str(f)}
    out, headers = await handle_hook_ex(rt6, json.dumps(body).encode(), HDR, "http://gw")
    assert out["decision"] == "block" and out["reason"].startswith("[Aegis] GOV-06: ")
    assert headers["x-aegis-decision-id"].startswith("dec") and headers["x-aegis-test"] == "1"
    it = rt6.pipeline.evaluated[-1]
    assert it.surface == "config.change" and it.meta["config_change"]["changed_keys"] == ["hooks"]
    assert len(rt6.pipeline.completed) == 1


async def test_handler_edit_settings_denied_via_pipeline(rt6):
    body = {"hook_event_name": "PreToolUse", "session_id": "s9", "tool_name": "Edit",
            "tool_use_id": "t1", "cwd": "/repo/demo/claude/project",
            "tool_input": {"file_path": "/repo/demo/claude/settings.json",
                           "old_string": "aegis-hook", "new_string": "true"}}
    out, headers = await handle_hook_ex(rt6, json.dumps(body).encode(), HDR, "http://gw")
    h = out["hookSpecificOutput"]
    assert h["permissionDecision"] == "deny"
    assert h["permissionDecisionReason"].startswith("[Aegis] GOV-06: Blocked by Agent harness integrity")
    assert "x-aegis-decision-id" in headers


async def test_handler_budget_prompt_via_gov06(rt6):
    from aegis.core.types import BudgetStatus

    rt6.policy.snap.controls["BUD-01"].mode = "enforce"
    rt6.ledger.statuses["agent:claude-code@platform"] = [BudgetStatus(
        scope="agent:claude-code@platform", scope_type="agent", dimension="usd", window="day",
        limit=0.0001, used=0.02, pct=200.0, state="hard")]
    body = {"hook_event_name": "UserPromptSubmit", "session_id": "s9", "prompt": "hi"}
    out, headers = await handle_hook_ex(rt6, json.dumps(body).encode(), HDR, "http://gw")
    assert out["decision"] == "block"
    assert out["reason"].startswith("[Aegis] GOV-06: Budget exhausted for agent:claude-code@platform")
    assert headers.get("x-should-retry") == "false"
