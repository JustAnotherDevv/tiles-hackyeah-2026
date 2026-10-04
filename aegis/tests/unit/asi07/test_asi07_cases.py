"""tests/cases/asi07.yaml + the snippet's inline tests, replayed through POST /v1/guard on the
real gateway with the asi-07 snippet applied (green before and after ASI-POLICY's merge)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.unit.asi07.conftest import snippet_controls
from tests.unit.asi07.test_asi07_gateway import _auth

CASES = Path(__file__).resolve().parents[2] / "cases" / "asi07.yaml"


def _cases() -> list[dict[str, Any]]:
    doc = yaml.safe_load(CASES.read_text())
    return [{**doc.get("defaults", {}), **c} for c in doc["cases"]]


def _inline() -> list[dict[str, Any]]:
    out = []
    for c in snippet_controls():
        for t in c.get("tests", []):
            out.append({"id": t["name"], "control": t.get("control"), "expect": t["expect"],
                        "surface": t["surface"], "tool": t.get("tool_name"),
                        "input": t.get("text"), "dest": t.get("destination")})
    return out


async def _run(gw, case: dict[str, Any]) -> dict[str, Any]:
    inter = {"surface": case["surface"], "kind": "a2a", "destination": case.get("dest"),
             "tool_name": case.get("tool"), "text": case.get("input"),
             "meta": case.get("meta") or {}}
    r = await gw.post("/v1/guard", json={"interaction": inter},
                      headers=_auth("trading-copilot@trading"))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("case", _cases() + _inline(), ids=lambda c: c["id"])
async def test_case(a2a, case: dict[str, Any]) -> None:
    gw, _peer, _rt = a2a
    body = await _run(gw, case)
    v = body["verdict"]
    assert v["action"] == case["expect"], (case["id"], v.get("primary"))
    if case["expect"] != "allow" and case.get("control"):
        assert v["primary"]["control_id"] == case["control"], v["primary"]
    if case["expect"] == "redact":
        text = body.get("text") or ""
        assert "AEGIS-QUARANTINE" in text and "exfil.test" not in text, text
        assert text.startswith("Summary"), text  # the benign part is still delivered
