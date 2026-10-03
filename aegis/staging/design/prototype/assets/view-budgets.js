/* View 5 — Budgets: org → teams → agents */
(function (A) {
  'use strict';
  const { $, $$, esc, fmtUsd, fmtInt, compact } = A.u;
  let dim = 'usd';
  const open = { trading: true, eng: true };
  const TOK = 0.0000062;
  const fmtV = (usd) => dim === 'usd' ? fmtUsd(usd, usd >= 1000 ? 0 : 2) : compact(usd / TOK) + ' tok';
  const fmtL = (usd) => dim === 'usd' ? fmtUsd(usd, 0) : compact(usd / TOK) + ' tok';

  const statusHtml = (r) => { const st = A.budgetState(r); return '<span class="state"><span class="status-dot ' + A.stateDot[st] + '"></span>' + (st === 'ok' || st === 'watch' ? (st === 'ok' ? 'Healthy' : 'Watch') : st === 'soft' ? '<span class="c-downgrade">Downgrading</span>' : '<span class="c-block">Blocking · 402</span>') + '</span>'; };
  const usage = (used, limit) => { const r = used / limit; return '<div class="bt-usage"><div class="nums"><span><b>' + fmtV(used) + '</b> used</span><span>' + Math.round(r * 100) + '%</span></div>' + A.h.ubar(r, A.budgetState(r)) + '</div>'; };

  const treeHtml = () => {
    const o = A.orgBudget;
    let h = '<div class="bt-row" style="height:36px;font-size:11.5px;color:var(--text-3);background:var(--surface-1)"><span>Scope</span><span>Usage · October (markers: 80% soft · 100% hard)</span><span>Limit / mo</span><span>Status</span><span></span></div>';
    h += '<div class="bt-row org"><div class="bt-name"><span class="org-logo" style="width:28px;height:28px;border-radius:8px;font-size:11px">AC</span><div><div class="bt-title">Acme Capital</div><div class="bt-sub mono">org/acme-capital · hard cap</div></div></div>' + usage(o.used, o.limit) + '<div class="num">' + fmtL(o.limit) + '</div>' + statusHtml(o.used / o.limit) + '<div style="text-align:right"><button class="btn ghost sm" data-req="org">' + A.icon('sliders', 13) + 'Adjust</button></div></div>';
    A.teams.forEach((t) => {
      const agents = A.agents.filter((a) => a.team === t.id);
      h += '<div class="bt-row"><div class="bt-name"><button class="tw ' + (open[t.id] ? 'open' : '') + '" data-tw="' + t.id + '" aria-label="Toggle ' + esc(t.name) + '">' + A.icon('chevRight', 13) + '</button><span class="team-sw" style="background:var(--cat-' + t.cat + ')"></span><div style="min-width:0"><div class="bt-title">' + esc(t.name) + '</div><div class="bt-sub ellipsis"><span class="mono">team/' + t.id + '</span> · lead ' + esc(A.member(t.lead).name) + '</div></div></div>' + usage(t.used, t.limit) + '<div class="num">' + fmtL(t.limit) + '</div>' + statusHtml(t.used / t.limit) + '<div style="text-align:right"><button class="btn secondary sm" data-req="team:' + t.id + '">' + A.icon('plus', 13) + 'Request increase</button></div></div>';
      agents.forEach((a) => {
        h += '<div class="bt-row agent ' + (open[t.id] ? '' : 'hidden') + '" data-parent="' + t.id + '"><div class="bt-name"><span class="indent"></span>' + A.h.agentAv('sm') + '<div style="min-width:0"><div class="bt-title mono" style="font-size:12.5px">' + esc(a.id) + '</div><div class="bt-sub ellipsis">owner ' + esc(A.member(a.owner).name) + ' · ' + a.sessions + ' sessions · ' + esc(a.kind) + '</div></div></div>' + usage(a.used, a.limit) + '<div class="num t2">' + fmtL(a.limit) + '</div>' + statusHtml(a.used / a.limit) + '<div style="text-align:right"><button class="btn ghost sm" data-req="agent:' + a.id + '">' + A.icon('plus', 13) + 'Increase</button></div></div>';
      });
    });
    return h;
  };

  const routeFor = (cur, next) => {
    if (next <= cur) return { role: null, text: 'Decrease — applies immediately, no approval needed.' };
    const pct = (next - cur) / cur;
    if (pct <= 0.2) return { role: 'admin', text: '+' + Math.round(pct * 100) + '% ≤ 20% → routed to Admin' };
    return { role: 'owner', text: '+' + Math.round(pct * 100) + '% > 20% → routed to Owner (escalate_to_owner: budget_increase_over_20pct)' };
  };

  const openRequest = (key) => {
    const [kind, id] = key.split(':');
    const node = kind === 'org' ? { name: 'Acme Capital', scope: 'org/acme-capital', limit: A.orgBudget.limit, used: A.orgBudget.used, team: 'trading' } : kind === 'team' ? (() => { const t = A.team(id); return { name: t.name, scope: 'team/' + t.id, limit: t.limit, used: t.used, team: t.id }; })() : (() => { const a = A.agent(id); return { name: a.id, scope: 'agent/' + a.id, limit: a.limit, used: a.used, team: a.team }; })();
    const sugg = Math.ceil(node.limit * (kind === 'agent' ? 1.6 : 2) / 50) * 50;
    A.modal.open({
      title: 'Request budget increase', desc: 'Creates an approval request. Limits apply on the next request once approved — counters keep their usage.', width: 520,
      body: '<div class="kv" style="grid-template-columns:120px 1fr"><span class="k">Scope</span><span class="v mono">' + esc(node.scope) + '</span><span class="k">Current</span><span class="v">' + fmtUsd(node.used) + ' used of ' + fmtUsd(node.limit, 0) + ' / month (' + Math.round(node.used / node.limit * 100) + '%)</span></div>' +
        '<div class="row" style="gap:12px;align-items:flex-end"><div class="field grow"><label for="rq-new">New monthly limit (USD)</label><input class="input" id="rq-new" type="number" min="0" step="50" value="' + sugg + '"></div><div class="field" style="width:120px"><label>Window</label><input class="input" value="1 month · UTC" disabled></div></div>' +
        '<div class="field"><label for="rq-why">Justification</label><textarea class="input" id="rq-why" rows="3">Earnings season — sustained research and desk-copilot load through month end.</textarea></div>' +
        '<div class="lock-note" id="rq-route" style="border-style:solid"></div>',
      onMount: (w) => {
        const upd = () => { const v = +$('#rq-new', w).value || 0; const r = routeFor(node.limit, v); $('#rq-route', w).innerHTML = A.icon(r.role ? 'shield' : 'check', 15) + '<span>' + (r.role ? '<span class="role-badge ' + r.role + '" style="margin-right:6px">Requires ' + A.roles[r.role].label + '</span>' : '') + esc(r.text) + '</span>'; };
        $('#rq-new', w).addEventListener('input', upd); upd();
      },
      actions: [{ label: 'Cancel' }, { label: 'Submit request', kind: 'primary', icon: 'send', onClick: (w) => {
        const v = +$('#rq-new', w).value || 0; const r = routeFor(node.limit, v); const me = A.me();
        if (!r.role) { A.toast({ type: 'success', title: 'Limit lowered', desc: esc(node.scope) + ' → ' + fmtUsd(v, 0) + ' / month (applies on next request)' }); return; }
        A.addApproval({
          id: 'apr_01JB8' + A.u.ulid(5), kind: 'config', icon: 'wallet', title: 'Raise ' + node.name + ' monthly budget ' + fmtUsd(node.limit, 0) + ' → ' + fmtUsd(v, 0),
          subject: { type: 'member', id: me.id, team: node.team }, required: r.role, risk: r.role === 'owner' ? 'medium' : 'low',
          payload: '  budgets:\n    - scope: ' + node.scope + '\n-     usd: { limit: ' + node.limit + ', window: 1mo }\n+     usd: { limit: ' + v + ', window: 1mo }', diff: true,
          rule: 'approvals.config.change', ruleText: r.text.replace(/^\+\d+% /, ''), why: $('#rq-why', w).value,
          context: [['Current usage', fmtUsd(node.used) + ' / ' + fmtUsd(node.limit, 0)], ['Change', '+' + fmtUsd(v - node.limit, 0) + ' (+' + Math.round((v - node.limit) / node.limit * 100) + '%)'], ['Org cap headroom', fmtUsd(A.orgBudget.limit - A.orgBudget.used) + ' left']], signals: r.role === 'owner' ? ['> 20% increase'] : []
        });
        A.toast({ type: 'success', icon: 'send', title: 'Approval requested · routed to ' + A.roles[r.role].label, desc: esc(node.scope) + ' ' + fmtUsd(node.limit, 0) + ' → ' + fmtUsd(v, 0) + ' · expires in 24h', meta: 'see Approvals inbox' });
      } }]
    });
  };

  const draw = () => {
    $('#bt-tree').innerHTML = treeHtml(); A.growBars($('#bt-tree'));
  };

  const drawChart = () => {
    const el = $('#bt-chart'); if (!el) return;
    const days = []; for (let d = 1; d <= 31; d++) days.push('Oct ' + d);
    const actual = days.map((_, i) => i === 0 ? 690 : i === 1 ? 1420 : i === 2 ? A.orgBudget.used : null);
    const step = (A.orgBudget.forecast - A.orgBudget.used) / 28;
    const fc = days.map((_, i) => i < 2 ? null : +(A.orgBudget.used + step * (i - 2)).toFixed(0));
    A.charts.line(el, { labels: days, height: 268, xEvery: 5, fmtY: (v) => '$' + compact(v), fmtTip: (v) => fmtUsd(v, 0), refs: [{ y: A.orgBudget.limit, label: 'Org cap $8,000 · hard', color: '#C43350', textColor: '#F2556F' }], annotations: [{ i: 27, label: 'cap hit · Oct 28' }], series: [{ label: 'Actual', color: '#3987E5', values: actual, area: true, endDot: true }, { label: 'Forecast (7-day trend)', color: '#7A808C', values: fc, dash: true }], aria: 'Org spend October, actual and forecast' });
  };

  A.views.budgets = {
    render(root) {
      root.innerHTML =
        '<div class="page-head"><div><h1 class="page-title">Budgets</h1><div class="page-sub">Hierarchical limits — every request must pass every level: org → team → agent → session. Local models are priced per compute-second.</div></div>' +
        '<div class="actions">' + A.h.seg('bt-dim', [{ v: 'usd', l: 'USD' }, { v: 'tokens', l: 'Tokens' }], dim) + '<button class="btn primary" id="bt-req">' + A.icon('plus', 14) + 'Request increase</button></div></div>' +
        '<div class="grid g-12 mb-3"><div class="card span-8"><div class="card-h"><div><div class="card-title">Org spend · October</div><div class="card-sub">Cumulative, with month-end forecast from the 7-day trend</div></div><div class="right">' + A.charts.legend([{ c: '#3987E5', l: 'Actual', line: true }, { c: '#7A808C', l: 'Forecast', line: true, dash: true }, { c: '#C43350', l: 'Hard cap', line: true }]) + '</div></div>' +
        '<div class="card-b"><div class="row wrap-sm" style="gap:28px;margin-bottom:10px"><div><div class="t3" style="font-size:12px">Month to date</div><div style="font-size:26px;font-weight:600;letter-spacing:-0.03em" class="num">' + fmtUsd(A.orgBudget.used) + '</div></div><div><div class="t3" style="font-size:12px">Forecast</div><div style="font-size:26px;font-weight:600;letter-spacing:-0.03em" class="num c-approval">' + fmtUsd(A.orgBudget.forecast, 0) + '</div></div><div><div class="t3" style="font-size:12px">Local compute</div><div style="font-size:26px;font-weight:600;letter-spacing:-0.03em" class="num">' + fmtInt(A.orgBudget.localCompute.used) + '<span class="t3" style="font-size:14px;font-weight:500"> s</span></div></div></div><div class="chart" id="bt-chart"></div></div></div>' +
        '<div class="card span-4"><div class="card-h"><div><div class="card-title">Runaway & enforcement · 24h</div><div class="card-sub">Graduated ladder per control</div></div></div><div class="card-b">' +
        '<div class="row" style="flex-wrap:wrap;gap:4px;margin-bottom:14px">' + [['Warn', 'neutral'], ['Throttle 429', 'neutral'], ['Downgrade', 'downgrade'], ['Approval', 'approval'], ['Block 402', 'block'], ['Kill', 'block']].map((x, i) => (i ? '<span class="t4">' + A.icon('chevRight', 12) + '</span>' : '') + '<span class="badge ' + x[1] + '">' + x[0] + '</span>').join('') + '</div>' +
        [['refresh', 'Loop detections', 'LOOP-001…007', '64'], ['arrowDown', 'Model downgrades', 'sonnet → qwen3:4b', '212'], ['ban', 'Hard blocks', '402 budget_exceeded', '58'], ['clock', 'Over step cap', 'session max_steps 30', '3'], ['power', 'Kill switch', A.state.kill ? 'engaged' : 'not engaged', A.state.kill ? 'ON' : 'off']].map((x) => '<div class="sys-row" style="padding:9px 0;grid-template-columns:1fr auto"><span class="sn">' + A.icon(x[0], 14) + '<span>' + x[1] + '<span class="t3 mono" style="display:block;font-size:11px">' + x[2] + '</span></span></span><span class="num" style="font-size:16px;font-weight:600">' + x[3] + '</span></div>').join('') +
        '</div></div></div>' +
        '<div class="card"><div class="card-h bordered"><div><div class="card-title">Budget hierarchy</div><div class="card-sub">A request is checked and reserved atomically at every level; the first scope that trips is named in the 402.</div></div><div class="right"><button class="btn ghost sm" id="bt-expand">' + A.icon('chevUpDown', 13) + 'Expand all</button></div></div><div class="btree" id="bt-tree"></div></div>';
      draw();
      requestAnimationFrame(drawChart);
      A.segHandlers['bt-dim'] = (v) => { dim = v; draw(); };
      $('#bt-req').addEventListener('click', () => openRequest('team:trading'));
      $('#bt-expand').addEventListener('click', () => { const all = A.teams.every((t) => open[t.id]); A.teams.forEach((t) => { open[t.id] = !all; }); draw(); });
      $('#bt-tree').addEventListener('click', (ev) => {
        const tw = ev.target.closest('[data-tw]'); if (tw) { const id = tw.dataset.tw; open[id] = !open[id]; tw.classList.toggle('open', open[id]); $$('.bt-row[data-parent="' + id + '"]').forEach((r) => r.classList.toggle('hidden', !open[id])); return; }
        const rq = ev.target.closest('[data-req]'); if (rq) openRequest(rq.dataset.req);
      });
    },
    onResize() { drawChart(); }
  };
})(window.A);
