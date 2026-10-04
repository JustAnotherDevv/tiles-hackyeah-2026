/* View 8 — Org & roles */
(function (A) {
  'use strict';
  const { $, $$, esc, fmtUsd } = A.u;
  let tab = 'members';

  const RULES = [
    ['Spend', 'amount ≤ $20', 'self', false, '6 h', 'agent owner approves own agent'],
    ['Spend', '$20 < amount ≤ $200', 'admin', false, '24 h', ''],
    ['Spend', 'amount > $200', 'owner', false, '24 h', ''],
    ['DB read', 'table tagged pii', 'admin', false, '1 h', 'results tokenized for external models'],
    ['DB write', 'env = production', 'owner', true, '1 h', 'two-person rule'],
    ['Egress', 'domain not on allowlist', 'admin', false, '4 h', 'EEA residency checked'],
    ['Package install', 'unknown / hallucinated package', 'admin', false, '1 h', 'AICL-TI-016'],
    ['Config change', 'add allowed model · threshold edit', 'admin', false, '24 h', ''],
    ['Config change', 'budget increase > 20%', 'owner', false, '24 h', 'escalate_to_owner'],
    ['Config change', 'disable a control', 'owner', false, '24 h', 'justification required'],
    ['Kill switch', 'engage · release', 'admin', false, '—', 'release requires owner']
  ];
  const CAPS = [
    ['View dashboards, decisions & audit', 'y', 'y', 'y'],
    ['Approve own agents’ spend ≤ $20', 'y', 'y', 'y'],
    ['Approve data access, egress, model changes', 'y', 'y', 'n'],
    ['Edit policy catalog (hot reload)', 'y', 'y', 'request'],
    ['Raise budgets > 20% · disable controls', 'y', 'n', 'n'],
    ['Production DB writes (two-person)', 'y', 'n', 'n'],
    ['Engage kill switch', 'y', 'y', 'n'],
    ['Release kill switch', 'y', 'n', 'n'],
    ['Manage members & roles', 'y', 'invite', 'n'],
    ['Rotate feed signing key / agent keys', 'y', 'agent keys', 'n']
  ];
  const cell = (v) => v === 'y' ? '<span class="yes">' + A.icon('check', 15) + '</span>' : v === 'n' ? '<span class="no">' + A.icon('minus', 15) + '</span>' : '<span class="part">' + esc(v) + '</span>';

  const body = () => {
    if (tab === 'members') return '<table class="table tall"><thead><tr><th>Member</th><th>Role</th><th>Title</th><th>Team</th><th>MFA</th><th>Last active</th><th></th></tr></thead><tbody>' +
      A.members.map((m) => '<tr><td><div class="cell-agent">' + A.h.avatar(m.name) + '<div><div style="font-weight:500">' + esc(m.name) + (m.id === A.viewAs[A.state.role] ? ' <span class="badge accent" style="height:18px">You</span>' : '') + '</div><div class="t3 mono" style="font-size:11.5px">' + esc(m.email) + '</div></div></div></td><td>' + A.h.role(m.role) + '</td><td class="t2">' + esc(m.title) + '</td><td class="t2">' + esc(m.team) + '</td><td>' + (m.mfa ? '<span class="c-allow">' + A.icon('check', 14) + '</span>' : '<span class="badge approval">Off</span>') + '</td><td class="t3">' + (m.last === 'invited' ? '<span class="badge neutral">Invited</span>' : esc(m.last === 'now' ? 'now' : m.last + ' ago')) + '</td><td class="r"><button class="btn ghost sm" data-role-of="' + m.id + '"' + (A.state.role === 'owner' ? '' : ' disabled data-tip="Only Owners can change roles"') + '>Change role' + A.icon('chevDown', 12) + '</button></td></tr>').join('') + '</tbody></table>';
    if (tab === 'agents') return '<table class="table tall"><thead><tr><th>Agent (service identity)</th><th>Team</th><th>Owner</th><th>Allowed models</th><th>Key</th><th class="r">Budget</th><th>Status</th><th>Last seen</th></tr></thead><tbody>' +
      A.agents.map((a) => '<tr><td><div class="cell-agent">' + A.h.agentAv() + '<div><div class="mono" style="font-size:12.5px;font-weight:500">' + esc(a.id) + '</div><div class="t3" style="font-size:11.5px">' + esc(a.kind) + '</div></div></div></td><td class="t2">' + esc(A.team(a.team).name) + '</td><td><div class="cell-agent">' + A.h.avatar(A.member(a.owner).name, 'sm') + '<span class="t2">' + esc(A.member(a.owner).name) + '</span></div></td><td><div class="row" style="gap:4px">' + a.models.map((x) => '<span class="tag">' + esc(x.replace('anthropic/', '').replace('ollama/', '⌂ ')) + '</span>').join('') + '</div></td><td class="mono t3" style="font-size:11.5px">' + esc(a.key) + '</td><td class="r num t2">' + fmtUsd(a.used, 0) + ' / ' + fmtUsd(a.limit, 0) + '</td><td>' + (a.status === 'active' ? '<span class="badge allow"><span class="dot"></span>Active</span>' : a.status === 'downgraded' ? '<span class="badge downgrade"><span class="dot"></span>Downgraded</span>' : '<span class="badge approval"><span class="dot"></span>Throttled</span>') + '</td><td class="t3">' + esc(a.last) + '</td></tr>').join('') + '</tbody></table>';
    if (tab === 'rules') return '<table class="table"><thead><tr><th>Action</th><th>Condition</th><th>Approver</th><th>Two-person</th><th>Expires</th><th>Notes</th></tr></thead><tbody>' +
      RULES.map((r) => '<tr><td style="font-weight:500">' + r[0] + '</td><td class="mono t2" style="font-size:12px">' + esc(r[1]) + '</td><td>' + A.h.role(r[2]) + '</td><td>' + (r[3] ? '<span class="badge accent">' + A.icon('users', 11) + 'Required</span>' : '<span class="t4">—</span>') + '</td><td class="mono t3" style="font-size:12px">' + r[4] + '</td><td class="t3">' + esc(r[5]) + '</td></tr>').join('') + '</tbody></table>';
    return '<table class="table matrix"><thead><tr><th>Capability</th><th class="c" style="text-align:center">' + A.h.role('owner') + '</th><th style="text-align:center">' + A.h.role('admin') + '</th><th style="text-align:center">' + A.h.role('member') + '</th></tr></thead><tbody>' +
      CAPS.map((c) => '<tr><td>' + esc(c[0]) + '</td><td class="c">' + cell(c[1]) + '</td><td class="c">' + cell(c[2]) + '</td><td class="c">' + cell(c[3]) + '</td></tr>').join('') + '</tbody></table>';
  };

  const draw = () => {
    $('#org-body').innerHTML = body();
    $$('[data-role-of]').forEach((b) => b.addEventListener('click', (ev) => {
      ev.stopPropagation(); const m = A.member(b.dataset.roleOf);
      A.menu.open(b, [{ group: 'Role for ' + m.name }].concat(['owner', 'admin', 'member'].map((r) => ({ icon: r === m.role ? 'check' : 'user', label: A.roles[r].label, onClick: () => { if (r === m.role) return; m.role = r; draw(); A.toast({ type: 'success', icon: 'users', title: m.name + ' is now ' + A.roles[r].label, meta: 'audit member.role_changed · by ' + A.me().name }); } }))));
    }));
  };

  A.views.org = {
    render(root) {
      const o = A.org;
      root.innerHTML =
        '<div class="page-head"><div><h1 class="page-title">Org & roles</h1><div class="page-sub">Members, agents as service identities, and the approval policies that decide who can approve what.</div></div><div class="actions"><button class="btn secondary" id="org-key">' + A.icon('key', 14) + 'New agent key</button><button class="btn primary" id="org-invite">' + A.icon('plus', 14) + 'Invite member</button></div></div>' +
        '<div class="card mb-3"><div class="org-hero"><div class="ol">AC</div><div><div style="font-size:17px;font-weight:600;letter-spacing:-0.015em">' + esc(o.name) + '</div><div class="t3" style="font-size:12.5px">' + esc(o.domain) + ' · ' + esc(o.region) + ' · ' + esc(o.plan) + ' · since ' + esc(o.created) + '</div></div>' +
        '<div class="org-stats">' + [[A.members.length, 'Members'], [A.agents.length, 'Agents'], [A.teams.length, 'Teams'], [RULES.length, 'Approval rules']].map((s) => '<div class="os"><div class="v num">' + s[0] + '</div><div class="l">' + s[1] + '</div></div>').join('') + '</div></div></div>' +
        '<div class="row mb-3">' + A.h.seg('org-tab', [{ v: 'members', l: 'Members', icon: 'users' }, { v: 'agents', l: 'Agents', icon: 'bot' }, { v: 'rules', l: 'Approval policies', icon: 'inbox' }, { v: 'roles', l: 'Roles & permissions', icon: 'shield' }], tab, 'lg') + '</div>' +
        '<div class="card"><div class="table-scroll" id="org-body"></div></div>';
      A.segHandlers['org-tab'] = (v) => { tab = v; draw(); };
      draw();
      $('#org-invite').addEventListener('click', () => {
        if (A.state.role === 'member') { A.toast({ type: 'warn', icon: 'lock', title: 'Members can’t invite', desc: 'Requires Admin or Owner.' }); return; }
        A.modal.open({ title: 'Invite member', desc: 'They join Acme Capital with the role you choose. Owners can be invited only by Owners.', body: '<div class="field"><label for="inv-email">Email</label><input class="input" id="inv-email" value="aleksandra.nowicka@acme-capital.pl"></div><div class="field"><label>Role</label><select class="select" id="inv-role"><option value="member">Member</option><option value="admin">Admin</option>' + (A.state.role === 'owner' ? '<option value="owner">Owner</option>' : '') + '</select></div>', actions: [{ label: 'Cancel' }, { label: 'Send invite', kind: 'primary', icon: 'mail', onClick: (w) => A.toast({ type: 'success', icon: 'mail', title: 'Invite sent', desc: esc($('#inv-email', w).value) + ' · ' + esc($('#inv-role', w).value), meta: 'audit member.invited' }) }] });
      });
      $('#org-key').addEventListener('click', () => A.toast({ type: 'success', icon: 'key', title: 'Agent key created', desc: 'Shown once in the CLI — the dashboard only ever stores a fingerprint.', meta: 'sha256:' + A.u.hex(4) + '…' + A.u.hex(4) }));
    },
    onRole() { A.rerender(); }
  };
})(window.A);
