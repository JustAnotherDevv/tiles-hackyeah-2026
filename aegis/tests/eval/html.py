"""Self-contained dark HTML reports (stdlib only; tokens from staging/design/DESIGN_TOKENS.md)."""

from __future__ import annotations

from html import escape
from typing import Any

from tests.corpora.obfuscate import TRANSFORMS

CSS = """
:root{--bg:#07080A;--s1:#0E1013;--s2:#13161A;--s3:#191C21;--b:#1E2228;--bs:#15181C;--t1:#ECEEF1;--t2:#A2A8B3;
--t3:#7A808C;--iris:#9A8CFF;--allow:#3CCB7F;--redact:#5BA4F5;--approval:#E8A93A;--block:#F2556F;
--m-allow:#1E9F68;--m-redact:#3987E5;--m-approval:#C98500;--m-block:#E5446D;--log:#8C93A0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t1);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Inter","Segoe UI",sans-serif;padding:32px 16px}
main{max-width:1180px;margin:0 auto}h1{font-size:24px;margin:0 0 4px}h2{font-size:16px;margin:32px 0 12px;
color:var(--t1)}.sub{color:var(--t3);font-size:13px}.card{background:var(--s1);border:1px solid var(--b);
border-radius:12px;padding:16px 18px;margin:12px 0;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}th{color:var(--t3);font-weight:500;text-align:left;
padding:6px 8px;border-bottom:1px solid var(--b);white-space:nowrap}td{padding:6px 8px;border-bottom:1px solid
var(--bs);vertical-align:middle}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.mono{font-family:"Geist Mono",ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.kpi{background:var(--s1);border:1px solid var(--b);border-radius:12px;padding:14px 16px}
.kpi .v{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums}.kpi .l{color:var(--t3);font-size:12px}
.kpi .c{color:var(--t2);font-size:12px}.bar{position:relative;height:8px;background:var(--s3);border-radius:4px;
min-width:120px}.bar i{position:absolute;top:0;bottom:0;border-radius:4px}.bar b{position:absolute;top:-3px;
bottom:-3px;border-left:1px solid var(--t2);border-right:1px solid var(--t2)}
.tag{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;border:1px solid var(--b);color:var(--t2)}
.t-block{color:var(--block);border-color:rgba(242,85,111,.3);background:rgba(242,85,111,.1)}
.t-redact{color:var(--redact);border-color:rgba(91,164,245,.28);background:rgba(91,164,245,.1)}
.t-require_approval{color:var(--approval);border-color:rgba(232,169,58,.28);background:rgba(232,169,58,.1)}
.t-allow{color:var(--allow);border-color:rgba(60,203,127,.26);background:rgba(60,203,127,.1)}
.t-log{color:var(--log)}.foot{color:var(--t3);font-size:12px;margin-top:32px}
.legend span{margin-right:14px;font-size:12px;color:var(--t2)}.legend i{display:inline-block;width:10px;height:10px;
border-radius:2px;margin-right:5px;vertical-align:-1px}
"""

ACTION_FILL = {"block": "var(--m-block)", "redact": "var(--m-redact)", "require_approval": "var(--m-approval)",
               "allow": "var(--m-allow)", "log": "#3a3f48", "error": "#5a2a34"}


def _pct(x: float | None, nd: int = 1) -> str:
    return "not measured" if x is None else f"{x * 100:.{nd}f}%"


def _ci(c: Any) -> str:
    return "" if not c else f"[{c[0] * 100:.1f}–{c[1] * 100:.1f}]"


def _bar(rate: float | None, c: Any, color: str) -> str:
    if rate is None:
        return '<span class="sub">–</span>'
    w = f'<i style="left:0;width:{rate * 100:.1f}%;background:{color}"></i>'
    if c:
        w += f'<b style="left:{c[0] * 100:.1f}%;width:{max(0.5, (c[1] - c[0]) * 100):.1f}%"></b>'
    return f'<div class="bar">{w}</div>'


def _tag(action: str | None) -> str:
    a = action or "–"
    return f'<span class="tag t-{escape(a)}">{escape(a)}</span>'


def page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{escape(title)}</title><style>{CSS}</style>'
            f"</head><body><main>{body}</main></body></html>\n")


def heatmap_svg(hm: dict[str, Any]) -> str:
    ts = [t["id"] for t in hm["transforms"]]
    cw, ch, lw, th = 52, 22, 96, 70
    w = lw + cw * len(ts) + 60
    h = th + ch * len(hm["seeds"]) + 30
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" role="img" '
           f'aria-label="obfuscation heatmap" font-family="ui-monospace,Menlo,monospace" font-size="10">']
    for j, t in enumerate(ts):
        x = lw + j * cw + cw / 2
        out.append(f'<text x="{x}" y="{th - 8}" fill="#A2A8B3" transform="rotate(-35 {x} {th - 8})">{escape(t)}</text>')
    for i, (seed, row) in enumerate(zip(hm["seeds"], hm["cells"], strict=False)):
        y = th + i * ch
        out.append(f'<text x="0" y="{y + 15}" fill="#A2A8B3">{escape(seed["id"])}</text>')
        for j, c in enumerate(row):
            x = lw + j * cw
            if c is None:
                out.append(f'<rect x="{x + 1}" y="{y + 1}" width="{cw - 2}" height="{ch - 2}" rx="3" fill="#13161A" '
                           'stroke="#1E2228" stroke-dasharray="2 2"/>')
                continue
            fill = ACTION_FILL.get(c.get("action") or "", "#3a3f48")
            op = "1" if c.get("detected") else "0.35"
            tip = f'{seed["id"]} × {ts[j]}: {c.get("action")} {c.get("control_id") or ""}'
            out.append(f'<rect x="{x + 1}" y="{y + 1}" width="{cw - 2}" height="{ch - 2}" rx="3" fill="{fill}" '
                       f'opacity="{op}"><title>{escape(tip)}</title></rect>')
            if not c.get("detected"):
                out.append(f'<text x="{x + cw / 2 - 3}" y="{y + 15}" fill="#ECEEF1">·</text>')
        rr = hm["row_rate"][i]["rate"]
        out.append(f'<text x="{lw + cw * len(ts) + 6}" y="{y + 15}" fill="#ECEEF1">{_pct(rr, 0)}</text>')
    y = th + ch * len(hm["seeds"]) + 18
    for j, c in enumerate(hm["col_rate"]):
        out.append(f'<text x="{lw + j * cw + 12}" y="{y}" fill="#9A8CFF">{_pct(c["rate"], 0)}</text>')
    out.append("</svg>")
    return "".join(out)


def _legend() -> str:
    items = [("block", "var(--m-block)"), ("redact / quarantine", "var(--m-redact)"),
             ("approval", "var(--m-approval)"), ("allow (missed)", "var(--m-allow)")]
    return ('<div class="legend">' + "".join(f'<span><i style="background:{c}"></i>{escape(n)}</span>'
                                              for n, c in items)
            + '<span>faded cell = not detected · dashed = n/a</span></div>')


def eval_html(doc: dict[str, Any]) -> str:
    m = doc.get("machine", {})
    b: list[str] = [
        "<h1>Aegis red-team evaluation</h1>",
        f'<div class="sub">Generated {escape(str(doc.get("generated_at")))} · {doc.get("duration_s")} s · '
        f'{escape(str(m.get("cpu")))} · {m.get("ram_gb")} GB · corpora {doc.get("corpora", {}).get("rows")} rows · '
        'every number measured against the real Aegis pipeline (in-process, dry-run); 95 % Wilson intervals</div>',
    ]
    runs = [r for r in doc["runs"] if r.get("overall")]
    bal = next((r for r in runs if r["profile"] == "balanced"), runs[0] if runs else None)
    if bal:
        ov = bal["overall"]
        ho = (bal.get("by_split") or {}).get("held_out", {})
        hm = doc.get("heatmap") or {}
        kp = [
            ("Attack detection · balanced", _pct(ov["attack"]["rate"]), _ci(ov["attack"]["ci95"]) + f' n={ov["attack"]["n"]}'),
            ("False-positive rate · balanced", _pct(ov["benign"]["fpr"]), _ci(ov["benign"]["ci95"]) + f' n={ov["benign"]["n"]}'),
            ("Held-out detection", _pct(ho.get("attack", {}).get("rate")), "public sets not used for tuning"),
            ("Obfuscation coverage", _pct((hm.get("overall") or {}).get("rate")),
             f'{(hm.get("overall") or {}).get("detected")}/{(hm.get("overall") or {}).get("n")} seed×transform'),
        ]
        b.append('<div class="kpis">' + "".join(
            f'<div class="kpi"><div class="l">{escape(lbl)}</div><div class="v">{escape(v)}</div>'
            f'<div class="c">{escape(c)}</div></div>' for lbl, v, c in kp) + "</div>")
    b.append("<h2>Detection and false positives per profile</h2><div class='card'><table><tr><th>profile</th>"
             "<th>mode</th><th class=n>n</th><th>attack detected</th><th></th><th>FPR</th><th></th>"
             "<th>held-out det.</th><th>EN</th><th>PL</th><th>DE</th><th class=n>errors</th></tr>")
    for r in doc["runs"]:
        if not r.get("overall"):
            b.append(f"<tr><td>{escape(r['profile'])}</td><td>{escape(r['mode'])}</td><td colspan=10 class=sub>"
                     f"{escape(str(r.get('status')))}: {escape(str(r.get('skipped') or r.get('reason') or ''))}</td></tr>")
            continue
        ov = r["overall"]
        bl = r.get("by_lang") or {}
        ho = (r.get("by_split") or {}).get("held_out", {})

        def lg(k: str, bl: dict = bl) -> str:
            v = bl.get(k)
            return _pct(v["attack"]["rate"]) if v and v["attack"]["n"] else "–"

        b.append(
            f"<tr><td>{escape(r['profile'])}</td><td class=mono>{escape(r['mode'])}</td><td class=n>{r['n']}</td>"
            f"<td>{_pct(ov['attack']['rate'])} <span class=sub>{_ci(ov['attack']['ci95'])}</span></td>"
            f"<td>{_bar(ov['attack']['rate'], ov['attack']['ci95'], 'var(--m-allow)')}</td>"
            f"<td>{_pct(ov['benign']['fpr'])} <span class=sub>{_ci(ov['benign']['ci95'])}</span></td>"
            f"<td>{_bar(ov['benign']['fpr'], ov['benign']['ci95'], 'var(--m-block)')}</td>"
            f"<td>{_pct(ho.get('attack', {}).get('rate'))}</td><td>{lg('en')}</td><td>{lg('pl')}</td>"
            f"<td>{lg('de')}</td><td class=n>{r.get('errors')}</td></tr>")
    b.append("</table></div>")
    hm = doc.get("heatmap")
    if hm:
        b.append(f"<h2>Obfuscation heatmap · {escape(hm['profile'])} · {escape(hm['mode'])}</h2><div class=card>"
                 f"{_legend()}{heatmap_svg(hm)}<div class=sub>Benign twins (meaning-preserving transforms): "
                 f"{hm['benign']['over_block']}/{hm['benign']['n']} over-blocked.</div></div>")
    if bal:
        b.append("<h2>Balanced · by category</h2><div class=card><table><tr><th>category</th><th class=n>attacks</th>"
                 "<th>detected</th><th class=n>benign</th><th>FPR</th></tr>")
        for k, v in bal["by_category"].items():
            b.append(f"<tr><td class=mono>{escape(k)}</td><td class=n>{v['attack']['n']}</td>"
                     f"<td>{_pct(v['attack']['rate'])}</td><td class=n>{v['benign']['n']}</td>"
                     f"<td>{_pct(v['benign']['fpr'])}</td></tr>")
        b.append("</table></div><h2>Balanced · deciding controls</h2><div class=card><table><tr><th>control</th>"
                 "<th class=n>true positives</th><th class=n>false positives</th><th class=n>deciding</th></tr>")
        for c in bal["by_control"]:
            b.append(f"<tr><td class=mono>{escape(c['control_id'])}</td><td class=n>{c['tp']}</td>"
                     f"<td class=n>{c['fp']}</td><td class=n>{c['deciding']}</td></tr>")
        b.append("</table></div>")
        for title, key, tot in (("misses", "misses", "misses_total"),
                                ("false positives", "false_positives", "false_positives_total")):
            b.append(f"<h2>Balanced · {title} ({bal.get(tot)} total, first 20, masked)</h2><div class=card><table>"
                     "<tr><th>id</th><th>category</th><th>lang</th><th>action</th><th>control</th><th>preview</th></tr>")
            for it in bal[key]:
                b.append(f"<tr><td class=mono>{escape(it['id'])}</td><td class=mono>{escape(it['category'])}</td>"
                         f"<td>{escape(it['lang'])}</td><td>{_tag(it['action'])}</td>"
                         f"<td class=mono>{escape(str(it.get('control_id') or ''))}</td>"
                         f"<td>{escape(it.get('preview') or '')}</td></tr>")
            b.append("</table></div>")
    dlp = doc.get("dlp") or {}
    if dlp.get("runs"):
        b.append("<h2>End-to-end DLP leak leg</h2><div class=card><table><tr><th>profile</th><th>mode</th>"
                 "<th class=n>gold values</th><th class=n>leaked</th><th>leak rate</th><th>hard-neg. over-block</th>"
                 "<th>hard-neg. intervention</th></tr>")
        for d in dlp["runs"]:
            hn = d["hard_negatives"]
            b.append(f"<tr><td>{escape(d['profile'])}</td><td class=mono>{escape(d['mode'])}</td>"
                     f"<td class=n>{d['entities']}</td><td class=n>{d['leaked_entities']}</td>"
                     f"<td>{_pct(d['leak_rate'], 2)} <span class=sub>{_ci(d['leak_ci95'])}</span></td>"
                     f"<td>{_pct(hn['fpr'])}</td><td>{_pct(hn['intervention_rate'])}</td></tr>")
        b.append("</table></div>")
    b.append("<h2>Corpora</h2><div class=card><table><tr><th>file</th><th class=n>rows</th><th class=n>attack</th>"
             "<th class=n>benign</th><th>licence</th><th>used for tuning</th></tr>")
    for f in doc.get("corpora", {}).get("files", []):
        b.append(f"<tr><td class=mono>{escape(f['file'])}</td><td class=n>{f['rows']}</td>"
                 f"<td class=n>{f.get('attack')}</td><td class=n>{f.get('benign')}</td>"
                 f"<td>{escape(str(f.get('licence')))}</td><td>{'yes' if f.get('seen_by_tuning') else 'no'}</td></tr>")
    b.append("</table></div><div class=foot><b>Attribution.</b> " + " · ".join(escape(a) for a in doc.get("attribution", []))
             + "<br>External context (not our numbers): published PINT / model-card figures are cited in the pitch "
             "as third-party results only.</div>")
    return page("Aegis eval", "".join(b))


def bench_html(doc: dict[str, Any]) -> str:
    m = doc.get("machine", {})
    hl = doc.get("headline") or {}

    def ms(x: Any) -> str:
        return "not measured" if x is None else f"{x:.2f} ms"

    b = ["<h1>Aegis performance benchmark</h1>",
         f'<div class=sub>Generated {escape(str(doc.get("generated_at")))} · status {escape(str(doc.get("status")))} · '
         f'{escape(str(m.get("cpu")))} · {m.get("ram_gb")} GB · target {escape(str((doc.get("target") or {}).get("kind")))} · '
         f'{escape(str(m.get("load_generator") or ""))}</div>']
    kp = [("Overhead p50 · deterministic", ms(hl.get("det_overhead_p50_ms"))),
          ("Overhead p95 · deterministic", ms(hl.get("det_overhead_p95_ms"))),
          ("Throughput · deterministic", "not measured" if hl.get("rps_det") is None else f'{hl["rps_det"]:.0f} rps'),
          ("Share of an 800 ms upstream", "not measured" if hl.get("overhead_share_pct") is None
           else f'{hl["overhead_share_pct"]:.2f} %'),
          ("Overhead p95 · semantic", ms(hl.get("sem_overhead_p95_ms"))),
          ("Policy reload p95", ms(hl.get("reload_p95_ms")))]
    b.append('<div class="kpis">' + "".join(f'<div class="kpi"><div class="l">{escape(lbl)}</div>'
                                            f'<div class="v">{escape(v)}</div></div>' for lbl, v in kp) + "</div>")
    b.append("<h2>Load profiles</h2><div class=card><table><tr><th>profile</th><th>mode</th><th>path</th>"
             "<th class=n>c</th><th class=n>requests</th><th class=n>errors</th><th class=n>rps</th>"
             "<th class=n>overhead p50</th><th class=n>p95</th><th class=n>p99</th><th class=n>client p50</th></tr>")
    for p in doc.get("profiles", []):
        o = p.get("overhead_ms") or {}
        c = p.get("client_ms") or {}
        b.append(f"<tr><td class=mono>{escape(p['name'])}</td><td>{escape(p['mode'])}</td>"
                 f"<td class=mono>{escape(p['path'])}</td><td class=n>{p['concurrency']}</td>"
                 f"<td class=n>{p['requests']}</td><td class=n>{p['errors']}</td>"
                 f"<td class=n>{'' if p.get('rps') is None else f'{p['rps']:.0f}'}</td>"
                 f"<td class=n>{ms(o.get('p50'))}</td><td class=n>{ms(o.get('p95'))}</td><td class=n>{ms(o.get('p99'))}</td>"
                 f"<td class=n>{ms(c.get('p50'))}</td></tr>")
    b.append("</table></div>")
    share = doc.get("overhead_share")
    if share:
        b.append(f"<div class=card>Aegis adds <b>{ms(share.get('aegis_p50_ms'))}</b> (p50) to a "
                 f"{share.get('upstream_delay_ms')} ms upstream = <b>{share.get('share_pct')} %</b> "
                 f"<span class=sub>({escape(str(share.get('note')))})</span></div>")
    rows = doc.get("by_control") or []
    if rows:
        mx = max((r.get("p95_ms") or 0) for r in rows) or 1
        b.append("<h2>Per-control latency</h2><div class=card><table><tr><th>control</th><th>mode</th>"
                 "<th class=n>p50</th><th class=n>p95</th><th></th><th class=n>n</th><th>source</th></tr>")
        for r in rows:
            w = (r.get("p95_ms") or 0) / mx
            b.append(f"<tr><td class=mono>{escape(r['control_id'])}</td><td>{escape(str(r.get('mode', '')))}</td>"
                     f"<td class=n>{ms(r.get('p50_ms'))}</td><td class=n>{ms(r.get('p95_ms'))}</td>"
                     f"<td>{_bar(w, None, 'var(--m-redact)')}</td><td class=n>{r.get('count')}</td>"
                     f"<td class=sub>{escape(str(r.get('source')))}</td></tr>")
        b.append("</table></div>")
    rl = doc.get("reload")
    if rl:
        b.append(f"<h2>Policy reload</h2><div class=card class=mono>{escape(str(rl))}</div>")
    models = doc.get("models") or []
    if models:
        b.append("<h2>Model latency</h2><div class=card><table><tr><th>model</th><th>role</th><th class=n>p50</th>"
                 "<th class=n>p95</th><th>source</th></tr>")
        for mm in models:
            b.append(f"<tr><td class=mono>{escape(str(mm.get('name')))}</td><td>{escape(str(mm.get('role')))}</td>"
                     f"<td class=n>{ms(mm.get('p50_ms'))}</td><td class=n>{ms(mm.get('p95_ms'))}</td>"
                     f"<td class=sub>{escape(str(mm.get('source')))}</td></tr>")
        b.append("</table></div>")
    b.append("<div class=foot>Overhead = server-side <span class=mono>Server-Timing aegis</span> (falls back to verdict "
             "latency, then client time). The load generator is co-located (asyncio httpx); rps is a lower bound. "
             "Snapshot rows are labelled with their provenance and are not this run's numbers.</div>")
    return page("Aegis bench", "".join(b))


__all__ = ["TRANSFORMS", "bench_html", "eval_html", "heatmap_svg"]
