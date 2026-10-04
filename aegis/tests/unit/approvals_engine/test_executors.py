"""APR-V05: executors apply approved config changes (fallback layer, registration order,
failures, stale YAML)."""

from __future__ import annotations

from aegis.core.types import ApprovalDraft

PATCH = [{"op": "set", "path": "budgets.limits[scope=team:trading,window=day].usd", "value": 75}]
CHANGE = {"kind": "budget.raise", "path": "budgets.limits[scope=team:trading,window=day].usd",
          "scope": "team:trading", "dimension": "usd", "before": 60, "after": 75,
          "increase_pct": 25, "loosening": True}


def _draft(proposal: dict) -> ApprovalDraft:
    return ApprovalDraft(kind="config_change", action_type="budget.raise",
                         title="Piotr Zieliński wants to raise team:trading day usd 60 → 75 (+25%)",
                         resource="policy:0123456789abcdef",
                         payload={"changes": [CHANGE], "proposal": proposal})


async def test_fallback_applies_patch(svc, h, fake_rt) -> None:
    req = await svc.create_manual(h.member("u_piotr"), _draft({"patch": PATCH, "base_version": 1}))
    assert (req.status, req.required_role, req.rule_id) == ("pending", "admin", "raise-team-small")
    done = await svc.vote(req.id, h.member("u_emily"), "approve")
    assert done.execution["status"] == "applied"
    assert done.execution["policy_version"] == 2 and done.execution["previous_version"] == 1
    assert len(fake_rt.policy.calls) == 1
    call = fake_rt.policy.calls[0]
    assert call["op"] == "patch" and call["source"] == "approval"
    assert call["actor"].member_id == "u_emily" and req.id in call["reason"]
    assert fake_rt.audit.of("approval.executed")


async def test_registered_executor_wins_regardless_of_order(svc, h, fake_rt) -> None:
    calls = []

    async def policy_engine_exec(req):
        calls.append(req.id)
        return {"status": "applied", "policy_version": 42}

    svc.register_executor("config_change", policy_engine_exec)
    req = await svc.create_manual(h.member("u_piotr"), _draft({"patch": PATCH}))
    done = await svc.vote(req.id, h.member("u_emily"), "approve")
    assert calls == [req.id] and done.execution["policy_version"] == 42
    assert fake_rt.policy.calls == []


async def test_executor_failure_keeps_approved_and_warns(svc, h, fake_rt) -> None:
    async def broken(req):
        raise RuntimeError("selector vanished")

    svc.register_executor("config_change", broken)
    req = await svc.create_manual(h.member("u_piotr"), _draft({"patch": PATCH}))
    done = await svc.vote(req.id, h.member("u_emily"), "approve")
    assert done.status == "approved" and done.execution["status"] == "error"
    assert "selector vanished" in done.execution["message"]
    warnings = fake_rt.bus.events("system")
    assert any("could not be applied" in w["message"] for w in warnings)
    executed = fake_rt.audit.of("approval.executed")
    assert executed and executed[-1].data["ok"] is False


async def test_stale_yaml_conflict(svc, h, fake_rt) -> None:
    req = await svc.create_manual(h.member("u_piotr"),
                                  _draft({"yaml": "version: 1\n", "base_version": 0}))
    done = await svc.vote(req.id, h.member("u_emily"), "approve")
    assert done.execution["status"] == "conflict"
    assert fake_rt.policy.calls == []


async def test_current_yaml_applied(svc, h, fake_rt) -> None:
    req = await svc.create_manual(h.member("u_piotr"),
                                  _draft({"yaml": "version: 1\n", "base_version": 1}))
    done = await svc.vote(req.id, h.member("u_emily"), "approve")
    assert done.execution["status"] == "applied"
    assert fake_rt.policy.calls[0]["op"] == "yaml"


async def test_mcp_pin_without_executor(svc, h, fake_rt) -> None:
    draft = ApprovalDraft(kind="mcp_pin", action_type="mcp.repin",
                          title="Re-approve changed MCP tool rugpull.get_exchange_rate",
                          resource="mcp:rugpull.get_exchange_rate",
                          labels={"dest": "third_party", "server": "rugpull", "reason": "changed"},
                          payload={"server": "rugpull", "tool": "get_exchange_rate",
                                   "new_hash": "ab" * 32})
    req = await svc.create_manual(h.agent("claude-code@platform"), draft)
    assert req.rule_id == "mcp-repin"
    assert not svc.can_approve(h.member("u_tomasz"), req)[0]
    done = await svc.vote(req.id, h.member("u_marek"), "approve")
    assert done.execution["status"] == "no_executor"


async def test_auto_manual_runs_executor(svc, h, fake_rt) -> None:
    change = {"kind": "control.enable", "path": "controls[id=INJ-03].enabled",
              "control_id": "INJ-03", "before": False, "after": True}
    draft = ApprovalDraft(kind="config_change", action_type="control.enable", title="enable INJ-03",
                          payload={"changes": [change],
                                   "proposal": {"patch": [{"op": "set",
                                                           "path": "controls[id=INJ-03].enabled",
                                                           "value": True}]}})
    req = await svc.create_manual(h.member("u_olivia"), draft)
    assert (req.status, req.required_role) == ("approved", "auto")
    assert req.execution["status"] == "applied" and req.uses == req.max_uses
