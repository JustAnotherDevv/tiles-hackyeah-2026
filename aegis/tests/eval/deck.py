"""reports/deck_numbers.{json,md}: paste-ready pitch numbers, each traced to a file + JSON path.

Missing values are written as "not measured" - never a guess.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.eval.common import now_iso, read_json, write_json_atomic, write_text_atomic

NM = "not measured"


def _get(doc: dict[str, Any] | None, path: str) -> Any:
    cur: Any = doc
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _row(slide: str, placeholder: str, doc: dict | None, file: str, path: str, unit: str, *,
         scale: float = 1.0, nd: int = 1, note: str = "") -> dict[str, Any]:
    v = _get(doc, path)
    value: Any = NM
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        value = round(v * scale, nd)
    elif isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v):
        value = f"{v[0] * scale:.{nd}f}–{v[1] * scale:.{nd}f}"
    return {"slide": slide, "placeholder": placeholder, "value": value, "unit": unit if value != NM else "",
            "source_file": file, "json_path": path,
            "measured_at": (doc or {}).get("generated_at") if value != NM else None, "note": note}


def _run_idx(evald: dict | None, profile: str, mode_prefix: str = "deterministic") -> int | None:
    for i, r in enumerate((evald or {}).get("runs") or []):
        if r.get("profile") == profile and str(r.get("mode", "")).startswith(mode_prefix) and r.get("overall"):
            return i
    return None


def _ctl_idx(bench: dict | None, cid: str) -> int | None:
    for i, r in enumerate((bench or {}).get("by_control") or []):
        if r.get("control_id") == cid:
            return i
    return None


def build(out_dir: Path) -> list[dict[str, Any]]:
    bench = read_json(out_dir / "bench.json")
    evald = read_json(out_dir / "eval.json")
    results = read_json(out_dir / "results.json")
    dlpm = read_json(out_dir / "dlp-metrics.json")
    B, E, R = "reports/bench.json", "reports/eval.json", "reports/results.json"
    rows: list[dict[str, Any]] = []
    # slide 4: data never leaves
    dlp_runs = ((evald or {}).get("dlp") or {}).get("runs") or []
    for i, d in enumerate(dlp_runs):
        rows.append(_row("4", f"leak rate ({d.get('profile')}, {d.get('mode')})", evald, E,
                         f"dlp.runs.{i}.leak_rate", "%", scale=100, nd=2,
                         note=f"{d.get('leaked_entities')}/{d.get('entities')} gold PII/secret values left toward a "
                              "remote model"))
    if not dlp_runs:
        rows.append(_row("4", "end-to-end leak rate", None, E, "dlp.runs.0.leak_rate", "%"))
    rows.append(_row("4", "detector precision (redaction-engine)", dlpm, "reports/dlp-metrics.json",
                     "overall.precision", "", nd=3, note="redaction-engine detector P/R (if present)"))
    rows.append(_row("4", "detector recall (redaction-engine)", dlpm, "reports/dlp-metrics.json",
                     "overall.recall", "", nd=3))
    # slide 7: live policy
    if _get(bench, "reload.file_to_active_ms.p95") is not None:
        rows.append(_row("7", "policy edit -> active p95", bench, B, "reload.file_to_active_ms.p95", "ms", nd=0,
                         note="file write -> /healthz policy_version (spawned gateway)"))
    else:
        rows.append(_row("7", "policy edit -> active p95", results, R, "perf.reload_ms", "ms", nd=0,
                         note="test-suite measurement (fallback)"))
    rows.append(_row("7", "policy apply p95 (in-process)", bench, B, "reload.apply_ms.p95", "ms", nd=0,
                     note="rt.policy.apply_yaml incl. self-test gate"))
    rows.append(_row("7", "feed signature activation", results, R, "perf.feed_activation_ms", "ms", nd=0))
    # slide 9: performance + honest robustness
    rows.append(_row("9", "gateway overhead p50 (deterministic)", bench, B, "headline.det_overhead_p50_ms", "ms", nd=2))
    rows.append(_row("9", "gateway overhead p95 (deterministic)", bench, B, "headline.det_overhead_p95_ms", "ms", nd=2))
    rows.append(_row("9", "throughput (deterministic, co-located load generator)", bench, B, "headline.rps_det",
                     "rps", nd=0, note="lower bound"))
    rows.append(_row("9", "share of an 800 ms upstream", bench, B, "headline.overhead_share_pct", "%", nd=2,
                     note="simulated upstream"))
    rows.append(_row("9", "semantic overhead p50", bench, B, "headline.sem_overhead_p50_ms", "ms", nd=1))
    rows.append(_row("9", "semantic overhead p95", bench, B, "headline.sem_overhead_p95_ms", "ms", nd=1))
    ci = _ctl_idx(bench, "DLP-01")
    rows.append(_row("9", "redaction (DLP-01) p95", bench, B,
                     f"by_control.{ci}.p95_ms" if ci is not None else "by_control.DLP-01.p95_ms", "ms", nd=2))
    for prof in ("balanced", "strict"):
        i = _run_idx(evald, prof, "semantic")
        mode = "semantic"
        if i is None:
            i = _run_idx(evald, prof)
            mode = "deterministic"
        base = f"runs.{i}" if i is not None else f"runs.?{prof}"
        rows.append(_row("9", f"attack detection ({prof}, {mode})", evald, E, f"{base}.overall.attack.rate", "%",
                         scale=100))
        rows.append(_row("9", f"attack detection 95% CI ({prof}, {mode})", evald, E, f"{base}.overall.attack.ci95",
                         "%", scale=100))
        rows.append(_row("9", f"false-positive rate ({prof}, {mode})", evald, E, f"{base}.overall.benign.fpr", "%",
                         scale=100))
        rows.append(_row("9", f"held-out detection ({prof}, {mode})", evald, E,
                         f"{base}.by_split.held_out.attack.rate", "%", scale=100,
                         note="public sets not used for tuning"))
    rows.append(_row("9", "obfuscation coverage (seed x transform)", bench, B, "headline.obfuscation_coverage", "%",
                     scale=100))
    # HackTribe claims
    rows.append(_row("claims", "\"policy edits apply within a second\" (reload p95)", bench, B,
                     "headline.reload_p95_ms", "ms", nd=0))
    return rows


def markdown(rows: list[dict[str, Any]]) -> str:
    L = ["# Deck numbers (measured; paste-ready)", "", f"Generated {now_iso()}. Every value is read from a "
         "report file at the given JSON path. `not measured` means the run has not happened - never fill in a guess.",
         "", "| slide | number | value | source | json path | measured at | note |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        v = r["value"] if r["value"] == NM else f"{r['value']} {r['unit']}".strip()
        L.append(f"| {r['slide']} | {r['placeholder']} | **{v}** | `{r['source_file']}` | `{r['json_path']}` | "
                 f"{r['measured_at'] or ''} | {r['note']} |")
    return "\n".join(L) + "\n"


def write(out_dir: Path) -> list[dict[str, Any]]:
    rows = build(out_dir)
    write_json_atomic(out_dir / "deck_numbers.json", {"generated_at": now_iso(), "rows": rows})
    write_text_atomic(out_dir / "deck_numbers.md", markdown(rows))
    return rows


__all__ = ["build", "markdown", "write"]
