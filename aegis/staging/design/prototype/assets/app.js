/* Aegis prototype — shell, router, shared decision-trace drawer, kill switch, commands, init. */
(function (A) {
  'use strict';
  const { $, $$, esc, fmtMs, fmtUsd, fmtInt, clock } = A.u;
  A.views = A.views || {};

  const NAV = [
    { group: 'Monitor' },
    { id: 'overview', label: 'Command Center', icon: 'gauge', key: 'c' },
    { id: 'live', label: 'Live Decisions', icon: 'activity', live: true, key: 'l' },
    { id: 'redaction', label: 'Redaction', icon: 'eyeOff', key: 'r' },
    { group: 'Govern' },
    { id: 'approvals', label: 'Approvals', icon: 'inbox', count: true, key: 'a' },
    { id: 'budgets', label: 'Budgets', icon: 'wallet', key: 'b' },
    { id: 'policy', label: 'Policy', icon: 'fileCode', key: 'p' },
    { group: 'Defend' },
    { id: 'feed', label: 'Threat Feed', icon: 'radar', key: 'f' },
    { group: 'Admin' },
    { id: 'org', label: 'Org & Roles', icon: 'users', key: 'o' }
  ];
  const TITLES = {}; NAV.forEach((n) => { if (n.id) TITLES[n.id] = n.label; });
  let current = null;

  /* ---------------- shell ---------------- */
  const renderNav = () => {
    const pending = A.state.approvals.length;
    $('#nav').innerHTML = NAV.map((n) => n.group ? '<div class="nav-group">' + n.group + '</div>' :
      '<a class="nav-item ' + (n.id === current ? 'active' : '') + '" href="#/' + n.id + '" data-tip="' + esc(n.label + ' · g then ' + n.key) + '">' + A.icon(n.icon, 16) + '<span>' + n.label + '</span>' +
      (n.live ? '<span class="live-dot ' + (A.state.live ? '' : 'paused') + '"></span>' : '') +
      (n.count && pending ? '<span class="count warn">' + pending + '</span>' : '') +
      (n.id === 'feed' && A.state.feedBanner ? '<span class="count" style="color:var(--block);border-color:var(--block-border);background:var(--block-subtle)">1</span>' : '') + '</a>').join('');
  };
  const renderSideFoot = () => {
    $('#side-foot').innerHTML =
      '<div class="health-line"><span class="status-dot ok"></span><span class="k">Gateway</span><span class="v">p95 1.1 ms</span></div>' +
      '<div class="health-line"><span class="status-dot ok"></span><span class="k">Policy</span><span class="v">v' + A.state.policyVersion + ' · hot</span></div>' +
      '<div class="health-line"><span class="status-dot ' + (A.state.feedBanner ? 'warn' : 'ok') + '"></span><span class="k">Feed</span><span class="v">#' + A.state.feedSerial + ' · ed25519</span></div>' +
      '<div class="health-line"><span class="status-dot ok"></span><span class="k">Audit chain</span><span class="v">verified</span></div>';
  };
  const renderTopbar = () => {
    $('#version-pill').innerHTML = A.icon('commit', 13) + 'policy v' + A.state.policyVersion + '<span class="sep">·</span>feed #' + A.state.feedSerial + '<span class="sep">·</span><span class="c-allow">chain ✓</span>';
    const k = A.state.kill;
    $('#kill-btn').innerHTML = (k ? '<span class="live-dot red"></span><span class="kl">Kill switch on</span>' : A.icon('power', 14) + '<span class="kl">Kill switch</span>');
    $('#role-seg').innerHTML = A.h.seg('role', [{ v: 'owner', l: 'Owner' }, { v: 'admin', l: 'Admin' }, { v: 'member', l: 'Member' }], A.state.role);
    const m = A.me();
    $('#me').innerHTML = A.h.avatar(m.name) + '<div class="me-txt"><div class="me-name">' + esc(m.name) + '</div><div class="me-role">' + esc(m.title) + '</div></div>';
    A.initSegs($('.topbar'));
    const kb = $('#killbar');
    if (k) {
      kb.classList.add('on');
      kb.innerHTML = A.icon('power', 15) + '<b>Kill switch engaged</b><span class="t2">· ' + esc(k.scope === 'global' ? 'all agents' : 'agent/' + k.agents.join(', ')) + ' · in-flight streams cancelled · by ' + esc(k.by) + ' at ' + k.at + '</span><span class="grow"></span><button class="btn sm secondary" id="kill-release">Release</button>';
      $('#kill-release').addEventListener('click', releaseKill);
    } else { kb.classList.remove('on'); kb.innerHTML = ''; }
  };
  A.refreshShell = () => { renderNav(); renderSideFoot(); renderTopbar(); };
  A.flashPill = () => { const p = $('#version-pill'); p.classList.remove('flash'); void p.offsetWidth; p.classList.add('flash'); };

  /* ---------------- router ---------------- */
  const route = () => {
    const id = (location.hash.replace(/^#\/?/, '') || 'overview').split('?')[0];
    const v = A.views[id] ? id : 'overview';
    if (current && A.views[current] && A.views[current].destroy) A.views[current].destroy();
    current = v; A.current = v;
    $('#crumb').textContent = TITLES[v];
    document.title = TITLES[v] + ' · Aegis';
    const root = $('#view');
    root.classList.remove('enter'); void root.offsetWidth; root.classList.add('enter');
    root.innerHTML = '';
    A.drawer.close(); A.tip.hide();
    A.views[v].render(root);
    A.initSegs(root); A.growBars(root); A.charts.animateRings(root);
    renderNav();
    $('#content').scrollTop = 0;
  };
  A.go = (id) => { if (location.hash === '#/' + id) route(); else location.hash = '#/' + id; };
  A.rerender = () => { const root = $('#view'); const st = $('#content').scrollTop; root.innerHTML = ''; A.views[current].render(root); A.initSegs(root); A.growBars(root); A.charts.animateRings(root); $('#content').scrollTop = st; };
  window.addEventListener('hashchange', route);

  /* ---------------- bus wiring ---------------- */
  A.segHandlers.role = (v) => A.setRole(v);
  A.bus.on('role', () => { renderTopbar(); const v = A.views[current]; if (v && v.onRole) v.onRole(); });
  A.bus.on('event', (e) => { const v = A.views[current]; if (v && v.onEvent) v.onEvent(e); });
  A.bus.on('approvals', () => renderNav());
  A.bus.on('live', () => renderNav());
  A.bus.on('versions', () => { renderTopbar(); renderSideFoot(); renderNav(); A.flashPill(); });
  setInterval(() => A.bus.emit('tick'), 1000);
  A.bus.on('tick', () => { const v = A.views[current]; if (v && v.onTick) v.onTick(); });
  let rw = window.innerWidth;
  window.addEventListener('resize', A.u.debounce(() => { A.initSegs(document); if (Math.abs(window.innerWidth - rw) > 4) { rw = window.innerWidth; const v = A.views[current]; if (v && v.onResize) v.onResize(); } }, 160));
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => A.initSegs(document));

  /* ---------------- decision trace drawer (shared) ---------------- */
  const STAGE_ICON = { pass: 'check', skip: 'skip', block: 'ban', redact: 'eyeOff', approval: 'clock', downgrade: 'arrowDown', allow: 'check' };
  const scoreText = (s) => {
    if (s.score == null || s.th == null) return '';
    const v = s.unit === 'used' ? Math.round(s.score * 100) + '%' : s.unit === 'repeats' ? s.score + '×' : s.score.toFixed(2);
    const t = s.unit === 'used' ? Math.round(s.th * 100) + '%' : s.unit === 'repeats' ? s.th + '×' : s.th.toFixed(2);
    return '<b>' + v + '</b><span>' + (s.score >= s.th ? '≥ ' : '< ') + t + '</span>';
  };
  A.openTrace = (e) => {
    const ag = A.agent(e.agent) || { team: 'eng' }; const team = A.team(e.team) || { name: '—' };
    const active = e.stages.filter((s) => s.status !== 'skip');
    const total = active.reduce((a, s) => a + s.ms, 0) || 1;
    let off = 0;
    const hitStage = e.stages.find((s) => s.status === 'hit');
    const stages = e.stages.map((s, i) => {
      let cls = s.status === 'hit' ? 'hit-' + s.hitClass : s.status === 'final' ? 'hit-' + (e.tag === 'downgraded' ? 'downgrade' : e.decision) : s.status;
      if (cls === 'hit-allow') cls = 'pass';
      const ico = s.status === 'hit' ? STAGE_ICON[s.hitClass] : s.status === 'final' ? 'shieldCheck' : STAGE_ICON[s.status];
      const fillCls = s.status === 'hit' ? s.hitClass : 'pass';
      let score = '';
      if (s.score != null && s.th != null && s.status !== 'skip') {
        const w = Math.min(1, s.score / s.max) * 100, th = s.th / s.max * 100;
        score = '<div class="s-score"><div class="score-bar"><div class="f ' + fillCls + '" data-w="' + w.toFixed(1) + '"></div><span class="th" style="left:' + th.toFixed(1) + '%"></span></div><div class="s-scoretext">' + scoreText(s) + '</div></div>';
      } else score = '<div class="s-sub" style="font-family:var(--font-sans);font-size:11.5px">' + esc(s.note || (s.status === 'skip' ? 'skipped' : '—')) + '</div>';
      let wf = '';
      if (s.status !== 'skip') { const l = off / total * 100, w = s.ms / total * 100; off += s.ms; wf = '<div class="wf"><div class="wf-track"></div><div class="wf-bar" style="left:' + l.toFixed(2) + '%;width:' + Math.max(0.6, w).toFixed(2) + '%;' + (s.status === 'hit' ? 'background:var(--' + (s.hitClass === 'downgrade' ? 'downgrade' : s.hitClass) + ')' : '') + '"></div></div><div class="wf-ms">' + fmtMs(s.ms) + '</div>'; }
      else wf = '<div class="wf-ms t4">—</div>';
      return '<div class="stage ' + cls + '" style="animation-delay:' + (i * 45) + 'ms"><span class="s-ico">' + A.icon(ico, 12) + '</span><div style="min-width:0"><div class="s-name">' + esc(s.name) + ' <span class="mono t3" style="font-weight:400;font-size:11px">' + esc(s.ctrl) + '</span></div><div class="s-sub">' + esc(s.sub) + '</div></div>' + score + '<div>' + wf + '</div></div>';
    }).join('');
    const st = e.stages.filter((s) => s.status !== 'skip' && s.key !== 'policy' && s.key !== 'ingress').map((s) => s.key.slice(0, 4) + ';dur=' + s.ms.toFixed(2));
    const serverTiming = 'Server-Timing: aicl;dur=' + e.overhead.toFixed(2) + ', ' + st.join(', ') + (e.upstream ? ', upstream;dur=' + Math.round(e.upstream) : '');
    const chain = A.u.hex(4) + '…' + A.u.hex(4);
    const audit = '{\n  <span class="k">"schema"</span>: <span class="s">"aicl.audit/1"</span>,\n  <span class="k">"event_id"</span>: <span class="s">"evt_' + e.id.slice(4) + '"</span>,\n  <span class="k">"decision"</span>: <span class="s">"' + e.decision + '"</span>,\n  <span class="k">"interception_point"</span>: <span class="s">"' + e.surface + '"</span>,\n  <span class="k">"controls"</span>: [{ <span class="k">"control_id"</span>: <span class="s">"' + esc(e.ctl || 'none') + '"</span>' + (hitStage && hitStage.score != null ? ', <span class="k">"score"</span>: <span class="n">' + hitStage.score + '</span>, <span class="k">"threshold"</span>: <span class="n">' + hitStage.th + '</span>' : '') + ' }],\n  <span class="k">"latency"</span>: { <span class="k">"gateway_overhead_ms"</span>: <span class="n">' + e.overhead.toFixed(2) + '</span>, <span class="k">"upstream_ms"</span>: <span class="n">' + Math.round(e.upstream) + '</span> },\n  <span class="k">"versions"</span>: { <span class="k">"catalog"</span>: <span class="s">"cat-v' + A.state.policyVersion + '"</span>, <span class="k">"feed_serial"</span>: <span class="n">' + A.state.feedSerial + '</span>, <span class="k">"gateway"</span>: <span class="s">"0.3.1"</span> },\n  <span class="k">"integrity"</span>: { <span class="k">"prev_hash"</span>: <span class="s">"sha256:7a1e…' + chain.slice(0, 4) + '"</span>, <span class="k">"hash"</span>: <span class="s">"sha256:' + chain + '"</span> }\n}';
    const isTool = /tool|egress|package/.test(e.surface);
    const html =
      '<div class="drawer-h"><div class="row">' + A.h.badge(e.tag === 'downgraded' ? 'downgrade' : e.decision, true) + (e.tag === 'downgraded' ? '<span class="badge allow lg"><span class="dot"></span>Allowed</span>' : '') + A.h.tag(e.surface) + (e.tool ? A.h.tag(e.tool, 'accent') : '') + '<span class="grow"></span><span class="mono t3" style="font-size:11.5px">' + clock(e.ts) + '</span><button class="btn ghost sm icon" data-close aria-label="Close">' + A.icon('x', 15) + '</button></div>' +
      '<div class="ap-detail-title ' + (isTool ? 'mono' : '') + '" style="' + (isTool ? 'font-size:13.5px;font-weight:500;letter-spacing:0' : 'font-size:15.5px') + '">' + esc(e.text) + '</div>' +
      '<div class="row t3" style="font-size:12.5px;gap:10px;flex-wrap:wrap">' + A.h.agentAv('sm') + '<span class="t1" style="font-weight:500">' + esc(e.agent) + '</span><span>·</span><span>' + esc(team.name) + '</span><span>·</span><span class="mono" style="font-size:11.5px">' + (e.requested ? esc(e.requested) + ' → ' : '') + esc(e.model || '—') + '</span></div></div>' +
      '<div class="drawer-b">' +
      '<div class="trace-reason ' + (e.tag === 'downgraded' ? 'approval' : e.decision) + '"><span class="' + 'c-' + (e.tag === 'downgraded' ? 'downgrade' : e.decision) + '" style="margin-top:2px">' + A.icon(e.decision === 'block' ? 'ban' : e.decision === 'redact' ? 'eyeOff' : e.decision === 'approval' ? 'clock' : e.tag ? 'arrowDown' : 'shieldCheck', 16) + '</span><div><div>' + esc(e.reason) + '</div><div class="mono t3" style="font-size:11.5px;margin-top:4px">' + esc(e.ctl || 'no control fired') + ' · policy v' + A.state.policyVersion + ' · feed #' + A.state.feedSerial + ' · strictness balanced</div></div></div>' +
      '<div class="grid g-4 mt-3">' +
      [['Gateway overhead', fmtMs(e.overhead)], ['Upstream', e.upstream ? Math.round(e.upstream) + ' ms' : '—'], ['Cost', e.cost ? fmtUsd(e.cost, 4) : '$0'], [e.avoided ? 'Cost avoided' : 'Tokens', e.avoided ? fmtUsd(e.avoided, 4) : fmtInt(e.tokens || 0)]].map((k) => '<div class="card" style="padding:10px 12px;box-shadow:none"><div class="t3" style="font-size:11.5px">' + k[0] + '</div><div class="num" style="font-size:15px;font-weight:600;margin-top:2px">' + k[1] + '</div></div>').join('') + '</div>' +
      '<div class="sub-h"><h4>Decision trace</h4><span class="right t3" style="font-size:12px">' + active.length + ' of ' + e.stages.length + ' controls ran' + (e.decision === 'block' && hitStage ? ' · short-circuit at ' + esc(hitStage.ctrl === 'SIG:*' ? (e.ctl || 'SIG') : hitStage.ctrl) : '') + '</span></div>' +
      '<div class="stage" style="opacity:1;animation:none;padding:0 0 6px;border-bottom:1px solid var(--border)"><span></span><span class="section-label">Control</span><span class="section-label">Score vs threshold</span><span class="section-label" style="text-align:right">Latency · waterfall</span></div>' +
      '<div class="pipeline">' + stages + '</div>' +
      '<div class="sub-h"><h4>Identifiers</h4></div><div class="kv">' +
      [['Request', e.id], ['Trace', e.trace], ['Session', e.session], ['Agent key', ag.key || '—'], ['Policy', 'cat-v' + A.state.policyVersion + ' · feed #' + A.state.feedSerial]].map((k) => '<span class="k">' + k[0] + '</span><span class="v mono">' + esc(k[1]) + '</span>').join('') + '</div>' +
      '<div class="sub-h"><h4>Response headers</h4></div><div class="codebox">X-Aegis-Decision: ' + e.decision + '\nX-Aegis-Trace-Id: ' + e.trace + '\nX-Policy-Version: ' + A.state.policyVersion + '\n' + esc(serverTiming) + '</div>' +
      '<div class="sub-h"><h4>Audit record</h4><span class="right"><span class="badge allow"><span class="dot"></span>Hash chain verified</span></span></div><div class="codebox">' + audit + '</div>' +
      '</div>' +
      '<div class="drawer-f">' + ((e.hit === 'pii' || e.hit === 'secrets') ? '<button class="btn secondary" id="tr-redact">' + A.icon('split', 14) + 'Open redaction diff</button>' : '') + '<button class="btn secondary" id="tr-copy">' + A.icon('copy', 14) + 'Copy trace ID</button><button class="btn primary" id="tr-export">' + A.icon('download', 14) + 'Export record</button></div>';
    A.drawer.open(html, (el) => {
      const rb = $('#tr-redact', el); if (rb) rb.addEventListener('click', () => { A.state.redactionSample = e.hit === 'secrets' ? 'env-debug' : 'client-reply'; A.drawer.close(); A.go('redaction'); });
      $('#tr-copy', el).addEventListener('click', () => { try { navigator.clipboard.writeText(e.trace).catch(() => {}); } catch (err) { /* file:// */ } A.toast({ type: 'success', title: 'Trace ID copied', meta: e.trace, duration: 2400 }); });
      $('#tr-export', el).addEventListener('click', () => A.toast({ type: 'success', icon: 'download', title: 'Audit record exported', desc: '1 record · JSONL · OCSF 2004 mapping included', meta: 'evt_' + e.id.slice(4) + '.jsonl' }));
    });
  };

  /* ---------------- kill switch ---------------- */
  const releaseKill = () => {
    if (A.state.role !== 'owner') { A.toast({ type: 'warn', icon: 'lock', title: 'Release requires Owner', desc: 'approvals.kill_switch.release → Owner. Switch “View as” to Owner to release.' }); return; }
    A.state.kill = null; renderTopbar();
    A.toast({ type: 'success', icon: 'power', title: 'Kill switch released', desc: 'Traffic resumes on the next request. Audit event killswitch.toggled written.' });
  };
  const openKill = () => {
    if (A.state.kill) { releaseKill(); return; }
    if (A.state.role === 'member') { A.toast({ type: 'warn', icon: 'lock', title: 'Members can’t engage the kill switch', desc: 'Requires Admin or Owner. Switch “View as” in the top bar.' }); return; }
    const opts = [
      { v: 'analyst-bot', l: 'agent/analyst-bot', d: 'Runaway loop · 98% of monthly budget' },
      { v: 'trade-desk-copilot', l: 'agent/trade-desk-copilot', d: '5 active sessions · downgraded' },
      { v: 'global', l: 'Global — all agents', d: 'Stops every agent in Acme Capital' }
    ];
    let pick = 'analyst-bot';
    A.modal.open({
      title: 'Engage kill switch', desc: 'Cancels in-flight upstream streams and refuses new requests until released. Release requires Owner.',
      body: '<div class="opt-list">' + opts.map((o, i) => '<button type="button" class="opt ' + (i === 0 ? 'on' : '') + '" data-v="' + o.v + '"><span class="radio"></span><span class="grow"><span class="mono" style="font-size:12.5px;color:var(--text-1)">' + esc(o.l) + '</span><span class="t3" style="display:block;font-size:12px">' + esc(o.d) + '</span></span></button>').join('') + '</div>',
      onMount: (w) => { $$('.opt', w).forEach((b) => b.addEventListener('click', () => { pick = b.dataset.v; $$('.opt', w).forEach((x) => x.classList.toggle('on', x === b)); })); },
      actions: [{ label: 'Cancel' }, { label: 'Engage kill switch', kind: 'danger', icon: 'power', onClick: () => {
        A.state.kill = { scope: pick === 'global' ? 'global' : 'agent', agents: pick === 'global' ? [] : [pick], by: A.me().name, at: A.u.hhmm(Date.now()) };
        renderTopbar();
        A.toast({ type: 'error', icon: 'power', title: 'Kill switch engaged', desc: (pick === 'global' ? 'All agents' : 'agent/' + esc(pick)) + ' · 3 in-flight streams cancelled', meta: 'aicl_killswitch_active=1 · audit killswitch.toggled' });
      } }]
    });
  };
  $('#kill-btn').addEventListener('click', openKill);

  /* ---------------- commands (⌘K) ---------------- */
  A.commands = () => {
    const nav = NAV.filter((n) => n.id).map((n) => ({ group: 'Go to', icon: n.icon, label: n.label, hint: 'g ' + n.key, run: () => A.go(n.id) }));
    const sims = A.presets.map((p) => ({ group: 'Simulate', icon: 'zap', label: p.label, run: () => { const e = A.emitTemplate(A.templates[p.idx]); A.openTrace(e); } }));
    const roles = ['owner', 'admin', 'member'].map((r) => ({ group: 'View as', icon: 'user', label: 'View as ' + A.roles[r].label + ' — ' + A.member(A.viewAs[r]).name, run: () => A.setRole(r) }));
    const actions = [
      { group: 'Actions', icon: A.state.live ? 'pause' : 'play', label: A.state.live ? 'Pause live stream' : 'Resume live stream', hint: 'space', run: () => A.setLive(!A.state.live) },
      { group: 'Actions', icon: 'power', label: A.state.kill ? 'Release kill switch' : 'Engage kill switch…', run: openKill },
      { group: 'Actions', icon: 'download', label: 'Export audit log (OCSF)', run: () => A.toast({ type: 'success', icon: 'download', title: 'Audit export ready', desc: '48,213 records · chain verified', meta: 'aegis-audit-2026-10-03.ocsf.jsonl' }) },
      { group: 'Actions', icon: 'radar', label: 'Threat feed: simulate tampered bundle', run: () => { A.go('feed'); setTimeout(() => A.feedTamper && A.feedTamper(), 300); } },
      { group: 'Actions', icon: 'fileCode', label: 'Policy: lower INJ-003 block threshold to 0.50', run: () => { A.go('policy'); setTimeout(() => A.policyQuick && A.policyQuick('threshold'), 300); } }
    ];
    return nav.concat(actions, sims, roles);
  };
  $('#search-btn').addEventListener('click', () => A.cmdk.open());
  $('#menu-btn').addEventListener('click', () => A.cmdk.open());

  /* ---------------- keyboard ---------------- */
  let gPending = 0;
  document.addEventListener('keydown', (e) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement && document.activeElement.tagName);
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); A.cmdk.isOpen ? A.cmdk.close() : A.cmdk.open(); return; }
    if (e.key === 'Escape') { if (A.cmdk.isOpen) A.cmdk.close(); else if (A.modal.isOpen) A.modal.close(); else if (A.drawer.isOpen) A.drawer.close(); A.menu.close(); return; }
    if (typing || A.cmdk.isOpen || A.modal.isOpen) return;
    if (e.key === 'g') { gPending = Date.now(); return; }
    if (gPending && Date.now() - gPending < 900) { const n = NAV.find((x) => x.key === e.key); gPending = 0; if (n) { e.preventDefault(); A.go(n.id); } return; }
    if (e.key === ' ' && current === 'live') { e.preventDefault(); A.setLive(!A.state.live); }
  });

  /* ---------------- init ---------------- */
  $('#brand-mark').innerHTML = A.logo(16);
  $('#search-ico').innerHTML = A.icon('search', 14);
  $('#menu-btn').innerHTML = A.icon('command', 15);
  $('#org-chev').innerHTML = A.icon('chevUpDown', 14);
  A.seedEvents();
  A.refreshShell();
  route();
  A.startLive();
})(window.A);
