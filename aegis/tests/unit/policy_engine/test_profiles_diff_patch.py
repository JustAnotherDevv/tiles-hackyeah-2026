"""POL-04 profiles (V04 matrix), POL-08 diff classification, POL-09 patch applier."""

from __future__ import annotations

import pytest
import yaml

from aegis.policy.diff import diff_docs, primary_kind, summarize
from aegis.policy.patch import PatchError, apply_patch_text
from aegis.policy.profiles import ProfileSet, effective_controls
from aegis.policy.validate import validate_text


def _doc(text: str):
    r = validate_text(text, profiles=ProfileSet.load())
    assert r.ok, r.errors
    return r


# ---------------------------------------------------------------- profiles
@pytest.mark.parametrize(
    ("profile", "inj02", "dlp02", "act01_cap", "exe03"),
    [
        ("permissive", 0.80, "redact", 10000, "log"),
        ("balanced", 0.80, "block", 5000, "require_approval"),
        ("strict", 0.75, "block", 1000, "block"),
        ("paranoid", 0.60, "block", 500, "block"),
    ],
)
def test_profile_matrix(policy_text: str, profile: str, inj02: float, dlp02: str, act01_cap: int, exe03: str) -> None:
    r = _doc(policy_text)
    eff = effective_controls(r.raw, r.doc, profile, ProfileSet.load())
    assert eff["INJ-02"].threshold == pytest.approx(inj02)
    assert eff["DLP-02"].action == dlp02
    assert eff["ACT-01"].params.get("hard_block_above_usd") == act01_cap
    assert eff["EXE-03"].action == exe03


def test_global_monitor_mode(policy_text: str) -> None:
    r = _doc(policy_text.replace("profile: balanced", "profile: balanced", 1))
    raw = dict(r.raw)
    raw["defaults"] = {**(raw.get("defaults") or {}), "mode": "monitor"}
    doc = r.doc.model_copy(update={"defaults": r.doc.defaults.model_copy(update={"mode": "monitor"})})
    eff = effective_controls(raw, doc, "balanced", ProfileSet.load())
    assert all(c.mode in ("monitor", "off") for c in eff.values())


def test_params_deep_merge() -> None:
    ps = ProfileSet.from_dict({"balanced": {"controls": {"DLP-02": {"params": {"a": 1, "b": 2}}}}})
    text = "controls:\n  - id: DLP-02\n    params: {b: 3, c: 4}\n"
    r = validate_text(text, profiles=ps)
    eff = effective_controls(r.raw, r.doc, "balanced", ps)
    assert eff["DLP-02"].params == {"a": 1, "b": 3, "c": 4}


# ---------------------------------------------------------------- diff
def _changes(old: str, new: str):
    return diff_docs(_doc(old).doc, _doc(new).doc)


def test_diff_budget_raise(policy_text: str) -> None:
    new = apply_patch_text(policy_text, [{"op": "set", "path": "budgets.limits[scope=team:trading,window=day].usd",
                                          "value": 75}])
    (ch,) = _changes(policy_text, new)
    assert ch.kind == "budget.raise" and ch.scope == "team:trading" and ch.dimension == "usd"
    assert ch.increase_pct == pytest.approx(25.0) and ch.loosening


def test_diff_disable_control(policy_text: str) -> None:
    new = apply_patch_text(policy_text, [{"op": "set", "path": "controls[id=DLP-02].enabled", "value": False}])
    (ch,) = _changes(policy_text, new)
    assert ch.kind == "control.disable" and ch.loosening and ch.control_id == "DLP-02"
    assert summarize([ch]) and primary_kind([ch]) == "control.disable"


def test_diff_threshold_tighten(policy_text: str) -> None:
    new = apply_patch_text(policy_text, [{"op": "set", "path": "controls[id=INJ-02].threshold", "value": 0.5}])
    (ch,) = _changes(policy_text, new)
    assert ch.kind == "control.threshold.tighten" and not ch.loosening
    assert ch.summary == "INJ-02 threshold 0.80 → 0.50"


def test_diff_matrix_killswitch_profile_model(policy_text: str) -> None:
    new = apply_patch_text(policy_text, [
        {"op": "set", "path": "destinations.matrix.CONFIDENTIAL.remote", "value": "block"},
        {"op": "append", "path": "budgets.kill_switch.agents", "value": "chaos-agent@platform"},
        {"op": "set", "path": "profile", "value": "strict"},
        {"op": "append", "path": "models.allowed", "value": "o3-mini"},
    ])
    kinds = {c.kind: c for c in _changes(policy_text, new)}
    assert kinds["control.action.tighten"].control_id == "DLP-01"
    assert kinds["killswitch.on"].scope == "agent:chaos-agent@platform"
    assert kinds["profile.change"].loosening is False
    assert kinds["model.allow"].loosening is True


# ---------------------------------------------------------------- patch
def test_patch_roundtrip_identity(policy_text: str) -> None:
    assert apply_patch_text(policy_text, []) == policy_text


def test_patch_keeps_comments_and_upserts(policy_text: str) -> None:
    out = apply_patch_text(policy_text, [
        {"op": "set", "path": "budgets.limits[scope=team:newteam,window=day].usd", "value": 10},
        {"op": "set", "path": "controls[id=INJ-02].threshold", "value": 0.5},
    ])
    data = yaml.safe_load(out)
    assert any(lim.get("scope") == "team:newteam" and lim.get("usd") == 10 for lim in data["budgets"]["limits"])
    # every comment line of the original survives
    old_comments = [ln for ln in policy_text.splitlines() if ln.lstrip().startswith("#")]
    new_comments = [ln for ln in out.splitlines() if ln.lstrip().startswith("#")]
    assert old_comments == new_comments
    import difflib

    diff = [ln for ln in difflib.unified_diff(policy_text.splitlines(), out.splitlines(), lineterm="", n=0)
            if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    assert len(diff) <= 3  # one inserted limit line + one replaced threshold line


def test_patch_remove_and_errors(policy_text: str) -> None:
    out = apply_patch_text(policy_text, [{"op": "append", "path": "budgets.kill_switch.agents", "value": "x@y"}])
    out = apply_patch_text(out, [{"op": "remove", "path": "budgets.kill_switch.agents[0]"}])
    assert yaml.safe_load(out)["budgets"]["kill_switch"]["agents"] == []
    with pytest.raises(PatchError):
        apply_patch_text(policy_text, [{"op": "remove", "path": "controls[id=NOPE-99]"}])
