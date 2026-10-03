"""Eval reports: eval.json, heatmap.json, eval.md, console tables, bench.json merge (plan 19 §2.10)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from tests.eval.common import merge_bench, write_json_atomic, write_text_atomic
from tests.eval.heatmap import ascii_heatmap

EVAL_SCHEMA = "aegis.eval/1"
NM = "not measured"


def pct(x: float | None, nd: int = 1) -> str:
    return NM if x is None else f"{x * 100:.{nd}f}%"


def ci(c: list[float] | tuple[float, float] | None) -> str:
    return "" if not c else f"[{c[0] * 100:.1f}–{c[1] * 100:.1f}]"


def compact_run(run: dict[str, Any]) -> dict[str, Any]:
    s = run.get("summary") or {}
    ov = s.get("overall") or {}
    out = {
        "profile": run["profile"], "mode": run["mode"], "status": run.get("status", "ok"),
        "skipped": run.get("skipped"), "n": s.get("n"), "sampled": run.get("sampled", False),
        "policy_version": run.get("policy_version"),
    }
    if ov:
        out["attack"] = {k: ov["attack"][k] for k in ("rate", "ci95", "n", "detected")}
        out["benign"] = {k: ov["benign"][k] for k in ("fpr", "ci95", "n", "over_block", "intervention_rate")}
        out["by_lang"] = {
            lang: {"attack_rate": v["attack"]["rate"], "attack_ci95": v["attack"]["ci95"], "attack_n": v["attack"]["n"],
                   "fpr": v["benign"]["fpr"], "fpr_ci95": v["benign"]["ci95"], "benign_n": v["benign"]["n"]}
            for lang, v in (s.get("by_lang") or {}).items()
        }
        out["by_split"] = {
            k: {"attack_rate": v["attack"]["rate"], "attack_ci95": v["attack"]["ci95"], "attack_n": v["attack"]["n"],
                "fpr": v["benign"]["fpr"], "fpr_ci95": v["benign"]["ci95"], "benign_n": v["benign"]["n"]}
            for k, v in (s.get("by_split") or {}).items()
        }
        out["errors"] = s.get("errors")
        out["latency_ms"] = s.get("latency_ms")
    return out


def find_run(runs: list[dict[str, Any]], profile: str, mode_prefix: str = "deterministic") -> dict | None:
    for r in runs:
        if r["profile"] == profile and str(r["mode"]).startswith(mode_prefix) and r.get("summary"):
            return r
    return None


def headline_from_eval(runs: list[dict[str, Any]], heatmap: dict[str, Any] | None) -> dict[str, Any]:
    h: dict[str, Any] = {}
    bal = find_run(runs, "balanced", "semantic") or find_run(runs, "balanced", "deterministic")
    if bal:
        ov = bal["summary"]["overall"]
        h["detection_rate_balanced"] = ov["attack"]["rate"]
        h["fpr_balanced"] = ov["benign"]["fpr"]
        h["detection_mode_balanced"] = bal["mode"]
        held = (bal["summary"].get("by_split") or {}).get("held_out")
        if held:
            h["detection_rate_balanced_held_out"] = held["attack"]["rate"]
            h["fpr_balanced_held_out"] = held["benign"]["fpr"]
    if heatmap:
        h["obfuscation_coverage"] = heatmap["overall"]["rate"]
    return h


def build_eval_json(meta: dict[str, Any], runs: list[dict[str, Any]], dlp: dict[str, Any] | None,
                    heatmap: dict[str, Any] | None) -> dict[str, Any]:
    out_runs = []
    for r in runs:
        s = r.get("summary") or {}
        out_runs.append({
            "profile": r["profile"], "mode": r["mode"], "status": r.get("status", "ok"),
            "skipped": r.get("skipped"), "reason": r.get("reason"), "policy_version": r.get("policy_version"),
            "feed_serial": r.get("feed_serial"), "semantic_status": r.get("semantic_status"),
            "switch": r.get("switch"), "sampled": r.get("sampled", False), "duration_s": r.get("duration_s"),
            **s,
        })
    return {"schema": EVAL_SCHEMA, **meta, "runs": out_runs, "dlp": dlp, "heatmap": heatmap}


def eval_markdown(doc: dict[str, Any]) -> str:
    L = ["# Aegis red-team evaluation", "",
         f"Generated {doc.get('generated_at')} · {doc.get('duration_s')} s · "
         f"{doc.get('machine', {}).get('cpu')} · corpora {doc.get('corpora', {}).get('rows')} rows",
         "", "All numbers are measured by `python -m tests.eval` against the real Aegis pipeline "
         "(in-process, `dry_run`). Rates exclude errors; 95 % Wilson intervals in brackets. "
         "**Held-out** = public sets the detectors were not tuned on (deepset, gandalf, JBB, XSTest); "
         "**tuning** = handwritten/generated/indirect sets that injection-defense tunes on.", "",
         "## Detection and false positives per profile", "",
         "| profile | mode | n | attack detected | FPR (block/approval on benign) | held-out detection | "
         "held-out FPR | EN | PL | DE | errors |",
         "|---|---|--:|---|---|---|---|---|---|---|--:|"]
    for r in doc["runs"]:
        if r.get("status") not in (None, "ok"):
            L.append(f"| {r['profile']} | {r['mode']} | – | {r.get('status')}: {r.get('skipped') or r.get('reason')} "
                     "| | | | | | | |")
            continue
        ov = r["overall"]
        sp = r.get("by_split") or {}
        bl = r.get("by_lang") or {}

        def lang(k: str, bl: dict = bl) -> str:
            v = bl.get(k)
            return pct(v["attack"]["rate"]) if v and v["attack"]["n"] else "–"

        ho = sp.get("held_out", {})
        L.append(
            f"| {r['profile']} | {r['mode']} | {r['n']} | {pct(ov['attack']['rate'])} {ci(ov['attack']['ci95'])} "
            f"| {pct(ov['benign']['fpr'])} {ci(ov['benign']['ci95'])} "
            f"| {pct(ho.get('attack', {}).get('rate'))} | {pct(ho.get('benign', {}).get('fpr'))} "
            f"| {lang('en')} | {lang('pl')} | {lang('de')} | {r.get('errors')} |")
    base = next((r for r in doc["runs"] if r.get("overall") and r["profile"] == "balanced"), None)
    if base:
        L += ["", f"## Balanced ({base['mode']}) by category", "", "| category | attacks | detected | benign | FPR |",
              "|---|--:|---|--:|---|"]
        for k, v in base["by_category"].items():
            L.append(f"| {k} | {v['attack']['n']} | {pct(v['attack']['rate'])} | {v['benign']['n']} | "
                     f"{pct(v['benign']['fpr'])} |")
        L += ["", "## Balanced by corpus source", "", "| source | attacks | detected | benign | FPR |",
              "|---|--:|---|--:|---|"]
        for k, v in base["by_source"].items():
            L.append(f"| {k} | {v['attack']['n']} | {pct(v['attack']['rate'])} | {v['benign']['n']} | "
                     f"{pct(v['benign']['fpr'])} |")
        L += ["", "## Balanced: deciding controls", "", "| control | true positives | false positives | deciding |",
              "|---|--:|--:|--:|"]
        for c in base["by_control"]:
            L.append(f"| {c['control_id']} | {c['tp']} | {c['fp']} | {c['deciding']} |")
        L += ["", f"## Balanced: misses (first 20 of {base.get('misses_total')}, masked previews)", "",
              "| id | category | lang | action | preview |", "|---|---|---|---|---|"]
        for m in base["misses"]:
            L.append(f"| {m['id']} | {m['category']} | {m['lang']} | {m['action']} | {_md(m['preview'])} |")
        L += ["", f"## Balanced: false positives ({base.get('false_positives_total')})", "",
              "| id | category | lang | action | control | preview |", "|---|---|---|---|---|---|"]
        for m in base["false_positives"]:
            L.append(f"| {m['id']} | {m['category']} | {m['lang']} | {m['action']} | {m['control_id']} | "
                     f"{_md(m['preview'])} |")
    hm = doc.get("heatmap")
    if hm:
        L += ["", f"## Obfuscation heatmap ({hm['profile']} · {hm['mode']})", "", "```", ascii_heatmap(hm), "```"]
    dlp = doc.get("dlp")
    if dlp and dlp.get("runs"):
        L += ["", "## End-to-end DLP leak leg", "",
              "Gold PII / secret values still present in the text that would leave toward a remote model.", "",
              "| profile | mode | entities | leaked | leak rate | hard negatives over-blocked | intervention |",
              "|---|---|--:|--:|---|---|---|"]
        for d in dlp["runs"]:
            hn = d["hard_negatives"]
            L.append(f"| {d['profile']} | {d['mode']} | {d['entities']} | {d['leaked_entities']} | "
                     f"{pct(d['leak_rate'], 2)} {ci(d['leak_ci95'])} | {pct(hn['fpr'])} | "
                     f"{pct(hn['intervention_rate'])} |")
    L += ["", "## Corpora", "", "| file | rows | attack | benign | licence | tuning? |", "|---|--:|--:|--:|---|---|"]
    for f in doc.get("corpora", {}).get("files", []):
        L.append(f"| {f['file']} | {f['rows']} | {f.get('attack')} | {f.get('benign')} | {f.get('licence')} | "
                 f"{'yes' if f.get('seen_by_tuning') else 'no'} |")
    L += ["", "## Attribution", ""] + [f"- {a}" for a in doc.get("attribution", [])] + [""]
    return "\n".join(L)


def _md(s: str | None) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def console(doc: dict[str, Any]) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
    except Exception:  # pragma: no cover
        print(eval_markdown(doc))
        return
    con = Console(width=None if sys.stdout.isatty() else 140)
    t = Table(title="Aegis red-team eval (measured; 95% Wilson CI)", header_style="bold")
    for col in ("profile", "mode", "n", "attack detected", "FPR", "held-out det.", "EN", "PL", "errors"):
        t.add_column(col, justify="right" if col in ("n", "errors") else "left")
    for r in doc["runs"]:
        if r.get("status") not in (None, "ok"):
            t.add_row(r["profile"], r["mode"], "-", f"[yellow]{r.get('status')}: {r.get('skipped') or r.get('reason')}",
                      "", "", "", "", "")
            continue
        ov = r["overall"]
        bl = r.get("by_lang") or {}
        ho = (r.get("by_split") or {}).get("held_out", {})
        t.add_row(
            r["profile"], r["mode"], str(r["n"]),
            f"[green]{pct(ov['attack']['rate'])}[/] {ci(ov['attack']['ci95'])}",
            f"{pct(ov['benign']['fpr'])} {ci(ov['benign']['ci95'])}",
            pct(ho.get("attack", {}).get("rate")),
            pct(bl.get("en", {}).get("attack", {}).get("rate")),
            pct(bl.get("pl", {}).get("attack", {}).get("rate")),
            str(r.get("errors")),
        )
    con.print(t)
    if doc.get("heatmap"):
        con.print(f"[bold]Obfuscation heatmap[/] ({doc['heatmap']['profile']} · {doc['heatmap']['mode']}): "
                  "█ detected · missed")
        con.print(ascii_heatmap(doc["heatmap"]), highlight=False)
    dlp = doc.get("dlp") or {}
    for d in dlp.get("runs", []):
        con.print(f"DLP leak leg {d['profile']}·{d['mode']}: {d['leaked_entities']}/{d['entities']} gold values "
                  f"leaked ({pct(d['leak_rate'], 2)}), hard-negative over-block {pct(d['hard_negatives']['fpr'])}")


def write_eval_reports(out_dir: Path, doc: dict[str, Any], *, html: bool = True) -> list[Path]:
    from tests.eval.schemas import validate

    written: list[Path] = []
    validate("eval", doc)
    write_json_atomic(out_dir / "eval.json", doc)
    written.append(out_dir / "eval.json")
    if doc.get("heatmap"):
        validate("heatmap", doc["heatmap"])
        write_json_atomic(out_dir / "heatmap.json", doc["heatmap"])
        written.append(out_dir / "heatmap.json")
    write_text_atomic(out_dir / "eval.md", eval_markdown(doc))
    written.append(out_dir / "eval.md")
    if html:
        from tests.eval.html import eval_html

        write_text_atomic(out_dir / "eval.html", eval_html(doc))
        written.append(out_dir / "eval.html")
    compact = {
        "generated_at": doc["generated_at"], "duration_s": doc.get("duration_s"),
        "source_file": "reports/eval.json", "runs": [compact_run({**r, "summary": r if r.get("overall") else None})
                                                     for r in doc["runs"]],
        "corpora_rows": doc.get("corpora", {}).get("rows"), "attribution": doc.get("attribution"),
    }
    dlp = doc.get("dlp")
    bench_dlp = None
    if dlp:
        bench_dlp = {"runs": [{k: d[k] for k in ("profile", "mode", "entities", "leaked_entities", "leak_rate",
                                                 "leak_ci95", "by_lang", "hard_negatives")} for d in dlp.get("runs", [])],
                     "detector_metrics": dlp.get("detector_metrics")}
    merge_bench(out_dir, {"eval": compact, "heatmap": doc.get("heatmap"), "dlp": bench_dlp},
                headline=headline_from_eval([{**r, "summary": r} for r in doc["runs"] if r.get("overall")],
                                            doc.get("heatmap")))
    validate("bench", _read_bench(out_dir))
    written.append(out_dir / "bench.json")
    return written


def _read_bench(out_dir: Path) -> dict[str, Any]:
    import json

    return json.loads((out_dir / "bench.json").read_text(encoding="utf-8"))


__all__ = ["EVAL_SCHEMA", "build_eval_json", "compact_run", "console", "eval_markdown", "headline_from_eval",
           "write_eval_reports"]
