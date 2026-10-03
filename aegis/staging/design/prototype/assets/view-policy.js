/* View 6 — Policy editor (YAML look, live diff, validate → self-test → atomic swap, hot-reload toast) */
(function (A) {
  'use strict';
  const { $, $$, esc } = A.u;
  const S = A.state;
  let applying = false, lastErr = null;
  const versions = A.policyVersions.slice();
  const STRICT = { permissive: { block: '0.92', tpr: '81%', fpr: '0.4%' }, balanced: { block: '0.85', tpr: '93%', fpr: '1.2%' }, strict: { block: '0.70', tpr: '98%', fpr: '4.7%' } };

  /* ---------------- YAML highlighting ---------------- */
  const TOK = /("[^"]*"|'[^']*')|((?:^|(?<=[\s\[{,]))-?\d+(?:\.\d+)?(?=$|[\s,\]}]))|(\btrue\b|\bfalse\b|\bnull\b)|([\[\]{},])|([A-Za-z_][\w.\-\/]*)(?=:\s)|([^\s\[\]{},"']+)/g;
  const colorVal = (v) => {
    let out = '', m, last = 0; TOK.lastIndex = 0;
    while ((m = TOK.exec(v))) {
      if (m.index > last) out += esc(v.slice(last, m.index));
      const t = m[0];
      out += m[1] ? '<span class="y-str">' + esc(t) + '</span>' : m[2] ? '<span class="y-num">' + esc(t) + '</span>' : m[3] ? '<span class="y-bool">' + t + '</span>' : m[4] ? '<span class="y-punc">' + esc(t) + '</span>' : m[5] ? '<span class="y-key">' + esc(t) + '</span>' : '<span class="y-str">' + esc(t) + '</span>';
      last = m.index + t.length; if (t.length === 0) TOK.lastIndex++;
    }
    return out + esc(v.slice(last));
  };
  const hlLine = (line) => {
    let code = line, com = '';
    const ci = line.search(/(^|\s)#/);
    if (ci >= 0) { const at = line[ci] === '#' ? ci : ci + 1; code = line.slice(0, at); com = '<span class="y-com">' + esc(line.slice(at)) + '</span>'; }
    let m = code.match(/^(\s*)(- )?([^:#\[\]{}'"]+?)(:)(\s.*|)$/);
    if (m) {
      const isId = /^(?:[A-Z]{2,5}-\d{3}|AICL-TI-\d{3})$/.test(m[3].trim());
      return esc(m[1]) + (m[2] ? '<span class="y-dash">- </span>' : '') + '<span class="' + (isId ? 'y-id' : 'y-key') + '">' + esc(m[3]) + '</span><span class="y-punc">:</span>' + colorVal(m[5]) + com;
    }
    m = code.match(/^(\s*)(- )(.*)$/);
    if (m) return esc(m[1]) + '<span class="y-dash">- </span>' + colorVal(m[3]) + com;
    return esc(code) + com;
  };

  /* ---------------- validation ---------------- */
  const validate = (text) => {
    const lines = text.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const raw = lines[i];
      if (raw.indexOf('\t') >= 0) return { ok: false, stage: 'parse', line: i + 1, col: raw.indexOf('\t') + 1, msg: 'tab character — YAML indentation must use spaces' };
      const code = raw.replace(/(^|\s)#.*$/, '');
      if (!code.trim()) continue;
      const ind = code.match(/^\s*/)[0].length;
      if (ind % 2) return { ok: false, stage: 'parse', line: i + 1, col: ind + 1, msg: 'bad indentation of a mapping entry' };
      const body = code.trim();
      const opens = (body.match(/[\[{]/g) || []).length, closes = (body.match(/[\]}]/g) || []).length;
      if (opens !== closes) return { ok: false, stage: 'parse', line: i + 1, col: ind + body.length + 1, msg: 'unclosed flow collection — missing "' + (opens > closes ? ((body.lastIndexOf('[') > body.lastIndexOf('{')) ? ']' : '}') : '[') + '"' };
      if (/^- /.test(body)) continue;
      if (!/^[^:\[\]{}]+:(\s|$)/.test(body)) return { ok: false, stage: 'parse', line: i + 1, col: ind + body.length + 1, msg: 'could not find expected \':\' after mapping key "' + body.slice(0, 24) + '"' };
    }
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      let m = l.match(/^\s+(flag|block):\s*([^\s#]+)/);
      if (m && /thresholds/.test(lines.slice(Math.max(0, i - 3), i).join('\n'))) { const v = parseFloat(m[2]); if (isNaN(v) || v < 0 || v > 1) return { ok: false, stage: 'schema', line: i + 1, col: l.indexOf(m[2]) + 1, msg: 'controls.*.thresholds.' + m[1] + ' must be a number in [0, 1]' }; }
      m = l.match(/^strictness:\s*([^\s#]+)/);
      if (m && !STRICT[m[1]]) return { ok: false, stage: 'schema', line: i + 1, col: 13, msg: 'strictness must be one of permissive | balanced | strict' };
      m = l.match(/limit:\s*(-?[\d.]+)/);
      if (m && parseFloat(m[1]) < 0) return { ok: false, stage: 'schema', line: i + 1, col: l.indexOf(m[1]) + 1, msg: 'budget limit must be ≥ 0' };
    }
    return { ok: true };
  };

  /* ---------------- diff ---------------- */
  const lineDiff = (a, b) => {
    const n = a.length, m = b.length; const dp = []; for (let i = 0; i <= n; i++) dp.push(new Int16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    const ops = []; let i = 0, j = 0;
    while (i < n && j < m) { if (a[i] === b[j]) { ops.push({ t: 'ctx', s: a[i], ai: i, bi: j }); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) { ops.push({ t: 'del', s: a[i], ai: i }); i++; } else { ops.push({ t: 'add', s: b[j], bi: j }); j++; } }
    while (i < n) { ops.push({ t: 'del', s: a[i], ai: i }); i++; }
    while (j < m) { ops.push({ t: 'add', s: b[j], bi: j }); j++; }
    return ops;
  };
  const indentOf = (l) => l.match(/^\s*/)[0].length;
  const keyOf = (l) => { const m = l.replace(/(^|\s)#.*$/, '').match(/^\s*(?:- )?([^:\[\]{}]+):/); return m ? m[1].trim() : l.trim(); };
  const valOf = (l) => { const k = l.indexOf(':'); return k < 0 ? l.trim() : l.slice(k + 1).replace(/(^|\s)#.*$/, '').trim(); };
  const pathOf = (lines, idx) => {
    const parts = [keyOf(lines[idx])]; let cur = indentOf(lines[idx]);
    for (let k = idx - 1; k >= 0 && cur > 0; k--) {
      const l = lines[k]; if (!l.trim() || /^\s*#/.test(l)) continue;
      const ind = indentOf(l);
      if (ind < cur) { const sc = l.match(/^\s*- scope:\s*(\S+)/); parts.unshift(sc ? sc[1] : keyOf(l)); cur = ind; }
    }
    return parts.join('.');
  };
  const summarize = (ops, aLines, bLines) => {
    const out = []; let k = 0;
    while (k < ops.length) {
      if (ops[k].t === 'ctx') { k++; continue; }
      const dels = [], adds = [];
      while (k < ops.length && ops[k].t !== 'ctx') { (ops[k].t === 'del' ? dels : adds).push(ops[k]); k++; }
      const used = new Set();
      dels.forEach((d) => {
        if (!d.s.trim()) return;
        const ai = adds.findIndex((a, x) => !used.has(x) && keyOf(a.s) === keyOf(d.s));
        if (ai >= 0) { used.add(ai); out.push({ t: 'chg', path: pathOf(bLines, adds[ai].bi), from: valOf(d.s), to: valOf(adds[ai].s) }); }
        else out.push({ t: 'del', path: pathOf(aLines, d.ai) });
      });
      adds.forEach((a, x) => { if (!used.has(x) && a.s.trim()) out.push({ t: 'add', path: pathOf(bLines, a.bi), to: valOf(a.s) }); });
    }
    return out;
  };
  const sumText = (c) => c.t === 'chg' ? c.path + ' ' + c.from + ' → ' + c.to : c.t === 'add' ? '+ ' + c.path + (c.to ? ': ' + c.to : '') : '− ' + c.path;

  /* ---------------- commit (shared with approvals) ---------------- */
  const disabledIn = (text) => { const out = []; const re = /^ {2}([A-Z]{2,5}-\d{3}):\n(?: {4}.*\n)*? {4}enabled: false/gm; let m; while ((m = re.exec(text))) out.push(m[1]); return out; };
  A.commitPolicy = (text, o) => {
    const wasDraftClean = S.policyDraft === S.policyActive;
    const before = disabledIn(S.policyActive);
    S.policyVersion += 1;
    text = text.replace(/^version:\s*\d+/m, 'version: ' + S.policyVersion);
    S.policyActive = text; if (wasDraftClean || o.fromEditor) S.policyDraft = text;
    const nowDis = disabledIn(text);
    S.disabledControls = nowDis.map((id) => ({ id, by: A.member(o.by).name, at: A.u.hhmm(Date.now()), v: S.policyVersion, isNew: before.indexOf(id) < 0 }));
    versions.unshift({ v: S.policyVersion, by: o.by, ago: 'just now', note: o.note, ms: o.ms, fresh: true });
    A.bus.emit('versions');
    if (A.current === 'policy') A.rerender();
  };

  /* ---------------- view ---------------- */
  let ta, hl, gut;
  const refresh = () => {
    const text = ta.value; S.policyDraft = text;
    const lines = text.split('\n');
    hl.innerHTML = lines.map(hlLine).join('\n') + '\n';
    const v = validate(text); lastErr = v.ok ? null : v;
    const ops = lineDiff(S.policyActive.split('\n'), lines);
    const changed = new Set(ops.filter((o) => o.t === 'add').map((o) => o.bi));
    gut.innerHTML = lines.map((_, i) => '<div class="' + (lastErr && lastErr.line === i + 1 ? 'err' : changed.has(i) ? 'chg' : '') + '">' + (i + 1) + '</div>').join('') + '<div></div>';
    gut.scrollTop = ta.scrollTop;
    const dirty = text !== S.policyActive;
    $('#pe-tab').classList.toggle('dirty', dirty);
    $('#pe-status').innerHTML = (v.ok ? '<span class="ok">✓ valid</span>' : '<span class="err">✕ ' + esc(v.stage) + ' error · line ' + v.line + ':' + v.col + ' — ' + esc(v.msg) + '</span>') + '<span>YAML · UTF-8 · LF</span><span>' + lines.length + ' lines</span><span style="margin-left:auto">' + (dirty ? 'draft (unsaved) · base v' + S.policyVersion : 'in sync with active v' + S.policyVersion) + '</span>';
    drawDiff(ops);
    const btn = $('#pe-apply');
    btn.disabled = !dirty || applying;
    btn.innerHTML = A.state.role === 'member' ? A.icon('send', 14) + 'Request approval' : A.icon('zap', 14) + 'Validate & apply';
    const strict = (text.match(/^strictness:\s*(\w+)/m) || [])[1];
    if (strict && STRICT[strict]) { A.setSeg('pe-strict', strict); $('#pe-strict-note').innerHTML = 'INJ-003 block ≥ <b class="t1 mono">' + STRICT[strict].block + '</b> · measured TPR <b class="t1">' + STRICT[strict].tpr + '</b> · FPR <b class="t1">' + STRICT[strict].fpr + '</b> on the eval set'; }
  };
  const drawDiff = (ops) => {
    const aL = S.policyActive.split('\n'), bL = ta.value.split('\n');
    const changes = summarize(ops, aL, bL);
    const box = $('#pe-diff'); const sum = $('#pe-sum');
    if (!changes.length) { box.innerHTML = '<div class="diff-empty">No changes against active v' + S.policyVersion + '. Edit the YAML or use a quick edit.</div>'; sum.innerHTML = ''; return; }
    const show = new Set(); ops.forEach((o, i) => { if (o.t !== 'ctx') for (let k = i - 2; k <= i + 2; k++) show.add(k); });
    let html = '', prev = -2;
    ops.forEach((o, i) => {
      if (!show.has(i)) return;
      if (i !== prev + 1) html += '<div class="dl hunk">@@ line ' + ((o.bi != null ? o.bi : o.ai) + 1) + ' @@</div>';
      prev = i;
      html += '<div class="dl ' + o.t + '"><span class="ln">' + ((o.t === 'del' ? o.ai : o.bi) + 1) + '</span><span class="sg">' + (o.t === 'add' ? '+' : o.t === 'del' ? '−' : ' ') + '</span><span>' + esc(o.s) + '</span></div>';
    });
    box.innerHTML = html;
    sum.innerHTML = changes.slice(0, 5).map((c) => '<div class="row" style="gap:8px;font-size:12px;padding:3px 0"><span class="' + (c.t === 'chg' ? 'c-approval' : c.t === 'add' ? 'c-allow' : 'c-block') + '">' + A.icon(c.t === 'chg' ? 'commit' : c.t === 'add' ? 'plus' : 'minus', 13) + '</span><span class="mono t2 ellipsis" style="font-size:11.5px">' + esc(sumText(c)) + '</span></div>').join('');
  };

  const setSteps = (states) => {
    const names = [['Parse YAML', 6.1], ['Schema validate', 9.4], ['Compile controls · RE2 sets', 38.2], ['Self-test · 142 cases', 130.0], ['Atomic swap · 3 workers', 0.3]];
    $('#pe-steps').innerHTML = names.map((n, i) => { const st = states[i] || ''; return '<div class="step-row ' + st + '"><span class="si">' + (st === 'ok' ? A.icon('check', 11) : st === 'fail' ? A.icon('x', 11) : '') + '</span><span>' + n[0] + '</span><span class="ms">' + (st === 'ok' ? n[1].toFixed(1) + ' ms' : st === 'fail' ? 'failed' : st === 'run' ? '…' : '') + '</span></div>'; }).join('');
  };

  const apply = () => {
    if (applying) return;
    const text = ta.value; if (text === S.policyActive) return;
    const ops = lineDiff(S.policyActive.split('\n'), text.split('\n'));
    const changes = summarize(ops, S.policyActive.split('\n'), text.split('\n'));
    const me = A.me();
    if (S.role === 'member') {
      const needsOwner = /enabled: false/.test(text) && !/enabled: false/.test(S.policyActive);
      const payload = ops.filter((o) => o.t !== 'ctx').slice(0, 8).map((o) => (o.t === 'add' ? '+ ' : '- ') + o.s).join('\n');
      A.addApproval({ id: 'apr_01JB8' + A.u.ulid(5), kind: 'config', icon: 'fileCode', title: 'Policy change: ' + (changes[0] ? sumText(changes[0]) : 'catalog edit'), subject: { type: 'member', id: me.id, team: 'research' }, required: needsOwner ? 'owner' : 'admin', risk: needsOwner ? 'high' : 'medium', payload, diff: true, rule: 'approvals.config.change', ruleText: needsOwner ? 'disable control → Owner' : 'config change → Admin', why: 'Submitted from the policy editor.', context: [['Base version', 'v' + S.policyVersion], ['Changes', String(changes.length)], ['Validation', validate(text).ok ? 'passes schema' : 'fails — will be rejected']], signals: needsOwner ? ['Disables a control'] : [] });
      A.toast({ type: 'info', icon: 'send', title: 'Change submitted for approval', desc: 'Members can’t apply catalog changes. Routed to ' + (needsOwner ? 'Owner' : 'Admin') + ' with the diff attached.', meta: 'see Approvals inbox' });
      return;
    }
    applying = true; $('#pe-apply').disabled = true; $('#pe-apply').innerHTML = '<span class="spin"></span>Applying…';
    const v = validate(text);
    const failAt = v.ok ? -1 : v.stage === 'parse' ? 0 : 1;
    const states = [];
    let i = 0;
    const next = () => {
      states[i] = 'run'; setSteps(states);
      setTimeout(() => {
        if (i === failAt) {
          states[i] = 'fail'; setSteps(states); applying = false; refresh();
          A.toast({ type: 'error', icon: 'x', title: 'Rejected — still on v' + S.policyVersion, desc: 'line ' + v.line + ':' + v.col + ' — ' + esc(v.msg), meta: 'last-known-good v' + S.policyVersion + ' kept · audit config.rejected' });
          return;
        }
        states[i] = 'ok'; setSteps(states); i++;
        if (i < 5) next();
        else {
          applying = false;
          const prevDisabled = disabledIn(S.policyActive);
          A.commitPolicy(text, { by: me.id, note: changes.slice(0, 2).map(sumText).join('; ') || 'catalog edit', ms: 184, fromEditor: true });
          A.toast({ type: 'success', icon: 'zap', title: 'Policy v' + S.policyVersion + ' hot-reloaded in 184 ms', desc: changes.slice(0, 3).map((c) => '<span class="mono" style="font-size:11.5px">' + esc(sumText(c)) + '</span>').join('<br>') + '<br>142/142 self-tests passed · 3 workers swapped atomically', meta: 'audit config.reloaded · by ' + me.name });
          const nowDis = disabledIn(text).filter((x) => prevDisabled.indexOf(x) < 0);
          if (nowDis.length) setTimeout(() => A.toast({ type: 'warn', icon: 'shieldOff', title: nowDis.join(', ') + ' disabled by policy change', desc: 'Attacks in this class now pass. High-severity audit event written; `make test-live` shows DISABLED.' }), 450);
        }
      }, 230);
    };
    next();
  };

  const replaceDraft = (from, to, okMsg) => {
    if (ta.value.indexOf(from) < 0) { A.toast({ type: 'info', title: 'Nothing to change', desc: 'That edit is already in the draft.', duration: 2400 }); return false; }
    ta.value = ta.value.replace(from, to); refresh();
    const line = ta.value.slice(0, ta.value.indexOf(to)).split('\n').length;
    ta.scrollTop = Math.max(0, (line - 6) * 20); hl.scrollTop = ta.scrollTop; gut.scrollTop = ta.scrollTop;
    if (okMsg) A.toast({ type: 'info', icon: 'fileCode', title: okMsg, desc: 'Draft updated — review the diff, then apply.', duration: 2600 });
    return true;
  };
  A.policyQuick = (k) => {
    if (!ta || A.current !== 'policy') return;
    if (k === 'threshold') replaceDraft('      block: ' + ((ta.value.match(/^ {6}block: ([\d.]+)/m) || [])[1] || '0.85'), '      block: 0.50', 'INJ-003 block threshold → 0.50');
    if (k === 'disable') replaceDraft('  SEC-001:\n    name: Secrets & credentials\n    enabled: true', '  SEC-001:\n    name: Secrets & credentials\n    enabled: false\n    justification: "judge test — remove control"', 'SEC-001 disabled in draft');
    if (k === 'keyword') replaceDraft("    allow_domains: [acme-capital.pl, docs.acme.internal]\n", "    allow_domains: [acme-capital.pl, docs.acme.internal]\n  KW-010:\n    name: Block keyword “Goldman” (judge rule)\n    enabled: true\n    match: { literal: [goldman, \"goldman sachs\"] }\n    action: block\n    tests: { block: [\"tell me about Goldman\"], allow: [\"golden ratio\"] }\n", 'Keyword rule KW-010 added');
    if (k === 'break') replaceDraft('    thresholds:\n', '    thresholds\n', 'Introduced a YAML error');
    if (k === 'revert') { ta.value = S.policyActive; refresh(); }
  };

  A.views.policy = {
    render(root) {
      const dis = S.disabledControls;
      root.innerHTML =
        '<div class="page-head"><div><h1 class="page-title">Policy</h1><div class="page-sub">One YAML control catalog. Edits are validated, self-tested and swapped atomically — no request ever sees half a policy.</div></div>' +
        '<div class="actions"><span class="badge accent lg">' + A.icon('commit', 12) + 'Active v' + S.policyVersion + '</span><button class="btn secondary" id="pe-yaml">' + A.icon('download', 14) + 'catalog.yaml</button></div></div>' +
        dis.map((d) => '<div class="banner block"><span class="b-icon">' + A.icon('shieldOff', 15) + '</span><div><div class="b-title">' + d.id + ' disabled by policy change v' + d.v + '</div><div class="b-desc">Attacks in this class now pass through. High-severity audit event written · changed by ' + esc(d.by) + ' at ' + d.at + '.</div></div><div class="b-actions"><button class="btn sm secondary" data-reenable="' + d.id + '">' + A.icon('undo', 13) + 'Re-enable in draft</button></div></div>').join('') +
        '<div class="pe-layout"><div class="editor">' +
        '<div class="editor-tabs"><div class="editor-tab" id="pe-tab">' + A.icon('fileCode', 14) + '<span class="mono" style="font-size:12px">policies/catalog.yaml</span><span class="mod"></span></div><div class="et-right">' + A.icon('lock', 12) + 'schema aicl.catalog/1 · watched by watchfiles · <span class="kbd">⌘S</span> apply</div></div>' +
        '<div class="editor-body"><div class="gutter" id="pe-gut"></div><div class="code-wrap"><pre class="code-hl" id="pe-hl" aria-hidden="true"></pre><textarea class="code-ta" id="pe-ta" spellcheck="false" wrap="off" autocapitalize="off" autocomplete="off" aria-label="Policy YAML"></textarea></div></div>' +
        '<div class="editor-status" id="pe-status"></div></div>' +
        '<div class="col" style="gap:12px">' +
        '<div class="card"><div class="card-h"><div class="card-title">Strictness</div></div><div class="card-b">' + A.h.seg('pe-strict', [{ v: 'permissive', l: 'Permissive' }, { v: 'balanced', l: 'Balanced' }, { v: 'strict', l: 'Strict' }], 'balanced') + '<div class="t3" id="pe-strict-note" style="font-size:12px;margin-top:10px;line-height:18px"></div></div></div>' +
        '<div class="card"><div class="card-h"><div><div class="card-title">Quick edits</div><div class="card-sub">What judges usually try live</div></div></div><div class="card-b"><div class="quick">' +
        [['threshold', 'sliders', 'INJ-003 block → 0.50'], ['disable', 'shieldOff', 'Disable SEC-001'], ['keyword', 'plus', 'Block “Goldman”'], ['break', 'alert', 'Break the YAML'], ['revert', 'undo', 'Revert draft']].map((q) => '<button class="btn secondary sm" data-q="' + q[0] + '">' + A.icon(q[1], 13) + q[2] + '</button>').join('') + '</div></div></div>' +
        '<div class="card"><div class="card-h"><div><div class="card-title">Changes vs active</div><div class="card-sub">Line diff · semantic summary</div></div></div><div class="card-b"><div id="pe-sum" style="margin-bottom:8px"></div><div class="diff" id="pe-diff"></div></div>' +
        '<div class="card-b" style="border-top:1px solid var(--border-subtle);padding-top:12px"><div class="steps" id="pe-steps"></div><button class="btn primary lg" id="pe-apply" style="width:100%;margin-top:10px"></button><div class="t3" style="font-size:11.5px;margin-top:8px;text-align:center">Invalid catalogs are rejected — last-known-good stays active.</div></div></div>' +
        '<div class="card"><div class="card-h bordered"><div class="card-title">Version history</div><div class="right t3" style="font-size:12px">p95 reload 184 ms</div></div><div id="pe-vers">' +
        versions.slice(0, 6).map((v, i) => { const html = '<div class="ver-item ' + (i === 0 ? 'active ' : '') + (v.fresh ? 'arrive' : '') + '"><span class="vn">v' + v.v + '</span><div style="min-width:0"><div class="ellipsis mono" style="font-size:11.5px">' + esc(v.note) + '</div><div class="vd">' + esc(A.member(v.by).name) + ' · ' + esc(v.ago) + ' · ' + v.ms + ' ms</div></div>' + (i === 0 ? '<span class="badge allow">Active</span>' : '<button class="btn ghost sm icon" data-rb="' + v.v + '" data-tip="Roll back to v' + v.v + '">' + A.icon('undo', 13) + '</button>') + '</div>'; v.fresh = false; return html; }).join('') +
        '</div></div></div></div>';

      ta = $('#pe-ta'); hl = $('#pe-hl'); gut = $('#pe-gut');
      ta.value = S.policyDraft;
      setSteps([]);
      refresh();
      ta.addEventListener('input', refresh);
      ta.addEventListener('scroll', () => { hl.scrollTop = ta.scrollTop; hl.scrollLeft = ta.scrollLeft; gut.scrollTop = ta.scrollTop; });
      ta.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') { e.preventDefault(); const s = ta.selectionStart; ta.value = ta.value.slice(0, s) + '  ' + ta.value.slice(ta.selectionEnd); ta.selectionStart = ta.selectionEnd = s + 2; refresh(); }
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); apply(); }
      });
      $('#pe-apply').addEventListener('click', apply);
      $$('[data-q]', root).forEach((b) => b.addEventListener('click', () => A.policyQuick(b.dataset.q)));
      $$('[data-reenable]', root).forEach((b) => b.addEventListener('click', () => replaceDraft('  ' + b.dataset.reenable + ':\n    name: Secrets & credentials\n    enabled: false', '  ' + b.dataset.reenable + ':\n    name: Secrets & credentials\n    enabled: true', b.dataset.reenable + ' re-enabled in draft')));
      $$('[data-rb]', root).forEach((b) => b.addEventListener('click', () => A.toast({ type: 'info', icon: 'undo', title: 'Rollback to v' + b.dataset.rb + ' prepared', desc: 'Loaded as a draft on top of v' + S.policyVersion + ' — rollbacks go through the same validate → self-test → swap path.' })));
      $('#pe-yaml').addEventListener('click', () => A.toast({ type: 'success', icon: 'download', title: 'catalog.yaml downloaded', meta: 'v' + S.policyVersion + ' · sha256:' + A.u.hex(12) }));
      A.segHandlers['pe-strict'] = (v) => {
        let t = ta.value.replace(/^strictness:\s*\w+/m, (m) => 'strictness: ' + v);
        t = t.replace(/^( {6}block: )[\d.]+/m, '$1' + STRICT[v].block);
        ta.value = t; refresh();
      };
    },
    onRole() { if (ta) refresh(); }
  };
})(window.A);
