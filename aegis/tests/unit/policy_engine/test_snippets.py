"""POL-16 snippet merge: keyed lists, ordered insertion, [SF-..] protection, comments kept, idempotent, CLI."""

from __future__ import annotations

from pathlib import Path

import yaml

from aegis.policy.snippets import main, merge_text

POLICY = """\
# top comment
version: 1
profile: balanced
approvals:
  rules:
    - {id: r1, when: {kind: [action]}, approver: admin}
    - {id: r3, when: {kind: [action]}, approver: owner}
controls:
  - id: DLP-02
    name: Secrets
    severity: critical                  # [SF-18]
    params: {entropy_min: 4.0}
    tests:
      - {name: t1, text: "hello", expect: allow, control: DLP-02}

  - id: INJ-02
    threshold: 0.8                      # keep me
budgets:
  limits:
    - {scope: "team:trading", window: day, usd: 60}
"""

SNIPPET = {
    "approvals": {"rules": [{"id": "r1", "when": {"kind": ["action"]}, "approver": "admin"},
                            {"id": "r2", "when": {"kind": ["action"]}, "approver": "self"},
                            {"id": "r3", "when": {"kind": ["action"]}, "approver": "owner"}]},
    "controls": [
        {"id": "DLP-02", "severity": "low", "params": {"min_len": 20, "entropy_min": 4.5},
         "tests": [{"name": "t2", "text": "x", "expect": "allow", "control": "DLP-02"}]},
        {"id": "BUD-01", "name": "Budgets", "params": {"a": 1}},
    ],
    "budgets": {"limits": [{"scope": "team:trading", "window": "day", "usd": 75},
                           {"scope": "team:research", "window": "day", "usd": 20}]},
    "profiles": {"strict": {}},
}


def test_merge_rules() -> None:
    res = merge_text(POLICY, [("x.yaml", SNIPPET)])
    assert res.errors == []
    data = yaml.safe_load(res.text)
    assert [r["id"] for r in data["approvals"]["rules"]] == ["r1", "r2", "r3"]  # ordered insertion
    dlp = data["controls"][0]
    assert dlp["severity"] == "critical"  # [SF-..] value kept
    assert dlp["params"] == {"entropy_min": 4.5, "min_len": 20}  # snippet wins, deep merge
    assert [t["name"] for t in dlp["tests"]] == ["t1", "t2"]
    assert [c["id"] for c in data["controls"]] == ["DLP-02", "BUD-01", "INJ-02"]
    lims = {(x["scope"], x["window"]): x["usd"] for x in data["budgets"]["limits"]}
    assert lims == {("team:trading", "day"): 75, ("team:research", "day"): 20}
    assert "profiles" not in data
    assert "# top comment" in res.text and "# keep me" in res.text and "# [SF-18]" in res.text
    kinds = {i.kind for i in res.items}
    assert {"add", "set", "kept", "skipped"} <= kinds
    # idempotent
    again = merge_text(res.text, [("x.yaml", SNIPPET)])
    assert again.text == res.text and again.changed == 0


def test_conflict_between_snippets() -> None:
    a = {"controls": [{"id": "INJ-02", "threshold": 0.7}]}
    b = {"controls": [{"id": "INJ-02", "threshold": 0.6}]}
    res = merge_text(POLICY, [("a.yaml", a), ("b.yaml", b)])
    assert yaml.safe_load(res.text)["controls"][1]["threshold"] == 0.6
    assert any(i.kind == "conflict" and i.snippet == "b.yaml" for i in res.items)


def test_cli_merge_writes_policy_and_golden(tmp_path: Path, policy_dir: Path) -> None:
    snips = tmp_path / "snips"
    snips.mkdir()
    (snips / "x.yaml").write_text("controls:\n  - id: INJ-04\n    params: {overlap_threshold: 0.3}\n",
                                  encoding="utf-8")
    pol = policy_dir / "policy.yaml"
    assert main(["check", "--policy", str(pol), "--snippets", str(snips)]) == 0
    assert "overlap_threshold: 0.3" not in pol.read_text()
    assert main(["merge", "--policy", str(pol), "--snippets", str(snips)]) == 0
    text = pol.read_text()
    assert (policy_dir / "policy.golden.yaml").read_text() == text
    inj = next(c for c in yaml.safe_load(text)["controls"] if c["id"] == "INJ-04")
    assert inj["params"]["overlap_threshold"] == 0.3
