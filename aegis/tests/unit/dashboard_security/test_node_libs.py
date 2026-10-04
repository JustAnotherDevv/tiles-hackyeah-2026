"""Runs the dashboard's pure-lib node tests from pytest, so `make test` covers the frontend libs.

* Every `tests/unit/dashboard_*/*.test.mjs` runs with Node's built-in runner (`node --test <file>`):
  no browser, no `npm install`, no network. The libs are type-only-import TypeScript that Node
  loads directly when it can strip types (Node >= 23.6, or 22.18+); otherwise the tests skip with
  a reason (the README minimum, Node 20.19 / 22.12, is enough to *build* the dashboard).
* One cross-language check: the policy editor's text quick edits (`yaml-text.ts`) must produce YAML
  that the server's parser (PyYAML) reads back with the intended value.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
NODE = shutil.which("node")
NODE_TESTS = sorted((ROOT / "tests" / "unit").glob("dashboard_*/*.test.mjs"))
TIMEOUT_S = 120


def _type_stripping(tmp: Path) -> str | None:
    """None when this node can import a .ts module; otherwise the skip reason."""
    if NODE is None:
        return "node not on PATH (needed only for the dashboard lib tests)"
    probe = tmp / "probe.ts"
    probe.write_text("export const answer: number = 42;\n", encoding="utf-8")
    code = f"const m = await import({json.dumps(probe.as_uri())}); if (m.answer !== 42) process.exit(3);"
    try:
        r = subprocess.run(
            [NODE, "--input-type=module", "-e", code],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"node probe failed: {exc}"
    if r.returncode != 0:
        version = subprocess.run([NODE, "--version"], capture_output=True, text=True, check=False).stdout.strip()
        return f"node {version} cannot strip TypeScript types (needs >= 23.6 or 22.18)"
    return None


@pytest.fixture(scope="module")
def node(tmp_path_factory: pytest.TempPathFactory) -> str:
    reason = _type_stripping(tmp_path_factory.mktemp("node_probe"))
    if reason:
        pytest.skip(reason)
    assert NODE is not None
    return NODE


def test_node_test_files_present() -> None:
    names = {p.relative_to(ROOT / "tests" / "unit").as_posix() for p in NODE_TESTS}
    assert {"dashboard_security/lib.test.mjs", "dashboard_governance/lib.test.mjs"} <= names, names


@pytest.mark.parametrize("path", NODE_TESTS, ids=[p.parent.name for p in NODE_TESTS])
def test_node_lib_suite(node: str, path: Path) -> None:
    r = subprocess.run(
        [node, "--test", "--test-reporter=tap", str(path)],
        cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT_S, check=False,
    )
    out = r.stdout + r.stderr
    if r.returncode != 0:
        failing = [ln for ln in out.splitlines() if ln.lstrip().startswith("not ok")]
        pytest.fail(f"{path.name} failed (exit {r.returncode}):\n" + "\n".join(failing) + "\n\n" + out[-4000:])
    # guard against a vacuous pass (e.g. a runner change that silently finds no tests)
    passed = [ln for ln in out.splitlines() if ln.startswith("# pass ")]
    assert passed and int(passed[-1].split()[-1]) > 0, out[-2000:]


_EDIT_SCRIPT = """
import { readFileSync } from 'node:fs';
const yt = await import(process.argv[1]);
const policy = readFileSync(process.argv[2], 'utf8');
const block = yt.listControlBlocks(policy).find((b) => !b.flow);
const out = {
  control: block ? block.id : null,
  disabled: block ? yt.setControlField(policy, block.id, 'enabled', false)?.yaml ?? null : null,
  profile: yt.setTopLevelScalar(policy, 'profile', 'strict').yaml,
  kill: yt.setKillSwitch(policy, 'agent:golden-agent@test', true)?.yaml ?? null,
  keyword: yt.addCustomKeyword(policy, 'golden-codename')?.yaml ?? null,
  broken: yt.breakYaml(policy).yaml,
};
process.stdout.write(JSON.stringify(out));
"""


def test_yaml_quick_edits_parse_on_the_server(node: str) -> None:
    lib = ROOT / "web" / "src" / "components" / "governance" / "lib" / "yaml-text.ts"
    policy = ROOT / "config" / "policy.yaml"
    r = subprocess.run(
        [node, "--input-type=module", "-e", _EDIT_SCRIPT, lib.as_uri(), str(policy)],
        cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT_S, check=False,
    )
    assert r.returncode == 0, r.stderr[-4000:]
    out = json.loads(r.stdout)

    assert out["control"] and out["disabled"], "no block-style control found in config/policy.yaml"
    doc = yaml.safe_load(out["disabled"])
    ctl = next(c for c in doc["controls"] if isinstance(c, dict) and c.get("id") == out["control"])
    assert ctl["enabled"] is False

    assert yaml.safe_load(out["profile"])["profile"] == "strict"

    assert out["kill"], "budgets.kill_switch flow mapping not found"
    assert "golden-agent@test" in yaml.safe_load(out["kill"])["budgets"]["kill_switch"]["agents"]

    if out["keyword"] is not None:  # null = CUS-01 exists without an editable keyword list
        doc = yaml.safe_load(out["keyword"])
        cus = next(c for c in doc["controls"] if isinstance(c, dict) and c.get("id") == "CUS-01")
        assert "golden-codename" in json.dumps(cus)

    # the "break it" demo really is rejected by the server's YAML parser
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(out["broken"])
