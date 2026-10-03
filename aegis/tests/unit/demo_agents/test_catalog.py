"""DEMO-10 catalog invariants + grading + YAML helpers + hook parsing (pure, no network)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from demo.agents import catalog as cat
from demo.agents.catalog import Outcome, Step

ROOT = Path(__file__).resolve().parents[3]
FAMILIES_REQUIRED = {"DLP", "INJ", "EXE", "ACT", "GOV", "BUD", "MCP", "SIG"}


def _policy_control_ids() -> set[str]:
    doc = yaml.safe_load((ROOT / "config" / "policy.yaml").read_text())
    return {c["id"] for c in doc["controls"]}


def test_step_ids_unique() -> None:
    ids = [s.id for s in [*cat.STEPS, cat.KILL_STEP]]
    assert len(ids) == len(set(ids))
    assert set(cat.STEPS_BY_ID) == set(ids)


def test_every_expected_control_exists_in_policy() -> None:
    known = _policy_control_ids()
    for s in cat.STEPS:
        for c in s.controls:
            assert c in known, f"{s.id}: {c} not in config/policy.yaml controls"


def test_every_control_family_and_approval_kind_covered() -> None:
    fams = {c.split("-")[0] for s in cat.STEPS for c in s.controls}
    assert FAMILIES_REQUIRED <= fams
    kinds = {s.kind for s in cat.STEPS if s.kind}
    assert set(cat.APPROVAL_KINDS) <= kinds
    assert {s.family for s in cat.STEPS} <= set(cat.FAMILIES)


def test_expectations_are_valid_actions() -> None:
    valid = {"allow", "log", "redact", "block", "require_approval", "killed", "budget_exceeded",
             "rate_limited"}
    for s in [*cat.STEPS, cat.KILL_STEP]:
        assert s.expect and set(s.expect) <= valid, s.id
        if s.role:
            assert s.role in {"self", "admin", "owner"}
            assert "require_approval" in s.expect


def test_ordering_puts_burners_last_and_content_first() -> None:
    order = cat.ordered(list(cat.STEPS))
    assert order[-1].burner
    assert order[0].family in ("benign", "injection")


def test_ambient_pool_is_safe() -> None:
    for s in cat.STEPS:
        if s.weight > 0:
            assert not s.mutates and not s.burner, s.id
    benign = sum(s.weight for s in cat.STEPS if set(s.expect) & {"allow", "log"})
    total = sum(s.weight for s in cat.STEPS)
    assert benign / total > 0.5  # benign-heavy mix


def test_grade() -> None:
    s = Step("x", "spend", "t", lambda ctx: Outcome("allow"), ("require_approval",), ("ACT-01",),
             role="admin")
    assert cat.grade(s, Outcome("require_approval", "ACT-01", role="admin")) == "✓"
    assert cat.grade(s, Outcome("require_approval", "ACT-02", role="admin")) == "≈"
    assert cat.grade(s, Outcome("require_approval", "ACT-01", role="owner")) == "≈"
    assert cat.grade(s, Outcome("block", "ACT-01")) == "✗"
    assert cat.grade(s, Outcome("skip", skipped="mock_mcp unavailable")) == "·"
    two = Step("y", "spend", "t", lambda ctx: Outcome("allow"), ("require_approval",),
               ("ACT-01",), role="owner", two_person=True)
    assert cat.grade(two, Outcome("require_approval", "ACT-01", role="owner")) == "≈"
    assert cat.grade(two, Outcome("require_approval", "ACT-01", role="owner", two_person=True)) == "✓"


def test_set_control_key_on_real_policy() -> None:
    text = (ROOT / "config" / "policy.yaml").read_text()
    out = cat.set_control_key(text, "INJ-02", "threshold", "0.55")
    doc = yaml.safe_load(out)
    inj02 = next(c for c in doc["controls"] if c["id"] == "INJ-02")
    assert inj02["threshold"] == 0.55
    off = yaml.safe_load(cat.disable_control_yaml(text, "DLP-02"))
    assert next(c for c in off["controls"] if c["id"] == "DLP-02")["enabled"] is False
    # nothing else changed
    assert len(out.splitlines()) == len(text.splitlines())


def test_disable_inserts_when_missing() -> None:
    y = "controls:\n  - id: A-01\n    action: log\n  - id: DLP-02\n    action: block\n"
    out = yaml.safe_load(cat.disable_control_yaml(y, "DLP-02"))
    assert out["controls"][1] == {"id": "DLP-02", "enabled": False, "action": "block"}
    assert out["controls"][0] == {"id": "A-01", "action": "log"}


def test_parse_hook_output_shapes() -> None:
    deny = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": "[Aegis] EXE-01: Blocked: pipe"}}
    o = cat.parse_hook_output(deny)
    assert (o.action, o.control) == ("block", "EXE-01")
    pend = {"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason":
            "[Aegis] ACT-04: Approval apr_0123456789abcdef0123456789 pending (needs admin)"}}
    o = cat.parse_hook_output(pend)
    assert (o.action, o.control, o.approval_id) == ("require_approval", "ACT-04",
                                                    "apr_0123456789abcdef0123456789")
    post = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext":
            "Aegis: untrusted content in this tool output was neutralised (INJ-01)"}}
    o = cat.parse_hook_output(post)
    assert (o.action, o.control) == ("redact", "INJ-01")
    assert cat.parse_hook_output({}).action == "allow"


def test_generated_secrets_are_runtime_only() -> None:
    import random

    k = cat.fake_aws_key(random.Random(1))
    assert re.fullmatch(r"(AKIA|ASIA)[A-Z0-9]{16}", k)
    src = (ROOT / "demo" / "agents" / "catalog.py").read_text()
    assert not re.search(r"AKIA[A-Z0-9]{16}", src)
    assert len(cat.tag_smuggle("hi")) == 2 and all(ord(c) >= 0xE0000 for c in cat.tag_smuggle("hi"))
