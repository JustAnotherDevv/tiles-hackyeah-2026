"""Reports: console matrix (rich), junit.xml, results.json (aegis.selftest/1), matrix.md and a
self-contained, offline, dark selftest.html. Inputs are never written raw (masked previews)."""

from __future__ import annotations

import contextlib
import html
import json
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tests.lib.matrix import RESULTS, Recorder, build_rows, build_suites, guard_latency, totals

STATUS_COLOR = {
    "PASS": "green",
    "FAIL": "red",
    "PARTIAL": "yellow",
    "UNTESTED": "magenta",
    "DISABLED": "bright_black",
    "NOT_IMPLEMENTED": "bright_black",
    "SKIPPED": "cyan",
}


def _git_sha() -> str | None:
    with contextlib.suppress(Exception):
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=Path(__file__).resolve().parents[2],
        )
        if out.returncode == 0:
            return out.stdout.strip()
    return None


def _evidence(reports: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"eval": None, "bench": None}
    for k in ("eval", "bench"):
        p = reports / f"{k}.json"
        if p.exists():
            with contextlib.suppress(Exception):
                d = json.loads(p.read_text())
                out[k] = d.get("headline") or d.get("summary") or {kk: d[kk] for kk in list(d)[:8]}
    return out


def build_report(
    rec: Recorder | None = None, duration_s: float = 0.0, reports: Path | None = None
) -> dict[str, Any]:
    rec = rec or RESULTS
    rows = build_rows(rec)
    p50, p95 = guard_latency(rec)
    perf = dict(rec.perf)
    perf["guard_p50_ms"] = perf.get("guard_p50_ms") or p50
    perf["guard_p95_ms"] = perf.get("guard_p95_ms") or p95
    g = rec.gateway or {}
    return {
        "schema": "aegis.selftest/1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "mode": rec.mode,
        "duration_s": round(duration_s, 2),
        "gateway": {
            "url": g.get("url", ""),
            "version": g.get("version"),
            "policy_version": g.get("policy_version"),
            "policy_sha256": g.get("policy_sha256"),
            "profile": g.get("profile"),
            "feed_serial": g.get("feed_serial"),
            "feed_status": g.get("feed_status"),
            "semantic": g.get("semantic"),
        },
        "git_sha": _git_sha(),
        "stack_error": rec.stack_error,
        "totals": totals(rec, rows),
        "controls": rows,
        "suites": build_suites(rec),
        "cases": [e.as_case() for e in rec.entries],
        "perf": perf,
        "obfuscation": rec.obfuscation,
        "evidence": _evidence(reports) if reports else {"eval": None, "bench": None},
    }


def _cnt(c: dict[str, int]) -> str:
    return f"{c['passed']}/{c['total']}" if c["total"] else "–"


def header_line(rep: dict[str, Any]) -> str:
    g = rep["gateway"]
    sha = (g.get("policy_sha256") or "")[:8]
    return (
        f"AEGIS SELF-TEST  mode={rep['mode']}  policy=v{g.get('policy_version')} sha256:{sha}…  "
        f"profile={g.get('profile')}  feed=serial {g.get('feed_serial')} ({g.get('feed_status')})  "
        f"semantic={g.get('semantic')}" + (f"  git={rep['git_sha']}" if rep.get("git_sha") else "")
    )


def matrix_markdown(rep: dict[str, Any]) -> str:
    lines = [
        f"**{header_line(rep)}**",
        "",
        "| Control | Name | Attack | Benign | Redact | Error | Other | p95 ms | Status |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rep["controls"]:
        lines.append(
            f"| {r['control_id']} | {r['name']} | {_cnt(r['attack'])} | {_cnt(r['benign'])} | "
            f"{_cnt(r['redact'])} | {_cnt(r['error'])} | {r['other_control']} | "
            f"{r['p95_ms'] if r['p95_ms'] is not None else '–'} | {r['status']} |"
        )
    if rep["suites"]:
        lines += ["", "| Suite | Passed | Status |", "|---|---|---|"]
        lines += [
            f"| {s['title']} | {s['passed']}/{s['total']} | {s['status']} |" for s in rep["suites"]
        ]
    t = rep["totals"]
    lines += [
        "",
        f"**TOTAL** {t['cases']} cases · {t['passed']} pass · {t['pass_other']} pass(other control) · "
        f"{t['xfailed']} xfail · {t['failed']} fail · {t['skipped']} skip · "
        f"{t['untested_controls']} UNTESTED · {rep['duration_s']} s",
    ]
    return "\n".join(lines) + "\n"


def write_junit(rep: dict[str, Any], path: Path) -> None:
    suites = ET.Element("testsuites", name="aegis-selftest")
    by_suite: dict[str, list[dict[str, Any]]] = {}
    for c in rep["cases"]:
        fam = (c.get("control") or c.get("suite") or "misc").split("-")[0]
        by_suite.setdefault(fam, []).append(c)
    for fam, cases in sorted(by_suite.items()):
        ts = ET.SubElement(
            suites,
            "testsuite",
            name=fam,
            tests=str(len(cases)),
            failures=str(sum(c["outcome"] == "fail" for c in cases)),
            skipped=str(
                sum(c["outcome"] in ("skip", "xfail", "disabled", "not_implemented") for c in cases)
            ),
        )
        for c in cases:
            tc = ET.SubElement(
                ts,
                "testcase",
                classname=c.get("control") or c.get("suite") or fam,
                name=c["id"],
                time=f"{(c.get('latency_ms') or 0) / 1000:.4f}",
            )
            props = ET.SubElement(tc, "properties")
            owasp = ",".join(
                t.split(":", 1)[1] for t in c.get("tags", []) if t.startswith("owasp:")
            )
            atlas = ",".join(
                t.split(":", 1)[1] for t in c.get("tags", []) if t.startswith("atlas:")
            )
            for k, v in (
                ("case_id", c["id"]),
                ("control", c.get("control")),
                ("polarity", c.get("polarity")),
                ("expect", c.get("expect")),
                ("got", c.get("got")),
                ("got_control", c.get("got_control")),
                ("owasp", owasp),
                ("atlas", atlas),
                ("source", c.get("source")),
                ("outcome", c.get("outcome")),
            ):
                ET.SubElement(props, "property", name=k, value=str(v or ""))
            if c["outcome"] == "fail":
                ET.SubElement(tc, "failure", message=c.get("reason", "")[:500])
            elif c["outcome"] in ("skip", "xfail", "disabled", "not_implemented"):
                ET.SubElement(tc, "skipped", message=f"{c['outcome']}: {c.get('reason', '')[:300]}")
    ET.ElementTree(suites).write(path, encoding="utf-8", xml_declaration=True)


_CSS = """
:root{--canvas:#07080A;--card:#0E1013;--line:#1C2026;--text:#E6E8EB;--mute:#8A93A0;--iris:#6D5DFC;
--allow:#10B981;--redact:#F59E0B;--approval:#8B5CF6;--block:#F43F5E;--log:#64748B}
*{box-sizing:border-box}body{margin:0;background:var(--canvas);color:var(--text);
font:14px/1.45 -apple-system,BlinkMacSystemFont,"Inter","Segoe UI",sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:22px;margin:0 0 4px;letter-spacing:-.01em}h1 b{color:var(--iris)}
h2{font-size:15px;margin:28px 0 10px;color:var(--mute);text-transform:uppercase;letter-spacing:.08em}
.sub{color:var(--mute);font:12px ui-monospace,"JetBrains Mono",monospace}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi .v{font-size:26px;font-weight:650;font-variant-numeric:tabular-nums}.kpi .l{color:var(--mute);font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:auto}
table{border-collapse:collapse;width:100%}th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;
font-variant-numeric:tabular-nums;white-space:nowrap}th{color:var(--mute);font-weight:500;font-size:12px;position:sticky;top:0;background:var(--card)}
td.n{white-space:normal}tr:hover td{background:#12151A}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600;border:1px solid}
.PASS{color:var(--allow);border-color:#10B98155}.FAIL{color:var(--block);border-color:#F43F5E55}
.PARTIAL{color:var(--redact);border-color:#F59E0B55}.UNTESTED{color:#E879F9;border-color:#E879F955}
.DISABLED,.NOT_IMPLEMENTED{color:var(--log);border-color:#64748B55}.SKIPPED{color:#22D3EE;border-color:#22D3EE55}
.pass{color:var(--allow)}.pass_other{color:var(--redact)}.fail{color:var(--block)}.skip,.xfail,.disabled,.not_implemented{color:var(--log)}
.a-allow,.a-log{color:var(--allow)}.a-redact{color:var(--redact)}.a-require_approval{color:var(--approval)}.a-block{color:var(--block)}
input,select{background:#0B0D10;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
.bar{display:flex;gap:8px;margin:0 0 10px;flex-wrap:wrap}.mono{font-family:ui-monospace,"JetBrains Mono",monospace;font-size:12px}
.foot{color:var(--mute);font-size:12px;margin-top:30px}.err{border-color:#F43F5E55;color:#FDA4AF;padding:12px}
"""

_JS = """
const q=document.getElementById('q'),f=document.getElementById('f');
function apply(){const t=q.value.toLowerCase(),o=f.value;document.querySelectorAll('#cases tbody tr').forEach(r=>{
const ok=(!t||r.textContent.toLowerCase().includes(t))&&(!o||r.dataset.o===o);r.style.display=ok?'':'none';});}
q.addEventListener('input',apply);f.addEventListener('change',apply);
document.querySelectorAll('[data-ctl]').forEach(el=>el.addEventListener('click',()=>{q.value=el.dataset.ctl;apply();
document.getElementById('cases').scrollIntoView({behavior:'smooth'});}));
"""


def _e(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def selftest_html(rep: dict[str, Any]) -> str:
    t = rep["totals"]
    g = rep["gateway"]
    kpis = [
        ("Cases", t["cases"]),
        ("Pass", t["passed"] + t["pass_other"]),
        ("Fail", t["failed"]),
        ("xfail / not impl.", t["xfailed"]),
        ("UNTESTED controls", t["untested_controls"]),
        ("Duration", f"{rep['duration_s']} s"),
    ]
    perf = rep["perf"]
    rows = []
    for r in rep["controls"]:
        rows.append(
            f"<tr><td class=mono><a href='#cases' data-ctl='{_e(r['control_id'])}' style='color:inherit'>"
            f"{_e(r['control_id'])}</a></td><td class=n>{_e(r['name'])}{' <span class=sub>(stretch)</span>' if r.get('stretch') else ''}</td>"
            f"<td>{_cnt(r['attack'])}</td><td>{_cnt(r['benign'])}</td><td>{_cnt(r['redact'])}</td>"
            f"<td>{_cnt(r['error'])}</td><td>{r['other_control'] or ''}</td>"
            f"<td>{_e(r['p95_ms']) if r['p95_ms'] is not None else '–'}</td>"
            f"<td><span class='chip {r['status']}'>{r['status']}</span></td></tr>"
        )
    suites = "".join(
        f"<tr><td>{_e(s['title'])}</td><td>{s['passed']}/{s['total']}</td>"
        f"<td><span class='chip {s['status']}'>{s['status']}</span></td></tr>"
        for s in rep["suites"]
    )
    cases = []
    for c in rep["cases"]:
        cases.append(
            f"<tr data-o='{_e(c['outcome'])}'><td class=mono>{_e(c['id'])}</td><td class=mono>{_e(c.get('control'))}</td>"
            f"<td>{_e(c.get('suite'))}</td><td>{_e(c.get('via'))}</td>"
            f"<td class='a-{_e(c.get('expect'))}'>{_e(c.get('expect'))}</td>"
            f"<td class='a-{_e(c.get('got'))}'>{_e(c.get('got'))}</td><td class=mono>{_e(c.get('got_control'))}</td>"
            f"<td class='{_e(c['outcome'])}'>{_e(c['outcome'])}</td>"
            f"<td class='n mono'>{_e(c.get('preview'))}</td><td class=n>{_e(c.get('reason'))}</td></tr>"
        )
    failures = [c for c in rep["cases"] if c["outcome"] == "fail"]
    fail_html = "".join(
        f"<tr><td class=mono>{_e(c['id'])}</td><td>{_e(c.get('expect'))} → {_e(c.get('got'))}</td>"
        f"<td class=mono>{_e(c.get('got_control'))}</td><td class=mono>{_e(c.get('decision_id'))}</td>"
        f"<td class=n>{_e(c.get('reason'))}</td></tr>"
        for c in failures
    )
    tags: dict[str, list[int]] = {}
    for c in rep["cases"]:
        for tg in c.get("tags", []):
            if tg.startswith(("owasp:", "atlas:")):
                p = tags.setdefault(tg, [0, 0])
                p[1] += 1
                p[0] += c["outcome"] in ("pass", "pass_other")
    tag_html = "".join(
        f"<tr><td class=mono>{_e(k)}</td><td>{v[0]}/{v[1]}</td></tr>"
        for k, v in sorted(tags.items())
    )
    untested = [r["control_id"] for r in rep["controls"] if r["status"] == "UNTESTED"]
    ev = rep.get("evidence") or {}
    ev_html = "".join(
        f"<div class=kpi><div class=l>{_e(k)}.json</div><div class=mono>{_e(json.dumps(v)[:300])}</div></div>"
        for k, v in ev.items()
        if v
    )
    obf = rep.get("obfuscation")
    obf_html = ""
    if obf and obf.get("cells"):
        seeds, trs = obf["seeds"], obf["transforms"]
        cell = {(s, t_): o for s, t_, o in obf["cells"]}
        head = "".join(f"<th>{_e(t_)}</th>" for t_ in trs)
        body = "".join(
            "<tr><td class=mono>"
            + _e(s)
            + "</td>"
            + "".join(
                f"<td class='{ {'pass': 'pass', 'fail': 'fail'}.get(cell.get((s, t_), 'skip'), 'skip') }'>"
                f"{ {'pass': '●', 'fail': '✕'}.get(cell.get((s, t_), 'skip'), '·') }</td>"
                for t_ in trs
            )
            + "</tr>"
            for s in seeds
        )
        obf_html = f"<h2>Obfuscation heatmap</h2><div class=card><table><tr><th>seed</th>{head}</tr>{body}</table></div>"
    err_html = (
        f"<div class='card err'>Gateway boot error: {_e(rep['stack_error'])}</div>"
        if rep.get("stack_error")
        else ""
    )
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><meta name=color-scheme content=dark>
<title>Aegis self-test</title><style>{_CSS}</style></head><body><div class=wrap>
<h1><b>Aegis</b> self-test report</h1>
<div class=sub>{_e(header_line(rep))} · generated {_e(rep["generated_at"])}</div>{err_html}
<div class=kpis>{"".join(f"<div class=kpi><div class=v>{_e(v)}</div><div class=l>{_e(lbl)}</div></div>" for lbl, v in kpis)}</div>
<h2>Per-control matrix</h2><div class=card><table><tr><th>Control</th><th>Name</th><th>Attack</th><th>Benign</th>
<th>Redact</th><th>Error</th><th>Other</th><th>p95 ms</th><th>Status</th></tr>{"".join(rows)}</table></div>
{f"<h2>Functional suites</h2><div class=card><table><tr><th>Suite</th><th>Passed</th><th>Status</th></tr>{suites}</table></div>" if suites else ""}
<h2>Coverage</h2><div class='card' style='padding:12px'>{("UNTESTED: " + ", ".join(untested)) if untested else "Every catalog control has at least one must-block and one must-allow case."}</div>
{f"<h2>Failures</h2><div class=card><table><tr><th>Case</th><th>Expected → got</th><th>Control</th><th>Decision</th><th>Reason</th></tr>{fail_html}</table></div>" if failures else ""}
<h2>Performance</h2><div class=kpis>{"".join(f"<div class=kpi><div class=v>{_e(v) if v is not None else '–'}</div><div class=l>{_e(k)}</div></div>" for k, v in perf.items())}</div>
{f"<h2>OWASP / ATLAS tags</h2><div class=card><table><tr><th>Tag</th><th>Passed</th></tr>{tag_html}</table></div>" if tag_html else ""}
{obf_html}
{f"<h2>Evidence</h2><div class=kpis>{ev_html}</div>" if ev_html else ""}
<h2 id=cases>Cases</h2><div class=bar><input id=q placeholder="filter (id, control, text)…" size=40>
<select id=f><option value="">all outcomes</option><option>pass</option><option>pass_other</option><option>fail</option>
<option>xfail</option><option>skip</option><option>disabled</option><option>not_implemented</option></select></div>
<div class=card><table id=cases><thead><tr><th>Case</th><th>Control</th><th>Suite</th><th>Via</th><th>Expect</th><th>Got</th>
<th>By</th><th>Outcome</th><th>Preview (masked)</th><th>Reason</th></tr></thead><tbody>{"".join(cases)}</tbody></table></div>
<div class=foot>Gateway {_e(g.get("url"))} · all inputs are fake test data; previews are masked and truncated.</div>
</div><script>{_JS}</script></body></html>"""


def write_all(
    reports: Path, rec: Recorder | None = None, duration_s: float = 0.0
) -> dict[str, Any]:
    reports.mkdir(parents=True, exist_ok=True)
    rep = build_report(rec, duration_s, reports)
    (reports / "results.json").write_text(json.dumps(rep, indent=2, default=str))
    (reports / "matrix.md").write_text(matrix_markdown(rep))
    (reports / "selftest.html").write_text(selftest_html(rep))
    write_junit(rep, reports / "junit.xml")
    return rep


def console(rep: dict[str, Any], write: Any = print) -> None:
    """Coloured matrix through `write(line, **markup)` (pytest TerminalReporter.write_line)."""
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:  # pragma: no cover
        write(matrix_markdown(rep))
        return
    tab = Table(title=header_line(rep), title_justify="left", show_lines=False, pad_edge=False)
    for col in (
        "CONTROL",
        "NAME",
        "ATTACK",
        "BENIGN",
        "REDACT",
        "ERROR",
        "OTHER",
        "p95 ms",
        "STATUS",
    ):
        tab.add_column(col, no_wrap=col != "NAME")
    for r in rep["controls"]:
        st = r["status"]
        tab.add_row(
            r["control_id"],
            r["name"][:34],
            _cnt(r["attack"]),
            _cnt(r["benign"]),
            _cnt(r["redact"]),
            _cnt(r["error"]),
            str(r["other_control"] or 0),
            str(r["p95_ms"]) if r["p95_ms"] is not None else "–",
            f"[{STATUS_COLOR.get(st, 'white')}]{st}[/]",
        )
    con = Console(width=150, force_terminal=True, color_system="standard", record=True)
    with con.capture() as cap:
        con.print(tab)
        if rep["suites"]:
            con.print(
                "SUITE  "
                + " · ".join(f"{s['title']} {s['passed']}/{s['total']}" for s in rep["suites"])
            )
        t = rep["totals"]
        con.print(
            f"[bold]TOTAL[/] {t['cases']} cases · [green]{t['passed']} pass[/] · "
            f"[yellow]{t['pass_other']} pass(other control)[/] · {t['xfailed']} xfail · "
            f"[red]{t['failed']} fail[/] · {t['skipped']} skip · {t['untested_controls']} UNTESTED · "
            f"{rep['duration_s']} s → reports/selftest.html"
        )
        failures = [c for c in rep["cases"] if c["outcome"] == "fail"][:25]
        for c in failures:
            con.print(f"  [red]FAIL[/] {c['id']} ({c.get('control')}): {c.get('reason', '')[:160]}")
    for line in cap.get().splitlines():
        write(line)


__all__ = [
    "build_report",
    "console",
    "header_line",
    "matrix_markdown",
    "selftest_html",
    "write_all",
    "write_junit",
]

_ = time
