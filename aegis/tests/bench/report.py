"""bench.json (aegis.bench/1, superset of plan 16 G3), bench.md, bench.html; merges eval + snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.eval.common import BENCH_SCHEMA, read_json, write_json_atomic, write_text_atomic

DATA = Path(__file__).resolve().parent / "data"
KEEP_FROM_EVAL = ("eval", "heatmap", "dlp")
EVAL_HEADLINE_KEYS = ("detection_rate_balanced", "fpr_balanced", "obfuscation_coverage",
                      "detection_mode_balanced", "detection_rate_balanced_held_out", "fpr_balanced_held_out")


def load_snapshot(name: str) -> dict[str, Any] | None:
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except Exception:
        return None


def merge_by_control(profiles: list[dict[str, Any]], micro: list[dict[str, Any]], kinds: dict[str, str]
                     ) -> list[dict[str, Any]]:
    """Per control: prefer pipeline-observed rows (count >= 50 % of requests), else micro, else Server-Timing."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for p in profiles:
        if p["path"] != "/v1/guard" or p["concurrency"] != 1:
            continue
        for row in p.get("by_control") or []:
            key = (row["control_id"], p["mode"])
            if row["count"] >= 0.5 * max(1, p["requests"] - p["errors"]) and key not in out:
                out[key] = {**row, "mode": p["mode"], "kind": kinds.get(row["control_id"]), "profile": p["name"]}
    for row in micro:
        key = (row["control_id"], row["mode"])
        if key not in out:
            out[key] = {**row, "kind": row.get("kind") or kinds.get(row["control_id"])}
        else:
            out[key]["micro_p95_ms"] = row["p95_ms"]
    for p in profiles:
        for row in p.get("by_control") or []:
            key = (row["control_id"], p["mode"])
            if key not in out:
                out[key] = {**row, "mode": p["mode"], "kind": kinds.get(row["control_id"]), "profile": p["name"]}
    return sorted(out.values(), key=lambda r: (r["mode"], -(r.get("p95_ms") or 0)))


def headline(doc: dict[str, Any]) -> dict[str, Any]:
    prev = doc.get("headline") or {}
    h: dict[str, Any] = {k: prev.get(k) for k in EVAL_HEADLINE_KEYS if k in prev}
    prof = {p["name"]: p for p in doc.get("profiles", [])}
    c1 = prof.get("guard-det-c1")
    c16 = prof.get("guard-det-c16")
    h["det_overhead_p50_ms"] = (c1 or {}).get("overhead_ms", {}).get("p50")
    h["det_overhead_p95_ms"] = (c1 or {}).get("overhead_ms", {}).get("p95")
    h["rps_det"] = (c16 or {}).get("rps")
    s1 = prof.get("guard-sem-c1")
    h["sem_overhead_p50_ms"] = (s1 or {}).get("overhead_ms", {}).get("p50")
    h["sem_overhead_p95_ms"] = (s1 or {}).get("overhead_ms", {}).get("p95")
    h["overhead_share_pct"] = (doc.get("overhead_share") or {}).get("share_pct")
    rl = doc.get("reload") or {}
    h["reload_p95_ms"] = (rl.get("file_to_active_ms") or {}).get("p95") or (rl.get("apply_ms") or {}).get("p95")
    return h


def modes_block(doc: dict[str, Any], sem_meta: dict[str, Any]) -> dict[str, Any]:
    prof = {p["name"]: p for p in doc.get("profiles", [])}
    det = {"overhead_ms": (prof.get("guard-det-c1") or {}).get("overhead_ms"),
           "rps": (prof.get("guard-det-c16") or {}).get("rps")}
    sem = {"overhead_ms": (prof.get("guard-sem-c1") or {}).get("overhead_ms"),
           "rps": (prof.get("guard-sem-c4") or {}).get("rps"), **sem_meta}
    return {"deterministic": det, "semantic": sem}


def models_block(live_status: dict[str, Any] | None) -> list[dict[str, Any]]:
    snap = load_snapshot("model_latency.snapshot.json") or {}
    rows = [{**m, "source": f"snapshot ({snap.get('measured_at')})"} for m in snap.get("models", [])]
    for m in (live_status or {}).get("models") or []:
        if m.get("p50_ms") is None and not m.get("calls"):
            continue
        rows.insert(0, {"name": m.get("name"), "role": m.get("role"), "p50_ms": m.get("p50_ms"),
                        "p95_ms": m.get("p95_ms"), "calls": m.get("calls"), "fallbacks": m.get("fallbacks"),
                        "escalations": m.get("escalations"), "memory_mb": m.get("est_mb"), "source": "live"})
    return rows


def finalize(out_dir: Path, doc: dict[str, Any], *, html: bool = True) -> list[Path]:
    """Merge eval keys from an existing bench.json, compute headline, validate, write json/md/html."""
    from tests.eval.schemas import validate

    prev = read_json(out_dir / "bench.json") or {}
    for k in KEEP_FROM_EVAL:
        if k not in doc and prev.get(k) is not None:
            doc[k] = prev[k]
    doc["headline"] = {**(prev.get("headline") or {}), **{k: v for k, v in headline({**doc, "headline":
                                                                                         prev.get("headline")}).items()}}
    sel = read_json(out_dir / "results.json")
    if sel and "selftest" not in doc:
        doc["selftest"] = {k: sel.get(k) for k in ("generated_at", "summary", "totals", "perf") if k in sel} or None
    doc.setdefault("schema", BENCH_SCHEMA)
    validate("bench", doc)
    write_json_atomic(out_dir / "bench.json", doc)
    write_text_atomic(out_dir / "bench.md", markdown(doc))
    paths = [out_dir / "bench.json", out_dir / "bench.md"]
    if html:
        from tests.eval.html import bench_html

        write_text_atomic(out_dir / "bench.html", bench_html(doc))
        paths.append(out_dir / "bench.html")
    return paths


def _ms(x: Any) -> str:
    return "not measured" if x is None else f"{x:.2f} ms"


def markdown(doc: dict[str, Any]) -> str:
    m = doc.get("machine") or {}
    L = ["# Aegis performance benchmark", "",
         f"Generated {doc.get('generated_at')} · status **{doc.get('status')}** · {doc.get('duration_s')} s · "
         f"{m.get('cpu')} · {m.get('ram_gb')} GB ({m.get('available_gb_at_start')} GB free at start) · "
         f"target `{(doc.get('target') or {}).get('kind')}` · {m.get('load_generator')}", "",
         "Overhead = server-side `Server-Timing aegis` (fallback: verdict latency, then client time).", "",
         "## Headline", "", "| metric | value |", "|---|---|"]
    for k, v in (doc.get("headline") or {}).items():
        L.append(f"| {k} | {'not measured' if v is None else v} |")
    L += ["", "## Profiles", "", "| profile | mode | path | c | requests | errors | rps | overhead p50 | p95 | p99 | "
          "client p50 |", "|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for p in doc.get("profiles", []):
        o, c = p.get("overhead_ms") or {}, p.get("client_ms") or {}
        L.append(f"| {p['name']} | {p['mode']} | `{p['path']}` | {p['concurrency']} | {p['requests']} | {p['errors']} "
                 f"| {p.get('rps')} | {_ms(o.get('p50'))} | {_ms(o.get('p95'))} | {_ms(o.get('p99'))} | "
                 f"{_ms(c.get('p50'))} |")
    if doc.get("overhead_share"):
        s = doc["overhead_share"]
        L += ["", f"**Aegis adds {_ms(s.get('aegis_p50_ms'))} of a {s.get('total_p50_ms')} ms request with an "
                  f"{s.get('upstream_delay_ms')} ms upstream = {s.get('share_pct')} %** ({s.get('note')})."]
    if doc.get("by_control"):
        L += ["", "## Per control", "", "| control | mode | p50 | p95 | n | source |", "|---|---|--:|--:|--:|---|"]
        for r in doc["by_control"]:
            L.append(f"| {r['control_id']} | {r.get('mode')} | {_ms(r.get('p50_ms'))} | {_ms(r.get('p95_ms'))} | "
                     f"{r.get('count')} | {r.get('source')} |")
    if doc.get("reload"):
        L += ["", "## Policy reload", "", "```", json.dumps(doc["reload"], indent=2), "```"]
    sem = (doc.get("modes") or {}).get("semantic") or {}
    if sem.get("skipped"):
        L += ["", f"Semantic stage skipped: {sem['skipped']}"]
    if doc.get("models"):
        L += ["", "## Models (live rows first; snapshot rows labelled)", "", "| model | role | p50 | p95 | source |",
              "|---|---|--:|--:|---|"]
        for r in doc["models"]:
            L.append(f"| {r.get('name')} | {r.get('role')} | {r.get('p50_ms')} | {r.get('p95_ms')} | {r.get('source')} |")
    L.append("")
    return "\n".join(L)


__all__ = ["finalize", "headline", "load_snapshot", "markdown", "merge_by_control", "models_block", "modes_block"]
