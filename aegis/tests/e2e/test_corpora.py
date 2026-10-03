"""Corpora rate suites (TEST-21, non-gating): finance benign wall, Polish/multilingual, agentic tools,
and the obfuscation matrix (seed × transform → heatmap cells in results.json / selftest.html).

Each row goes through `/v1/guard`; detection rate (attacks not allowed) and false-positive rate
(benign rows not allowed) are reported with Wilson 95 % intervals. Misses are recorded as `xfail`
in the matrix (suite "Corpora (rates)"); these suites never fail the build.
"""

from __future__ import annotations

import json
import math
import secrets
from pathlib import Path
from typing import Any

import pytest

from tests.lib.matrix import RESULTS, Entry
from tests.lib.privacy import mask_text

DIR = Path(__file__).resolve().parents[1] / "fixtures" / "corpora"
CORPORA = ["finance_benign", "polish_multilingual", "agentic_tools", "obfuscation_matrix"]
ARG = {"Bash": "command", "sql_query": "sql", "read_file": "file_path", "write_file": "file_path"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


def _interaction(row: dict[str, Any]) -> dict[str, Any]:
    s, text = row.get("surface"), row.get("text", "")
    if s == "tool_input":
        tool = row.get("tool") or "Bash"
        tool = {"sql_query": "acme-db.query"}.get(tool, tool)
        surface = "mcp.call" if "." in tool else "tool.input"
        return {
            "surface": surface,
            "tool_name": tool,
            "destination": "local",
            "tool_args": {ARG.get(row.get("tool") or "Bash", "input"): text},
        }
    if s == "mcp_tool_description":
        return {
            "surface": "mcp.list",
            "tool_name": "weather.corpus_tool",
            "text": text,
            "destination": "remote",
            "meta": {"raw_result": {"name": "corpus_tool", "description": text}},
        }
    if s == "model_output":
        return {"surface": "model.response", "text": text, "destination": "remote"}
    if s == "tool_result":
        return {"surface": "tool.output", "text": text, "destination": "remote"}
    return {"surface": "model.request", "text": text, "destination": "remote"}


@pytest.mark.parametrize("corpus", CORPORA)
def test_corpus_rates(gw: Any, corpus: str) -> None:
    path = DIR / f"{corpus}.jsonl"
    if not path.exists():
        pytest.skip(f"{path.name} missing")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    tp = fn = fp = tn = 0
    cells: list[tuple[str, str, str]] = []
    for row in rows:
        r = gw.guard(
            _interaction(row),
            who="chaos-agent@platform",
            session=f"t-corpus-{secrets.token_hex(3)}",
            dry_run=True,
        )
        if r.status_code != 200:
            continue
        v = r.json().get("verdict") or {}
        got = v.get("action")
        flagged = got not in ("allow", "log")
        attack = row.get("label") == "attack" or row.get("expected_action") not in (None, "allow")
        ok = flagged if attack else not flagged
        tp += attack and flagged
        fn += attack and not flagged
        fp += (not attack) and flagged
        tn += (not attack) and not flagged
        if row.get("seed_id") and row.get("transform"):
            cells.append((row["seed_id"], row["transform"], "pass" if ok else "fail"))
        RESULTS.add(
            Entry(
                id=row.get("id", "?"),
                control=None,
                suite="corpora",
                polarity="attack" if attack else "benign",
                expect=row.get("expected_action") or ("block" if attack else "allow"),
                column="attack" if attack else "benign",
                outcome="pass" if ok else "xfail",
                got=got,
                got_control=(v.get("primary") or {}).get("control_id"),
                reason="" if ok else "rate suite miss (non-gating)",
                tier="stretch",
                via="guard",
                latency_ms=v.get("latency_ms"),
                tags=[f"corpus:{corpus}", f"lang:{row.get('lang')}"],
                source=f"tests/fixtures/corpora/{corpus}.jsonl",
                preview=mask_text(row.get("text", "")),
            )
        )
    if cells:
        seeds = sorted({c[0] for c in cells})
        trs = list(dict.fromkeys(c[1] for c in cells))
        RESULTS.obfuscation = {"seeds": seeds, "transforms": trs, "cells": [list(c) for c in cells]}
    n_att, n_ben = tp + fn, fp + tn
    rates = {
        "corpus": corpus,
        "attacks": n_att,
        "benign": n_ben,
        "detection_rate": round(tp / n_att, 3) if n_att else None,
        "detection_ci": wilson(tp, n_att),
        "fpr": round(fp / n_ben, 3) if n_ben else None,
        "fpr_ci": wilson(fp, n_ben),
    }
    RESULTS.perf.setdefault("corpora", {})[corpus] = rates
    print(f"\n{corpus}: {json.dumps(rates)}")
    assert n_att + n_ben > 0, "no rows evaluated"
