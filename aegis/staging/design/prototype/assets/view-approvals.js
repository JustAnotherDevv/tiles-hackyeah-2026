/* View 4 — Approvals inbox with "view as" role switcher */
(function (A) {
  'use strict';
  const { $, $$, esc, dur } = A.u;
  let tab = 'pending', sel = null;
  const KIND = { spend: 'Spend', data: 'Data access', config: 'Config change', egress: 'Egress', dbwrite: 'Prod write', model: 'Config change', control: 'Config change' };
  const RISK = { low: 'neutral', medium: 'approval', high: 'block' };

  const reqLabel = (ap) => ap.required === 'member' ? 'Self-approve' : 'Requires ' + A.roles[ap.required].label;
  const reqBadge = (ap) => '<span class="role-badge ' + (ap.required === 'member' ? 'self' : ap.required) + '">' + (ap.required === 'member' ? A.icon('user', 11) : A.icon('shield', 11)) + reqLabel(ap) + '</span>';
  const isOwnRequest = (ap) => ap.subject.type === 'member' && ap.subject.id === A.viewAs[A.state.role] && ap.required !== 'member';
  const can = (ap) => A.canApprove(ap) && !isOwnRequest(ap) && !(ap.twoPerson && (ap.approvals || []).some((x) => x.by === A.viewAs[A.state.role]));
  const requester = (ap) => ap.subject.type === 'agent' ? ap.subject.id : A.member(ap.subject.id).name;
  const eligible = (ap) => A.members.filter((m) => m.role !== 'member' && A.roles[m.role].rank >= A.roles[ap.required === 'member' ? 'member' : ap.required].rank).map((m) => m.name);

  const list = () => {
    const S = A.state;
    if (tab === 'history') return S.history;
    return tab === 'mine' ? S.approvals.filter(can) : S.approvals;
  };

  const itemHtml = (ap) => {
    const ok = can(ap);
    return '<div class="ap-item ' + (sel === ap.id ? 'selected ' : '') + (ok ? '' : 'locked ') + (ap._arrive ? 'arrive' : '') + '" data-id="' + ap.id + '"><div class="ap-ico">' + A.icon(ap.icon, 16) + '</div><div class="grow" style="min-width:0"><div class="ap-title">' + esc(ap.title) + '</div><div class="ap-meta">' + reqBadge(ap) +
      '<span>' + esc(requester(ap)) + '</span><span class="row" style="gap:4px" data-exp="' + ap.expires + '">' + A.icon('clock', 11) + '<span class="exp-t">' + dur(ap.expires - Date.now()) + '</span></span>' +
      (ap.twoPerson ? '<span class="row" style="gap:6px"><span class="progress-2p"><span class="' + ((ap.approvals || []).length >= 1 ? 'on' : '') + '"></span><span class="' + ((ap.approvals || []).length >= 2 ? 'on' : '') + '"></span></span>' + (ap.approvals || []).length + '/2</span>' : '') +
      '</div></div>' + (ok ? '' : '<span class="t4" style="margin-top:2px">' + A.icon('lock', 14) + '</span>') + '</div>';
  };
  const histHtml = (h) => '<div class="ap-item" style="cursor:default"><div class="ap-ico" style="color:var(--' + (h.decision === 'approved' ? 'allow' : 'block') + ')">' + A.icon(h.decision === 'approved' ? 'check' : 'x', 16) + '</div><div class="grow"><div class="ap-title">' + esc(h.title) + '</div><div class="ap-meta"><span class="badge ' + (h.decision === 'approved' ? 'allow' : 'block') + '"><span class="dot"></span>' + h.decision + '</span><span>by ' + esc(A.member(h.by).name) + '</span>' + A.h.role(h.role) + '<span>' + esc(h.ago) + '</span></div></div></div>';

  const detailHtml = (ap) => {
    if (!ap) return '<div class="empty"><div class="e-ico">' + A.icon('check', 18) + '</div><div class="t1" style="font-weight:500">Inbox zero</div><div style="margin-top:4px">Nothing waiting for your role. New requests appear here in real time.</div></div>';
    const ok = can(ap); const me = A.me();
    const ag = ap.subject.type === 'agent' ? A.agent(ap.subject.id) : null;
    const team = A.team(ap.subject.team);
    const n = (ap.approvals || []).length;
    const payload = ap.diff ? esc(ap.payload).split('\n').map((l) => /^\+/.test(l) ? '<span class="add">' + l + '</span>' : /^-/.test(l) ? '<span class="del">' + l + '</span>' : l).join('\n') : esc(ap.payload);
    let lock = '';
    if (!ok) {
      const why = isOwnRequest(ap) ? 'You requested this change — separation of duties requires another approver.' : (ap.twoPerson && (ap.approvals || []).some((x) => x.by === A.viewAs[A.state.role])) ? 'You already approved — the two-person rule needs a different ' + A.roles[ap.required].label + '.' : reqLabel(ap) + '. You are viewing as <b class="t1">' + A.roles[A.state.role].label + '</b> (' + esc(me.name) + ').';
      lock = '<div class="lock-note">' + A.icon('lock', 15) + '<span>' + why + ' Eligible: ' + esc(eligible(ap).join(', ')) + '.</span></div>';
    }
    return '<div class="ap-detail-h"><div class="row" style="flex-wrap:wrap">' + A.h.tag(KIND[ap.kind] || ap.kind) + reqBadge(ap) + '<span class="badge ' + RISK[ap.risk] + '"><span class="dot"></span>' + A.cap(ap.risk) + ' risk</span>' + (ap.twoPerson ? '<span class="badge accent">' + A.icon('users', 11) + 'Two-person rule</span>' : '') + '<span class="grow"></span><span class="mono t3" style="font-size:11.5px">' + ap.id + '</span></div>' +
      '<div class="ap-detail-title">' + esc(ap.title) + '</div>' +
      '<div class="row t3" style="font-size:12.5px;flex-wrap:wrap;gap:8px">' + (ag ? A.h.agentAv('sm') + '<span class="t1" style="font-weight:500">' + esc(ag.id) + '</span><span>on behalf of</span>' + A.h.avatar(A.member(ap.subject.onBehalf).name, 'sm') + '<span class="t2">' + esc(A.member(ap.subject.onBehalf).name) + '</span>' : A.h.avatar(A.member(ap.subject.id).name, 'sm') + '<span class="t1" style="font-weight:500">' + esc(A.member(ap.subject.id).name) + '</span>' + A.h.role(A.member(ap.subject.id).role)) +
      '<span>·</span><span>' + esc(team ? team.name : '') + '</span><span>·</span><span>requested ' + A.u.ago(Date.now() - ap.created) + ' ago</span></div></div>' +
      '<div class="card-b" style="padding-top:16px">' +
      '<div class="section-label" style="margin-bottom:8px">Requested action</div><div class="ap-code">' + payload + '</div>' +
      '<div class="section-label" style="margin:18px 0 8px">Justification</div><div class="t2" style="font-size:13px;line-height:20px;border-left:2px solid var(--border-strong);padding-left:12px">“' + esc(ap.why) + '”</div>' +
      '<div class="section-label" style="margin:18px 0 8px">Routing</div><div class="route" style="flex-wrap:wrap;row-gap:8px">' +
      '<div class="step done">' + A.icon('send', 13) + '<span>Requested</span></div><span class="conn">' + A.icon('chevRight', 14) + '</span>' +
      '<div class="step done">' + A.icon('fileCode', 13) + '<span class="mono" style="font-size:11.5px">' + esc(ap.rule) + '</span><span class="t3">' + esc(ap.ruleText) + '</span></div><span class="conn">' + A.icon('chevRight', 14) + '</span>' +
      (ap.twoPerson ? '<div class="step ' + (n >= 1 ? 'done' : 'active') + '">' + A.icon('user', 13) + (n >= 1 ? esc(A.member(ap.approvals[0].by).name) + ' ✓' : 'Owner #1') + '</div><span class="conn">' + A.icon('chevRight', 14) + '</span><div class="step active">' + A.icon('user', 13) + 'Owner #2</div>' : '<div class="step active">' + A.icon('shield', 13) + '<span>' + reqLabel(ap) + '</span></div>') +
      '</div>' +
      '<div class="section-label" style="margin:18px 0 8px">Context</div><div class="kv" style="grid-template-columns:150px 1fr">' + ap.context.map((c) => '<span class="k">' + esc(c[0]) + '</span><span class="v">' + esc(c[1]) + '</span>').join('') + '</div>' +
      (ap.signals.length ? '<div class="section-label" style="margin:18px 0 8px">Risk signals</div><div class="row" style="flex-wrap:wrap;gap:6px">' + ap.signals.map((s) => '<span class="signal">' + A.icon('alert', 12) + esc(s) + '</span>').join('') + '</div>' : '') +
      '</div>' +
      '<div class="card-f" style="flex-wrap:wrap;gap:10px;padding:12px 16px">' + (ok
        ? '<span class="row t3" style="gap:6px" data-exp="' + ap.expires + '">' + A.icon('clock', 13) + 'Expires in <span class="exp-t mono t2">' + dur(ap.expires - Date.now()) + '</span></span><span class="grow"></span><button class="btn danger-ghost" id="ap-deny">' + A.icon('x', 14) + 'Deny</button><button class="btn success" id="ap-approve">' + A.icon('check', 14) + (ap.twoPerson && n === 0 ? 'Approve (1 of 2)' : ap.required === 'member' ? 'Self-approve' : 'Approve') + '</button>'
        : lock + '<span class="grow"></span><button class="btn secondary" disabled>' + A.icon('x', 14) + 'Deny</button><button class="btn success" disabled>' + A.icon('lock', 14) + 'Approve</button>') + '</div>';
  };

  const effects = (ap) => {
    const me = A.me();
    if (ap.id === 'apr_01JB8JZ4XW') {
      A.team('trading').limit = 2000;
      A.commitPolicy && A.commitPolicy(A.state.policyActive.replace('scope: team/trading\n    usd: { limit: 500, window: 1mo }', 'scope: team/trading\n    usd: { limit: 2000, window: 1mo }'), { by: me.id, note: 'team/trading usd 500 → 2000 (apr)', ms: 162 });
      A.toast({ type: 'success', icon: 'zap', title: 'Policy v' + A.state.policyVersion + ' hot-reloaded in 162 ms', desc: 'budgets.team/trading.usd.limit <span class="mono">500 → 2000</span> · Trading leaves soft limit, downgrade lifted', meta: 'approved by ' + me.name + ' (' + A.roles[A.state.role].label + ')' });
      return;
    }
    if (ap.id === 'apr_01JB8K1A9T') {
      A.commitPolicy && A.commitPolicy(A.state.policyActive.replace('    - ollama/llama3.2:3b\n', '    - ollama/llama3.2:3b\n    - openai/gpt-5-mini\n'), { by: me.id, note: 'models.allowed += openai/gpt-5-mini', ms: 171 });
      A.toast({ type: 'success', icon: 'zap', title: 'Policy v' + A.state.policyVersion + ' hot-reloaded in 171 ms', desc: 'models.allowed += <span class="mono">openai/gpt-5-mini</span> (external zone → PII tokenized)' });
      return;
    }
    if (ap.id === 'apr_01JB8JW2HD') {
      A.commitPolicy && A.commitPolicy(A.state.policyActive.replace('  SEC-001:\n    name: Secrets & credentials\n    enabled: true', '  SEC-001:\n    name: Secrets & credentials\n    enabled: false'), { by: me.id, note: 'SEC-001 enabled: false (apr, justified)', ms: 158 });
      A.toast({ type: 'warn', icon: 'shieldOff', title: 'SEC-001 disabled by approved change', desc: 'High-severity audit event written · secrets will now pass for team Research', meta: 'policy v' + A.state.policyVersion + ' · approved by ' + me.name });
      return;
    }
    const msg = { spend: 'Payment released to ' + requester(ap) + ' · ' + A.u.fmtUsd(ap.amount || 0), data: 'Query released · results tokenized by PII-002 before reaching the model', egress: 'Egress to api.enrichly.io allowed once · payload scanned', dbwrite: 'Two-person rule satisfied · write executed under change ticket' }[ap.kind] || 'Request released';
    A.toast({ type: 'success', icon: 'check', title: 'Approved', desc: esc(msg), meta: 'audit approval.granted · ' + ap.id + ' · ' + me.name });
  };

  const decide = (ap, decision) => {
    const S = A.state; const me = A.me();
    if (decision === 'approved' && ap.twoPerson && (ap.approvals || []).length < 1) {
      ap.approvals = [{ by: me.id, role: A.state.role, ago: 0 }];
      A.toast({ type: 'info', icon: 'users', title: 'First approval recorded (1 of 2)', desc: 'Waiting for a second Owner — two-person rule.' });
      draw(); return;
    }
    const el = $('.ap-item[data-id="' + ap.id + '"]');
    const finish = () => {
      S.approvals = S.approvals.filter((x) => x.id !== ap.id);
      S.history.unshift({ id: ap.id, title: ap.title, by: me.id, role: A.state.role, decision, ago: 'just now' });
      const next = list()[0]; sel = next ? next.id : null;
      A.bus.emit('approvals'); draw();
    };
    if (el) { el.classList.add('leaving'); setTimeout(finish, 400); } else finish();
    if (decision === 'approved') effects(ap);
    else A.toast({ type: 'error', icon: 'x', title: 'Denied', desc: esc(requester(ap)) + ' receives <span class="mono">403 approval_denied</span> with your reason', meta: 'audit approval.denied · ' + ap.id });
  };

  const draw = () => {
    const S = A.state; const items = list();
    if (tab !== 'history' && (!sel || !S.approvals.find((x) => x.id === sel))) sel = items[0] ? items[0].id : null;
    const mine = S.approvals.filter(can).length;
    $('#ap-tabs').innerHTML = A.h.seg('ap-tab', [{ v: 'pending', l: 'Pending · ' + S.approvals.length }, { v: 'mine', l: 'You can approve · ' + mine }, { v: 'history', l: 'History' }], tab, 'lg');
    A.initSegs($('#ap-tabs'));
    $('#ap-list').innerHTML = tab === 'history' ? items.map(histHtml).join('') : (items.map(itemHtml).join('') || '<div class="empty"><div class="e-ico">' + A.icon('check', 18) + '</div>Nothing here for ' + A.roles[S.role].label + '.</div>');
    items.forEach((x) => { delete x._arrive; });
    const ap = tab === 'history' ? null : S.approvals.find((x) => x.id === sel);
    $('#ap-detail').innerHTML = tab === 'history' ? '<div class="empty"><div class="e-ico" style="color:var(--accent-fg)">' + A.icon('hash', 18) + '</div><div class="t1" style="font-weight:500">Every decision is audited</div><div style="margin-top:4px">approval.granted / approval.denied events are hash-chained with the approver, role and policy version.</div></div>' : detailHtml(ap);
    const urgent = S.approvals.filter((x) => x.expires - Date.now() < 3600e3).length;
    $('#ap-sum').innerHTML = '<span class="chip">' + A.icon('inbox', 13) + S.approvals.length + ' pending</span><span class="chip">' + A.icon('check', 13) + mine + ' you can approve</span><span class="chip">' + A.icon('clock', 13) + urgent + ' expiring &lt; 1h</span>';
    if (ap && can(ap)) { $('#ap-approve').addEventListener('click', () => decide(ap, 'approved')); $('#ap-deny').addEventListener('click', () => denyModal(ap)); }
  };

  const denyModal = (ap) => A.modal.open({
    title: 'Deny request', desc: esc(ap.title),
    body: '<div class="field"><label>Reason (sent to the agent and written to the audit log)</label><textarea class="input" rows="3" id="deny-reason">Not justified for this scope — use the sandbox dataset instead.</textarea></div>',
    actions: [{ label: 'Cancel' }, { label: 'Deny request', kind: 'danger', icon: 'x', onClick: () => decide(ap, 'denied') }]
  });

  A.addApproval = (ap) => { ap._arrive = true; ap.created = Date.now(); ap.expires = Date.now() + 24 * 3600e3; A.state.approvals.unshift(ap); A.bus.emit('approvals'); if (A.current === 'approvals') draw(); };

  A.views.approvals = {
    render(root) {
      const m = A.me();
      root.innerHTML =
        '<div class="page-head"><div><h1 class="page-title">Approvals</h1><div class="page-sub">Agent actions and config changes are routed to the role allowed to approve them — by action type, amount and scope. Every decision is audited.</div></div>' +
        '<div class="actions"><span class="t3" style="font-size:12.5px">Viewing as</span>' + A.h.seg('role', [{ v: 'owner', l: 'Owner', icon: 'shield' }, { v: 'admin', l: 'Admin', icon: 'shield' }, { v: 'member', l: 'Member', icon: 'user' }], A.state.role, 'lg') + '<span class="row" style="gap:8px">' + A.h.avatar(m.name) + '<span style="font-size:12.5px">' + esc(m.name) + '</span></span></div></div>' +
        (A.state.role === 'member' ? '<div class="banner info">' + '<span class="b-icon">' + A.icon('info', 15) + '</span><div><div class="b-title">You’re viewing as a Member</div><div class="b-desc">Members can self-approve spend ≤ $20 for agents they own. Data access, egress and config changes route to Admins; large budget changes, production writes and disabling controls route to Owners.</div></div></div>' : '') +
        '<div class="row mb-3" style="flex-wrap:wrap;gap:8px"><div id="ap-tabs"></div><span class="grow"></span><div class="row" id="ap-sum" style="gap:6px"></div></div>' +
        '<div class="ap-layout"><div class="card"><div class="ap-list" id="ap-list"></div></div><div class="card" id="ap-detail" style="position:sticky;top:0"></div></div>';
      A.segHandlers['ap-tab'] = (v) => { tab = v; sel = null; draw(); };
      $('#ap-list').addEventListener('click', (ev) => { const it = ev.target.closest('.ap-item[data-id]'); if (!it) return; sel = it.dataset.id; draw(); });
      draw();
    },
    onRole() { A.rerender(); },
    onTick() { $$('[data-exp]').forEach((el) => { const t = el.querySelector('.exp-t'); if (t) t.textContent = dur(+el.dataset.exp - Date.now()); }); }
  };
})(window.A);
