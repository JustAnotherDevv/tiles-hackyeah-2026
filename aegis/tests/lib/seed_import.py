"""One-shot dev tool: staging policy examples + approvals routing tests → tests/cases/*.yaml.

    uv run --frozen python -m tests.lib.seed_import --write [--force]

Reads `staging/seed/policy.yaml` (157 examples) and `docs/seed-fixes/approvals.yaml` (routing
tests) at dev time only (never imported at runtime) and applies the plan 18 §2.6 translation
table. Output files are prefixed `seed_` sections inside each family file and then curated by
hand; existing files are never overwritten unless `--force`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "tests" / "cases"

SURFACE = {
    None: "model.request",
    "llm.request": "model.request",
    "llm.response": "model.response",
    "tool.call": "tool.input",
    "action.request": "mcp.call",
    "tool.result": "tool.output",
    "http.egress": "egress.request",
    "tool.list": "mcp.list",
    "hook.pre_tool_use": "tool.input",
    "admin.api": "model.admin",
    "artifact.bytes": "artifact.file",
    "artifact.fetch": "artifact.file",
    "mcp.auth": "mcp.init",
    "a2a.message": "model.request",
}
DEST = {"T0": "local", "T1": "remote", "T2": "third_party"}
EXPECT = {"quarantine": "redact", "strip_tool": "redact", "modify": "redact"}
PLACEHOLDER = {"[PL_PESEL_1]": "[PESEL_1]", "[CREDIT_CARD_1]": "[PAN_1]", "[CVV]": "[REDACTED:CVV]"}
ENTITY = {
    "PL_NIP": "NIP",
    "PL_REGON": "REGON",
    "PL_NRB": "IBAN",
    "CARD_TRACK": "TRACK_DATA",
    "POSTAL_ADDRESS": "ADDRESS",
    "DATE_OF_BIRTH": "DOB",
    "PL_PESEL": "PESEL",
    "CREDIT_CARD": "PAN",
}
STAGING_ONLY = {
    "a2a.message": "A2A controls are reserved (no implementation owner)",
    "artifact.fetch": "artifact fetch surface not in contract",
    "mcp.auth": "OAuth endpoint checks are MCP-04 stretch",
}


def tool_name(t: str | None) -> tuple[str | None, bool]:
    """→ (contract tool name, is_mcp)."""
    if not t:
        return None, False
    m = re.fullmatch(r"mcp__([\w\-]+)__([\w\-]+)", t)
    if m:
        return f"{m.group(1)}.{m.group(2)}", True
    if t == "saas.purchase_subscription":
        return "marketpulse.purchase_subscription", True
    if t == "web_search":
        return "web.fetch_url", True
    if t in ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch") or t.startswith("http."):
        return t, False
    if "." in t:
        return t, True
    return t, False


def fix_text(s: Any) -> Any:
    if isinstance(s, str):
        for a, b in PLACEHOLDER.items():
            s = s.replace(a, b)
        return s
    if isinstance(s, list):
        return [fix_text(x) for x in s]
    if isinstance(s, dict):
        return {k: fix_text(v) for k, v in s.items()}
    return s


def _step(e: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    st = e.get("surface")
    surface = SURFACE.get(st, st or "model.request")
    tool, is_mcp = tool_name(e.get("tool"))
    if surface == "tool.input" and is_mcp and st != "hook.pre_tool_use":
        surface = "mcp.call"
    if not st and tool:
        surface = "mcp.call" if is_mcp else "tool.input"
    if (
        tool
        and tool.startswith("http.")
        and isinstance(e.get("args"), dict)
        and e["args"].get("url")
    ):
        surface = "egress.request"
        out["url"] = e["args"]["url"]
        out["method"] = tool.split(".", 1)[1].upper()
    if surface != "model.request":
        out["surface"] = surface
    if tool:
        out["tool"] = tool
    if e.get("args") is not None:
        out["args"] = fix_text(e["args"])
    if e.get("input") is not None:
        out["input"] = fix_text(e["input"])
    if e.get("as"):
        out["as"] = e["as"]
    return out


def translate(ctl: str, e: dict[str, Any], polarity: str, idx: int) -> dict[str, Any]:
    name = re.sub(r"[^A-Z0-9]+", "-", e["name"].upper()).strip("-")
    case: dict[str, Any] = {"id": f"{ctl.replace('-', '')}-{name}"[:60], "control": ctl}
    exp = EXPECT.get(e["expect"], e["expect"])
    case["polarity"] = "benign" if exp in ("allow", "log") else "attack"
    case["expect"] = exp
    st = e.get("surface")
    if st == "hook.pre_tool_use":
        case["via"] = "hook"
        case["hook_event"] = "PreToolUse"
    case.update(_step(e))
    if case.get("via") == "hook":
        case.pop("surface", None)
    as_ = e.get("as")
    if as_ == "key:key_revoked_demo":
        case["as"] = "key:revoked"
    dest = e.get("destination")
    if isinstance(dest, str):
        if dest in DEST:
            case["dest"] = DEST[dest]
        elif dest.startswith("model:"):
            case["model"] = dest.split("/", 1)[-1]
            case["dest"] = "local" if dest.startswith("model:ollama/") else "remote"
    if e.get("steps"):
        case["steps"] = [_step(s) for s in e["steps"]]
        case.pop("surface", None)
    if e.get("repeat"):
        case["repeat"] = int(e["repeat"])
    if e.get("profiles"):
        case["profiles"] = list(e["profiles"])
    if e.get("headers"):
        case["headers"] = {k: v for k, v in e["headers"].items() if k != "X-Aegis-Approval"}
    if e.get("expect_route"):
        case["expect_route"] = e["expect_route"].replace("owner+admin", "owner+2p")
    asserts: dict[str, Any] = {}
    for k in ("upstream_must_contain", "upstream_must_not_contain"):
        if e.get(k):
            asserts[k] = fix_text(e[k])
    if asserts:
        case["assert"] = asserts
    stretch: list[str] = []
    if st in STAGING_ONLY:
        stretch.append(STAGING_ONLY[st])
    if st in ("admin.api", "artifact.bytes"):
        stretch.append("model.admin / artifact bytes through /v1/guard (contract gaps F/A-12)")
    if e.get("expect_status"):
        stretch.append(f"staging expected HTTP {e['expect_status']} (guard always answers 200)")
    if (e.get("headers") or {}).get("X-Aegis-Approval"):
        stretch.append("grant replay is covered by the approvals functional suite")
    for k in (
        "upstream_byte_identical",
        "vault",
        "expect_updated_input_contains",
        "request_params",
        "expect_request_param",
        "mock_usage",
    ):
        if k in e or any(k in (s or {}) for s in e.get("steps") or []):
            stretch.append(f"staging-only field {k}")
    if stretch:
        case["tier"] = "stretch"
        case["note"] = "; ".join(dict.fromkeys(stretch))
    case["source"] = f"staging/seed/policy.yaml#{ctl}/{e['name']}"
    return case


def routing_cases() -> list[dict[str, Any]]:
    path = ROOT / "docs" / "seed-fixes" / "approvals.yaml"
    tests = (yaml.safe_load(path.read_text()) or {}).get("approvals", {}).get("tests", [])
    out = []
    for t in tests:
        req, exp = t["request"], t["expect"]
        role = exp["required_role"]
        expect = {"auto": "allow", "deny": "block"}.get(role, "require_approval")
        case = {
            "id": "APR-" + re.sub(r"[^A-Z0-9]+", "-", t["name"].upper()).strip("-")[:50],
            "control": None,
            "polarity": "benign" if expect == "allow" else "attack",
            "expect": expect,
            "via": "simulate",
            "kind": req["kind"],
            "action_type": req.get("action_type") or "",
            "as": req["requester"],
            "expect_rule": exp.get("rule"),
        }
        if t.get("profile"):
            case["profiles"] = [t["profile"]]
        if req.get("amount_usd") is not None:
            case["amount_usd"] = req["amount_usd"]
        if req.get("resource"):
            case["resource"] = req["resource"]
        if req.get("labels"):
            case["labels"] = req["labels"]
        if req.get("changes"):
            case["changes"] = req["changes"]
        if role not in ("auto", "deny"):
            case["expect_route"] = role + ("+2p" if exp.get("two_person") else "")
        case["source"] = f"docs/seed-fixes/approvals.yaml#{t['name']}"
        out.append(case)
    return out


def staging_cases() -> dict[str, list[dict[str, Any]]]:
    d = yaml.safe_load((ROOT / "staging" / "seed" / "policy.yaml").read_text())
    fam: dict[str, list[dict[str, Any]]] = {}
    for c in d["controls"]:
        ex = c.get("examples") or {}
        for pol in ("should_block", "should_allow"):
            for i, e in enumerate(ex.get(pol) or []):
                case = translate(c["id"], e, pol, i)
                fam.setdefault(c["id"].split("-")[0], []).append(case)
    return fam


def _dump(cases: list[dict[str, Any]]) -> str:
    lines = []
    for c in cases:
        lines.append("- " + json.dumps(c, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", default=str(CASES / "_seed"))
    a = ap.parse_args(argv)
    fam = staging_cases()
    routing = routing_cases()
    total = sum(len(v) for v in fam.values())
    print(f"staging examples: {total} in {len(fam)} families; routing cases: {len(routing)}")
    if not a.write:
        return 0
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f, cases in fam.items():
        p = out / f"{f.lower()}.seed.yaml"
        if p.exists() and not a.force:
            print(f"skip {p} (exists; --force to overwrite)")
            continue
        p.write_text(
            f"# generated by tests/lib/seed_import.py from staging/seed/policy.yaml — curate into "
            f"tests/cases/{f.lower()}.yaml\n" + _dump(cases)
        )
    p = out / "approvals_routing.seed.yaml"
    if not p.exists() or a.force:
        p.write_text(
            "# generated from docs/seed-fixes/approvals.yaml routing tests\n" + _dump(routing)
        )
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
