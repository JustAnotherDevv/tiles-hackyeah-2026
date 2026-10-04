/* View 1 — Command Center */
(function (A) {
  'use strict';
  const { $, $$, esc, fmtInt, fmtUsd, compact, ago, fmtMs } = A.u;
  const Ch = A.charts;
  const COL = { allow: '#1E9F68', redact: '#3987E5', approval: '#C98500', block: '#E5446D' };

  /* deterministic 24h series */
  const r = A.seeded(424242);
  const now = new Date();
  const hours = []; for (let i = 23; i >= 0; i--) { const d = new Date(now.getTime() - i * 3600e3); hours.push(d.getHours()); }
  const curve = hours.map((h) => 0.22 + 0.78 * Math.exp(-Math.pow(h - 13, 2) / (2 * 3.6 * 3.6)));
  const cs = curve.reduce((a, b) => a + b, 0);
  const req = curve.map((c) => Math.round(A.kpi.requests * c / cs * (0.92 + r() * 0.16)));
  const red = req.map((v) => Math.round(v * 0.081 * (0.8 + r() * 0.4)));
  const blk = req.map((v, i) => Math.round(v * 0.0266 * (0.7 + r() * 0.5) * (i >= 22 ? 1.9 : 1)));
  const apr = req.map((v) => Math.max(0, Math.round(v * 0.0008 * (0.4 + r() * 1.4))));
  const alw = req.map((v, i) => v - red[i] - blk[i] - apr[i]);
  const p50 = hours.map((h, i) => +(0.30 + 0.08 * curve[i] + r() * 0.05).toFixed(2));
  const p95 = hours.map((h, i) => +(0.92 + 0.38 * curve[i] + r() * 0.22 + (i === 16 ? 0.9 : 0)).toFixed(2));
  const labels = hours.map((h) => A.u.pad(h) + ':00');
  const blockSpark = blk.slice();
  const redSpark = red.slice();

  let mode = 'interventions', raf = null, tick = null;

  const kpiTile = (o) => '<div class="card kpi"><div class="kpi-label">' + A.icon(o.icon, 14) + o.label + (o.right ? '<span style="margin-left:auto">' + o.right + '</span>' : '') + '</div><div class="kpi-value" id="' + (o.id || '') + '"' + (o.val != null ? ' data-val="' + o.val + '"' : '') + '>' + o.value + '</div>' + (o.foot ? '<div class="kpi-foot">' + o.foot + '</div>' : '') + (o.spark ? '<div class="spark">' + o.spark + '</div>' : '') + (o.extra || '') + '</div>';

  const streamItem = (e, enter) => {
    const d = e.tag === 'downgraded' ? 'downgrade' : e.decision;
    return '<div class="stream-item ' + (enter ? 'enter' : '') + '" data-id="' + e.id + '"><div>' + A.h.badge(d) + '</div><div style="min-width:0"><div class="si-top"><span class="si-agent">' + esc(e.agent) + '</span><span class="tag">' + esc(e.surface) + '</span></div><div class="si-text">' + (e.ctl ? '<span class="mono t2" style="font-size:11px">' + esc(e.ctl) + '</span> · ' : '') + esc(e.text) + '</div></div><div class="si-time" data-ts="' + e.ts + '">' + ago(Date.now() - e.ts) + '</div></div>';
  };
  const tickerItem = (e) => {
    const d = e.tag === 'downgraded' ? 'downgrade' : e.decision;
    return '<span class="t-item" data-id="' + e.id + '">' + A.h.badge(d) + '<span class="ag">' + esc(e.agent) + '</span>' + (e.ctl ? '<span class="ctl">' + esc(e.ctl) + '</span>' : '<span class="ctl">' + esc(e.surface) + '</span>') + '<span class="t3" style="max-width:300px;overflow:hidden;text-overflow:ellipsis">' + esc(e.text) + '</span><span class="ms">' + fmtMs(e.overhead) + '</span></span>';
  };

  const drawCharts = () => {
    const c1 = $('#ov-decisions'); if (!c1) return;
    const series = mode === 'all'
      ? [{ label: 'Allow', color: COL.allow, values: alw }, { label: 'Redact', color: COL.redact, values: red }, { label: 'Approval', color: COL.approval, values: apr }, { label: 'Block', color: COL.block, values: blk }]
      : [{ label: 'Redact', color: COL.redact, values: red }, { label: 'Approval', color: COL.approval, values: apr }, { label: 'Block', color: COL.block, values: blk }];
    Ch.stacked(c1, { labels, series, height: 262, xEvery: 3, annotations: [{ i: 21, label: 'policy v13', flip: true }, { i: 23, label: 'v14 · feed #43', row: 1, flip: true }], tipTitle: (i) => labels[i] + ' – ' + A.u.pad((hours[i] + 1) % 24) + ':00', aria: 'Decisions per hour, last 24 hours' });
    $('#ov-dec-legend').innerHTML = Ch.legend(series.map((s) => ({ c: s.color, l: s.label })));
    const c2 = $('#ov-latency');
    Ch.line(c2, { labels, height: 196, xEvery: 6, endLabels: true, yMax: 3, fmtY: (v) => v === 0 ? '0' : (v < 1 ? v.toFixed(2) : v.toFixed(1)) + ' ms', series: [{ label: 'p95', color: '#D95926', values: p95, endDot: true }, { label: 'p50', color: '#3987E5', values: p50, area: true, endDot: true }], annotations: [{ i: 23, label: 'v14' }], aria: 'Gateway overhead p50 and p95' });
  };

  /* ---------- ticker (JS-driven so new events can be appended without a jump) ---------- */
  const startTicker = () => {
    const vp = $('#ticker-vp'), track = $('#ticker-track'); if (!vp) return;
    let offset = 0, last = performance.now(), hover = false, rr = 0;
    const queue = [];
    A.state.tickerQueue = queue;
    const fill = () => {
      while (track.scrollWidth + offset < vp.clientWidth + 120) {
        const e = queue.length ? queue.shift() : A.state.events[(rr++) % Math.min(A.state.events.length, 40)];
        if (!e) break;
        track.insertAdjacentHTML('beforeend', tickerItem(e));
      }
    };
    vp.addEventListener('mouseenter', () => { hover = true; });
    vp.addEventListener('mouseleave', () => { hover = false; });
    track.addEventListener('click', (ev) => { const it = ev.target.closest('.t-item'); if (!it) return; const e = A.state.events.find((x) => x.id === it.dataset.id); if (e) A.openTrace(e); });
    const frame = (t) => {
      const dt = Math.min(64, t - last); last = t;
      if (!hover) offset -= dt * 0.045;
      const first = track.firstElementChild;
      if (first && offset + first.offsetWidth < 0) { offset += first.offsetWidth; first.remove(); }
      fill();
      track.style.transform = 'translate3d(' + offset.toFixed(1) + 'px,0,0)';
      raf = requestAnimationFrame(frame);
    };
    fill();
    raf = requestAnimationFrame(frame);
  };

  A.views.overview = {
    render(root) {
      const S = A.state, k = A.kpi;
      const spendRatio = A.orgBudget.used / A.orgBudget.limit;
      root.innerHTML =
        '<div class="page-head"><div><h1 class="page-title">Command Center</h1><div class="page-sub">Acme Capital · Production · every model, tool, MCP and egress call through one policy decision point</div></div>' +
        '<div class="actions">' + A.h.seg('ov-range', [{ v: '1h', l: '1h' }, { v: '24h', l: '24h' }, { v: '7d', l: '7d' }], '24h') + '<button class="btn secondary" id="ov-export">' + A.icon('download', 14) + 'Export report</button></div></div>' +

        '<div class="grid g-6">' +
        kpiTile({ icon: 'activity', label: 'Requests · 24h', id: 'kpi-req', val: S.counts.requests, value: fmtInt(S.counts.requests), foot: '<span class="delta flat">▲ ' + k.requestsDelta + '%</span>vs yesterday', spark: Ch.spark(req, '#7A808C') }) +
        kpiTile({ icon: 'ban', label: 'Blocked', id: 'kpi-blk', val: S.counts.blocked, value: fmtInt(S.counts.blocked), foot: '<span class="delta down-good">▼ 8.1%</span>2.7% of traffic', spark: Ch.spark(blockSpark, COL.block) }) +
        kpiTile({ icon: 'eyeOff', label: 'Redacted', id: 'kpi-red', val: S.counts.redacted, value: fmtInt(S.counts.redacted), foot: '<span class="mono" style="color:var(--text-2)">' + fmtInt(k.entities) + '</span> entities tokenized', spark: Ch.spark(redSpark, COL.redact) }) +
        kpiTile({ icon: 'wallet', label: 'Spend vs budget · Oct', value: fmtUsd(A.orgBudget.used, 0) + '<small>/ ' + fmtUsd(A.orgBudget.limit, 0) + '</small>', foot: '<span class="c-approval row" style="gap:4px">' + A.icon('alert', 12) + 'forecast ' + fmtUsd(A.orgBudget.forecast, 0) + ' · 108%</span>', extra: '<div style="margin-top:8px">' + A.h.ubar(spendRatio, 'ok', 'thick') + '</div><div class="kpi-foot" style="margin-top:2px"><span>' + Math.round(spendRatio * 100) + '% used</span><span style="margin-left:auto">cap $8,000 · hard</span></div>' }) +
        kpiTile({ icon: 'trendDown', label: 'Cost avoided · 24h', id: 'kpi-avoid', val: S.counts.avoided, value: fmtUsd(S.counts.avoided), foot: 'blocks · downgrades · loop kills', spark: Ch.spark([12, 9, 14, 11, 16, 13, 19, 15, 22, 18, 25, 21, 28], '#1E9F68') }) +
        kpiTile({ icon: 'shieldCheck', label: 'Posture score', value: k.posture + '<small>/100</small>', right: '<span class="badge allow">A−</span>', foot: '2 findings to review', extra: '<div style="margin-top:10px;display:flex;gap:3px">' + [1, 1, 1, 1, 1, 1, 1, 1, 1, 0.2].map((v) => '<span style="flex:1;height:6px;border-radius:2px;background:' + (v === 1 ? 'var(--chart-allow)' : 'var(--surface-4)') + '"></span>').join('') + '</div>' }) +
        '</div>' +

        '<div class="ticker mt-3"><div class="t-label"><span class="live-dot ' + (S.live ? '' : 'paused') + '" id="tk-dot"></span>Live</div><div class="t-viewport" id="ticker-vp"><div class="t-track" id="ticker-track"></div></div></div>' +

        '<div class="grid g-12 mt-3">' +
        '<div class="card span-8"><div class="card-h"><div><div class="card-title">Decisions per hour</div><div class="card-sub">Annotated with policy and feed version changes</div></div><div class="right">' + A.h.seg('ov-mode', [{ v: 'interventions', l: 'Interventions' }, { v: 'all', l: 'All traffic' }], mode) + '</div></div>' +
        '<div class="card-b"><div id="ov-dec-legend" style="margin-bottom:10px"></div><div class="chart" id="ov-decisions"></div></div></div>' +
        '<div class="card span-4" style="display:flex;flex-direction:column"><div class="card-h bordered"><span class="live-dot ' + (S.live ? '' : 'paused') + '" id="st-dot"></span><div class="card-title">Live decisions</div><div class="right"><a class="btn ghost sm" href="#/live">View all' + A.icon('arrowRight', 13) + '</a></div></div><div class="stream" id="ov-stream" style="flex:1;min-height:300px;max-height:330px">' + S.events.slice(0, 9).map((e) => streamItem(e)).join('') + '</div></div>' +
        '</div>' +

        '<div class="grid g-12 mt-3">' +
        '<div class="card span-4"><div class="card-h"><div><div class="card-title">Spend by team · month to date</div><div class="card-sub">80% soft → downgrade · 100% hard → block</div></div><div class="right"><a class="btn ghost sm" href="#/budgets">Budgets' + A.icon('arrowRight', 13) + '</a></div></div><div class="card-b" style="display:flex;flex-direction:column;gap:14px;padding-top:16px">' +
        A.teams.map((t) => { const rr = t.used / t.limit, st = A.budgetState(rr); return '<div><div class="row" style="font-size:12.5px;margin-bottom:6px"><span class="sw" style="width:8px;height:8px;border-radius:2px;background:var(--cat-' + t.cat + ')"></span><span>' + esc(t.name) + '</span>' + (st === 'soft' ? '<span class="badge downgrade" style="height:18px">Downgrading</span>' : '') + '<span class="grow"></span><span class="num t2">' + fmtUsd(t.used, 0) + ' <span class="t3">/ ' + fmtUsd(t.limit, 0) + '</span></span><span class="num t3" style="width:38px;text-align:right">' + Math.round(rr * 100) + '%</span></div>' + A.h.ubar(rr, st) + '</div>'; }).join('') +
        '</div></div>' +
        '<div class="card span-4"><div class="card-h"><div><div class="card-title">Top controls fired · 24h</div><div class="card-sub">Which control decided, by outcome</div></div></div><div class="card-b"><div style="margin-bottom:10px">' + Ch.legend([{ c: COL.redact, l: 'Redact' }, { c: COL.block, l: 'Block' }, { c: COL.approval, l: 'Approval' }]) + '</div>' +
        Ch.hbars(A.topControls.map((c) => ({ id: c.id, label: c.label, value: c.n, color: COL[c.kind], kindLabel: c.kind[0].toUpperCase() + c.kind.slice(1) }))) + '</div></div>' +
        '<div class="card span-4"><div class="card-h"><div><div class="card-title">System status</div><div class="card-sub">Fail-closed controls · warm models</div></div><div class="right"><span class="badge allow"><span class="dot"></span>Operational</span></div></div>' +
        '<div class="card-b" style="padding-bottom:6px"><div class="ring-wrap">' + Ch.ring(92, { size: 72, stroke: 7, label: '92', fs: 20 }) + '<div class="posture-list">' +
        [['Controls enabled', '31 / 32'], ['Self-tests passing', '142 / 142'], ['Feed freshness', '#' + S.feedSerial + ' · 2m'], ['Audit chain', 'verified']].map((p) => '<div class="pl"><span class="status-dot ok"></span>' + p[0] + '<b>' + p[1] + '</b></div>').join('') + '</div></div></div>' +
        '<div style="border-top:1px solid var(--border-subtle)">' +
        [['server', 'Gateway · 3 workers', 'p95 1.1 ms', 'ok'], ['fileCode', 'Policy engine', 'v' + S.policyVersion + ' · reload 184 ms', 'ok'], ['radar', 'Threat feed', '#' + S.feedSerial + ' · rejected #44', 'warn'], ['cpu', 'Ollama · qwen3:4b', 'warm · 1.6 GB', 'ok'], ['sparkles', 'Semantic judge', 'escalation 6%', 'ok']].map((s) => '<div class="sys-row"><span class="sn">' + A.icon(s[0], 14) + s[1] + '</span><span class="sv">' + s[2] + '</span><span class="status-dot ' + s[3] + '"></span></div>').join('') + '</div></div>' +
        '</div>' +

        '<div class="grid g-12 mt-3">' +
        '<div class="card span-7"><div class="card-h"><div><div class="card-title">Gateway overhead</div><div class="card-sub">Added latency per request, excluding upstream model time</div></div><div class="right">' + Ch.legend([{ c: '#3987E5', l: 'p50', line: true }, { c: '#D95926', l: 'p95', line: true }]) + '</div></div><div class="card-b"><div class="chart" id="ov-latency"></div>' +
        '<div class="row t3" style="font-size:12px;margin-top:8px;gap:16px"><span>Deterministic path p95 <b class="t1 num">1.1 ms</b></span><span>Overhead share <b class="t1 num">0.13%</b> of 820 ms model time</span><span>Hot reload p95 <b class="t1 num">184 ms</b></span></div></div></div>' +
        '<div class="card span-5"><div class="card-h"><div><div class="card-title">Attack surface · agent × category</div><div class="card-sub">Control hits, last 24h</div></div></div><div class="card-b">' + Ch.heatmap({ cats: A.heat.cats, rows: A.heat.rows }) + '</div></div>' +
        '</div>';

      A.segHandlers['ov-mode'] = (v) => { mode = v; drawCharts(); };
      A.segHandlers['ov-range'] = (v) => A.toast({ type: 'info', icon: 'clock', title: 'Range: ' + v, desc: 'Prototype shows the 24h dataset for every range.', duration: 2200 });
      $('#ov-export').addEventListener('click', () => A.toast({ type: 'success', icon: 'download', title: 'Management report exported', desc: 'PDF · spend vs budget, blocks, cost avoided, forecast', meta: 'acme-capital-ai-controls-2026-10-03.pdf' }));
      $('#ov-stream').addEventListener('click', (ev) => { const it = ev.target.closest('.stream-item'); if (!it) return; const e = A.state.events.find((x) => x.id === it.dataset.id); if (e) A.openTrace(e); });
      requestAnimationFrame(() => { drawCharts(); startTicker(); });
    },
    onEvent(e) {
      const S = A.state;
      A.tween($('#kpi-req'), S.counts.requests, fmtInt);
      if (e.decision === 'block') { A.tween($('#kpi-blk'), S.counts.blocked, fmtInt); const el = $('#kpi-blk'); if (el) { el.classList.remove('bump'); void el.offsetWidth; el.classList.add('bump'); } }
      if (e.decision === 'redact') A.tween($('#kpi-red'), S.counts.redacted, fmtInt);
      if (e.avoided) A.tween($('#kpi-avoid'), S.counts.avoided, (v) => fmtUsd(v));
      const st = $('#ov-stream');
      if (st) { st.insertAdjacentHTML('afterbegin', streamItem(e, true)); while (st.children.length > 10) st.lastElementChild.remove(); }
      if (S.tickerQueue) S.tickerQueue.push(e);
    },
    onTick() { $$('.si-time[data-ts]').forEach((t) => { t.textContent = ago(Date.now() - +t.dataset.ts); }); const live = A.state.live; ['#tk-dot', '#st-dot'].forEach((s) => { const d = $(s); if (d) d.classList.toggle('paused', !live); }); },
    onResize() { drawCharts(); },
    destroy() { if (raf) cancelAnimationFrame(raf); raf = null; A.state.tickerQueue = null; }
  };
})(window.A);
