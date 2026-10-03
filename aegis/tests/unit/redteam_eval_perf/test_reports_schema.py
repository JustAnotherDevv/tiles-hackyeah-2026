"""Reports from fake results go to tmp_path only; schemas validate; bench.json merge keeps profiles."""

from __future__ import annotations

import json

from tests.eval import deck
from tests.eval.common import write_json_atomic
from tests.eval.heatmap import build_heatmap
from tests.eval.metrics import aggregate
from tests.eval.report import build_eval_json, write_eval_reports
from tests.eval.schemas import validate
from tests.unit.redteam_eval_perf.test_heatmap import fake_results


def _doc():
    res = fake_results()
    runs = [{"profile": "balanced", "mode": "deterministic", "status": "ok", "summary": aggregate(res)},
            {"profile": "balanced", "mode": "semantic", "status": "skipped", "skipped": "test"}]
    meta = {"generated_at": "2026-10-04T00:00:00+00:00", "duration_s": 1.0, "machine": {"cpu": "test"},
            "corpora": {"rows": 253, "files": []}, "attribution": ["x"]}
    return build_eval_json(meta, runs, None, build_heatmap([{**runs[0], "results": res}]))


def test_eval_reports_and_bench_merge(tmp_path):
    write_json_atomic(tmp_path / "bench.json", {"schema": "aegis.bench/1", "generated_at": "t", "status": "ok",
                                                "profiles": [{"name": "guard-det-c1", "mode": "deterministic",
                                                              "path": "/v1/guard", "concurrency": 1, "requests": 1,
                                                              "errors": 0, "overhead_ms": {"p50": 1, "p95": 2,
                                                                                           "p99": 3}}],
                                                "headline": {"det_overhead_p50_ms": 1}})
    doc = _doc()
    validate("eval", doc)
    write_eval_reports(tmp_path, doc, html=True)
    for f in ("eval.json", "heatmap.json", "eval.md", "eval.html", "bench.json"):
        assert (tmp_path / f).exists(), f
    b = json.loads((tmp_path / "bench.json").read_text())
    validate("bench", b)
    assert b["profiles"][0]["name"] == "guard-det-c1"  # kept
    assert b["headline"]["det_overhead_p50_ms"] == 1 and b["headline"]["obfuscation_coverage"] is not None
    assert b["eval"]["runs"][0]["attack"]["n"] > 0
    write_eval_reports(tmp_path, doc, html=False)  # idempotent re-run
    assert json.loads((tmp_path / "bench.json").read_text())["profiles"] == b["profiles"]


def test_deck_rows_are_traceable(tmp_path):
    write_eval_reports(tmp_path, _doc(), html=False)
    rows = deck.write(tmp_path)
    assert rows and all(r["source_file"] and r["json_path"] for r in rows)
    nm = [r for r in rows if r["value"] == "not measured"]
    assert nm and all(r["measured_at"] is None for r in nm)
    assert "not measured" in (tmp_path / "deck_numbers.md").read_text()


def test_minimal_bench_validates(tmp_path):
    from tests.eval.common import merge_bench, read_json

    merge_bench(tmp_path, {"eval": None})
    validate("bench", read_json(tmp_path / "bench.json"))
