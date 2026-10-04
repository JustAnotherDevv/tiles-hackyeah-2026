/* View 2 — Live decisions feed (+ trace drawer via A.openTrace) */
(function (A) {
  'use strict';
  const { $, $$, esc, fmtInt, fmtUsd, fmtMs, clock, compact } = A.u;
  const F = { q: '', d: 'all', s: 'all', a: 'all' };
  const SURFACES = ['llm.request', 'llm.response', 'tool.call', 'tool.result', 'tool.list', 'http.egress', 'package.install'];

  const match = (e) => (F.d === 'all' || (F.d === 'downgrade' ? e.tag === 'downgraded' : e.decision === F.d)) && (F.s === 'all' || e.surface === F.s) && (F.a === 'all' || e.agent === F.a) &&
    (!F.q || (e.text + ' ' + e.agent + ' ' + (e.ctl || '') + ' ' + e.id).toLowerCase().indexOf(F.q.toLowerCase()) >= 0);

  const hl = (s) => s.replace(/⟨[^⟩]+⟩/g, (m) => '<span class="ph">' + m + '</span>');
  const row = (e, isNew) => {
    const d = e.tag === 'downgraded' ? 'downgrade' : e.decision;
    return '<tr class="clickable ' + (isNew ? 'new ' + (e.decision === 'block' ? 'block' : '') : '') + '" data-id="' + e.id + '">' +
      '<td class="mono muted" style="font-size:11.5px">' + clock(e.ts) + '</td>' +
      '<td>' + A.h.badge(d) + '</td>' +
      '<td><span style="font-weight:500">' + esc(e.agent) + '</span></td>' +
      '<td><span class="tag">' + esc(e.surface) + '</span></td>' +
      '<td><div class="cell-summary ' + (/tool|egress|package/.test(e.surface) ? 'mono' : '') + '">' + hl(esc(e.text)) + '</div></td>' +
      '<td class="mono" style="font-size:11.5px;color:' + (e.ctl ? 'var(--text-1)' : 'var(--text-4)') + '">' + esc(e.ctl || '—') + '</td>' +
      '<td class="r mono" style="font-size:11.5px">' + fmtMs(e.overhead) + '</td>' +
      '<td class="r mono muted" style="font-size:11.5px">' + (e.cost ? fmtUsd(e.cost, 4) : e.avoided ? '<span class="c-allow">−' + fmtUsd(e.avoided, 3) + '</span>' : '—') + '</td></tr>';
  };

  const chips = () => {
    const c = A.state.counts;
    const list = [['all', 'All', c.requests, null], ['allow', 'Allow', c.allow, 'var(--allow)'], ['redact', 'Redact', c.redacted, 'var(--redact)'], ['approval', 'Approval', c.approval, 'var(--approval)'], ['block', 'Block', c.blocked, 'var(--block)']];
    return list.map((x) => '<button class="chip ' + (F.d === x[0] ? 'on' : '') + '" data-d="' + x[0] + '">' + (x[3] ? '<span class="sw" style="background:' + x[3] + '"></span>' : '') + x[1] + '<span class="n">' + compact(x[2]) + '</span></button>').join('');
  };

  const fillTable = () => {
    const tb = $('#lv-body'); if (!tb) return;
    const rows = A.state.events.filter(match).slice(0, 150);
    tb.innerHTML = rows.map((e) => row(e)).join('') || '<tr><td colspan="8"><div class="empty">' + A.icon('filter', 18) + '<div style="margin-top:8px">No decisions match these filters yet.</div></div></td></tr>';
    $('#lv-count').textContent = 'Showing ' + rows.length + ' of ' + fmtInt(A.state.counts.requests) + ' decisions (24h)';
  };

  const liveBtn = () => '<button class="btn secondary" id="lv-live">' + (A.state.live ? '<span class="live-dot"></span>Live' : A.icon('play', 13) + 'Paused') + '</button>';

  A.views.live = {
    render(root) {
      const agents = A.agents.map((a) => a.id);
      root.innerHTML =
        '<div class="page-head"><div><h1 class="page-title">Live decisions</h1><div class="page-sub">Every prompt, response, tool call, MCP message and egress request — decided in-line, explained, and hash-chained to the audit log.</div></div>' +
        '<div class="actions"><span id="lv-live-wrap">' + liveBtn() + '</span><button class="btn secondary" id="lv-sim">' + A.icon('zap', 14) + 'Simulate' + A.icon('chevDown', 13) + '</button><button class="btn secondary" id="lv-export">' + A.icon('download', 14) + 'Export' + A.icon('chevDown', 13) + '</button></div></div>' +
        '<div class="row mb-3" style="flex-wrap:wrap;gap:8px"><div class="input-wrap" style="width:260px">' + A.icon('search', 14) + '<input class="input" id="lv-q" placeholder="Filter by text, agent, control, request id" style="width:100%" value="' + esc(F.q) + '"></div>' +
        '<div class="row" id="lv-chips" style="gap:6px;flex-wrap:wrap">' + chips() + '</div><span class="grow"></span>' +
        '<select class="select" id="lv-s"><option value="all">All surfaces</option>' + SURFACES.map((s) => '<option ' + (F.s === s ? 'selected' : '') + '>' + s + '</option>').join('') + '</select>' +
        '<select class="select" id="lv-a"><option value="all">All agents</option>' + agents.map((s) => '<option ' + (F.a === s ? 'selected' : '') + '>' + s + '</option>').join('') + '</select></div>' +
        '<div class="card"><div class="table-scroll" style="max-height:calc(100vh - 290px)"><table class="table"><thead><tr><th style="width:80px">Time</th><th style="width:104px">Decision</th><th>Agent</th><th>Surface</th><th>Request / action</th><th>Control</th><th class="r">Overhead</th><th class="r">Cost</th></tr></thead><tbody id="lv-body"></tbody></table></div>' +
        '<div class="card-f"><span id="lv-count"></span><span class="grow"></span>' + A.icon('hash', 13) + '<span class="mono">audit chain verified · head sha256:41d9…c07e</span><span class="badge allow"><span class="dot"></span>OK</span></div></div>';
      fillTable();

      $('#lv-q').addEventListener('input', A.u.debounce((ev) => { F.q = ev.target.value; fillTable(); }, 120));
      $('#lv-s').addEventListener('change', (ev) => { F.s = ev.target.value; fillTable(); });
      $('#lv-a').addEventListener('change', (ev) => { F.a = ev.target.value; fillTable(); });
      $('#lv-chips').addEventListener('click', (ev) => { const b = ev.target.closest('.chip'); if (!b) return; F.d = b.dataset.d; $$('.chip', $('#lv-chips')).forEach((x) => x.classList.toggle('on', x === b)); fillTable(); });
      $('#lv-body').addEventListener('click', (ev) => { const tr = ev.target.closest('tr[data-id]'); if (!tr) return; $$('#lv-body tr').forEach((x) => x.classList.toggle('selected', x === tr)); const e = A.state.events.find((x) => x.id === tr.dataset.id); if (e) A.openTrace(e); });
      $('#lv-live-wrap').addEventListener('click', () => { A.setLive(!A.state.live); const w = $('#lv-live-wrap'); w.dataset.live = String(A.state.live); w.innerHTML = liveBtn(); });
      $('#lv-sim').addEventListener('click', (ev) => { ev.stopPropagation(); A.menu.open(ev.currentTarget, [{ group: 'Inject a test request' }].concat(A.presets.map((p) => ({ icon: 'zap', label: p.label, onClick: () => { const e = A.emitTemplate(A.templates[p.idx]); setTimeout(() => A.openTrace(e), 120); } })))); });
      $('#lv-export').addEventListener('click', (ev) => { ev.stopPropagation(); A.menu.open(ev.currentTarget, [{ group: 'Export audit log (24h)' }, { icon: 'download', label: 'JSONL · aicl.audit/1', hint: '48k', onClick: () => exp('jsonl') }, { icon: 'download', label: 'CSV', onClick: () => exp('csv') }, { icon: 'download', label: 'OCSF 1.9 (SIEM)', hint: '2004 · 6003', onClick: () => exp('ocsf.json') }]); });
      const exp = (f) => A.toast({ type: 'success', icon: 'download', title: 'Audit export ready', desc: fmtInt(A.state.counts.requests) + ' records · hash chain verified before export', meta: 'aegis-audit-2026-10-03.' + f });
    },
    onEvent(e) {
      const tb = $('#lv-body'); if (!tb) return;
      $('#lv-chips').innerHTML = chips();
      if (!match(e)) return;
      const empty = tb.querySelector('.empty'); if (empty) tb.innerHTML = '';
      tb.insertAdjacentHTML('afterbegin', row(e, true));
      while (tb.children.length > 150) tb.lastElementChild.remove();
      $('#lv-count').textContent = 'Showing ' + tb.children.length + ' of ' + fmtInt(A.state.counts.requests) + ' decisions (24h)';
    },
    onTick() { const w = $('#lv-live-wrap'); if (w && w.dataset.live !== String(A.state.live)) { w.dataset.live = String(A.state.live); w.innerHTML = liveBtn(); } }
  };
})(window.A);
