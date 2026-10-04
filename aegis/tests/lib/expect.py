"""Observation × Case → Outcome (plan 18 §2.5).

Outcomes: pass | pass_other | fail | disabled | not_implemented | skip (xfail is assigned by the
plugin for stretch-tier failures).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from tests.lib import macros
from tests.lib.cases import Case
from tests.lib.runner import Observation

ALLOWISH = {"allow", "log"}


@dataclass
class Outcome:
    outcome: str
    reason: str = ""
    got: str | None = None
    got_control: str | None = None
    checks_failed: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.outcome in ("pass", "pass_other")


def control_state(case: Case, controls: dict[str, dict[str, Any]] | None) -> tuple[str | None, str]:
    """→ ('disabled'|'not_implemented'|None, reason) for the expected control(s)."""
    if not controls or not case.controls:
        return None, ""
    for cid in case.controls:
        c = controls.get(cid)
        if c is None:
            return "not_implemented", f"{cid} not in the control registry"
        if c.get("implemented") is False:
            return "not_implemented", f"{cid} is not implemented in this build"
        if c.get("enabled") is False or c.get("mode") == "off":
            return "disabled", f"{cid} is disabled in the loaded policy"
    return None, ""


TRANSPARENT = {"DLP-03"}  # metadata generalisation/header stripping: not a verdict on the content


def _transparent_redact(obs: Observation) -> bool:
    """A benign call whose only 'redact' comes from metadata stripping (no entity redactions)."""
    if obs.action != "redact" or obs.entities:
        return False
    non_allow = {
        d.get("control_id")
        for d in obs.decisions
        if (d.get("mode") or "enforce") == "enforce" and d.get("action") not in ALLOWISH
    }
    return bool(non_allow) and non_allow <= TRANSPARENT


def _action_ok(expect: str, obs: Observation) -> bool:
    got = obs.action
    if expect == "allow":
        return got in ALLOWISH or _transparent_redact(obs)
    if expect == "log":
        return got in ALLOWISH
    if expect == "redact":
        return got == "redact" and (obs.mutations > 0 or bool(obs.entities))
    if expect == "require_approval":
        return got == "require_approval" or bool(obs.approval_id and got not in ALLOWISH)
    if expect == "block":
        return got == "block"
    return False


def _attributed(case: Case, obs: Observation) -> bool:
    ctrls = case.controls
    if not ctrls:
        return True
    if obs.control in ctrls:
        return True
    want = {case.expect} if case.expect != "allow" else ALLOWISH
    if case.expect == "redact":
        if set(ctrls) & set(obs.redaction_controls):
            return True
    for d in obs.decisions:
        if (
            d.get("control_id") in ctrls
            and (d.get("mode") or "enforce") == "enforce"
            and d.get("action") in want
        ):
            return True
    return False


def _checks(case: Case, obs: Observation) -> list[str]:
    bad: list[str] = []
    a = case.assert_
    if case.expect_status is not None and obs.status != case.expect_status:
        bad.append(f"status {obs.status} != {case.expect_status}")
    for ent in case.expect_entities:
        if ent not in obs.entities:
            bad.append(f"entity {ent} not redacted (got {obs.entities})")
    if case.expect_route:
        role, _, extra = case.expect_route.partition("+")
        route = obs.route or {}
        if route:
            if route.get("required_role") != role:
                bad.append(f"route {route.get('required_role')} != {role}")
            if extra == "2p" and not route.get("two_person"):
                bad.append("route not two-person")
        elif case.via != "simulate":
            pass  # route checked via simulate in the matrix (approval detail optional)
    if case.expect_rule and obs.route is not None and obs.route.get("rule_id") != case.expect_rule:
        bad.append(f"rule {obs.route.get('rule_id')} != {case.expect_rule}")
    if case.expect_monitor:
        want_c, want_a = case.expect_monitor.get("control"), case.expect_monitor.get("action")
        if not any(
            d.get("control_id") == want_c
            and (d.get("mode") == "monitor")
            and (want_a is None or d.get("action") == want_a)
            for d in obs.decisions
        ):
            bad.append(f"no monitor decision {want_c}→{want_a}")
    up = "\n".join(obs.upstream_texts) if obs.upstream_texts else (obs.text_out or "")
    for s in a.upstream_must_contain:
        if macros.expand(s) not in up:
            bad.append(f"upstream lacks {s!r}")
    for s in a.upstream_must_not_contain:
        if macros.expand(s) in up:
            bad.append(f"upstream contains {s[:24]!r}…")
    resp = obs.response_text or ""
    for s in a.response_must_contain:
        if macros.expand(s) not in resp:
            bad.append(f"response lacks {s[:24]!r}")
    for s in a.response_must_not_contain:
        if macros.expand(s) in resp:
            bad.append(f"response contains {s[:24]!r}")
    if a.sink_hits is not None and obs.sink_delta is not None and obs.sink_delta != a.sink_hits:
        bad.append(f"sink hits {obs.sink_delta} != {a.sink_hits}")
    if obs.tools_listed is not None:
        for t in a.tool_listed:
            if t not in obs.tools_listed:
                bad.append(f"tool {t} not listed")
        for t in a.tool_not_listed:
            if t in obs.tools_listed:
                bad.append(f"tool {t} still listed")
    return bad


def evaluate(
    case: Case, obs: Observation, controls: dict[str, dict[str, Any]] | None = None
) -> Outcome:
    if obs.skip:
        return Outcome("skip", obs.skip)
    state, why = control_state(case, controls)
    got = obs.action
    if case.expect.startswith("error:"):
        code = int(case.expect.split(":", 1)[1])
        ok = (obs.jsonrpc_code == code) if code < 0 else (obs.status == code)
        checks = _checks(case, obs) if ok else []
        if ok and not checks:
            return Outcome("pass", got=str(obs.jsonrpc_code or obs.status), got_control=obs.control)
        if state:
            return Outcome(state, why, got=str(obs.status), got_control=obs.control)
        return Outcome(
            "fail",
            f"expected {case.expect}, got status={obs.status} rpc={obs.jsonrpc_code}"
            + (f"; {'; '.join(checks)}" if checks else ""),
            got=str(obs.jsonrpc_code or obs.status),
            got_control=obs.control,
            checks_failed=checks,
        )
    if got is None:
        detail = f"status {obs.status}" + (f" {obs.error_type}" if obs.error_type else "")
        if obs.status in (404, 405, 501):
            return Outcome("skip", f"endpoint not available ({detail})")
        if state:
            return Outcome(state, why)
        return Outcome("fail", f"no verdict ({detail}) {obs.reason[:160]}")
    action_ok = _action_ok(case.expect, obs)
    checks = _checks(case, obs)
    if action_ok and not checks:
        if _attributed(case, obs):
            return Outcome("pass", got=got, got_control=obs.control)
        if state and case.column != "benign":
            return Outcome(
                state,
                why + f" (outcome {got} came from {obs.control})",
                got=got,
                got_control=obs.control,
            )
        return Outcome(
            "pass_other",
            f"decided by {obs.control} (expected {'/'.join(case.controls)})",
            got=got,
            got_control=obs.control,
        )
    if state:
        return Outcome(state, why, got=got, got_control=obs.control)
    why_fail = f"expected {case.expect}, got {got}" + (f" by {obs.control}" if obs.control else "")
    if action_ok:
        why_fail = "; ".join(checks)
    elif checks:
        why_fail += "; " + "; ".join(checks)
    if obs.reason and not action_ok:
        why_fail += f" — {obs.reason[:140]}"
    return Outcome("fail", why_fail, got=got, got_control=obs.control, checks_failed=checks)


def describe(obs: Observation) -> str:
    return json.dumps(
        {
            "action": obs.action,
            "control": obs.control,
            "status": obs.status,
            "entities": obs.entities,
            "decision_id": obs.decision_id,
        },
        default=str,
    )


__all__ = ["Outcome", "control_state", "describe", "evaluate"]
