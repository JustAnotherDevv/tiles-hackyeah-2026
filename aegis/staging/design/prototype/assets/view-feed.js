/* View 7 — Threat feed status (signed, external signature feed) */
(function (A) {
  'use strict';
  const { $, $$, esc, fmtInt, dur } = A.u;
  const S = A.state;
  S.feedUpdatedAt = Date.now() - A.feed.publishedAgo * 1000;
  S.feedExpires = Date.now() + A.feed.expiresIn * 1000;
  S.feedEvents = A.feed.events.slice();
  S.feedRejected = { serial: 44, at: A.u.clock(Date.now() - 64000) };
  const sigs = A.signatures.slice();
  const r = A.seeded(77);
  sigs.forEach((s) => { s.spark = Array.from({ length: 12 }, () => s.hits ? Math.round(s.hits / 12 * (0.2 + r() * 1.6)) : 0); });

  const ACTION_BADGE = { block: 'block', approval: 'approval', redact: 'redact', alert: 'neutral' };
  const ST = { active: ['ok', 'Active — enforcing'], monitor: ['warn', 'Monitor — logs only'], withdrawn: ['idle', 'Withdrawn (OSV-style, never deleted)'] };
  const sigRow = (s) => '<tr class="' + (s._new ? 'new' : '') + '" style="' + (s.status === 'withdrawn' ? 'opacity:0.5' : '') + '"><td class="mono" style="font-size:11.5px"><span class="row" style="gap:8px" data-tip="' + esc(ST[s.status][1]) + '"><span class="status-dot ' + ST[s.status][0] + '"></span>' + s.id + '</span></td><td style="max-width:240px;overflow:hidden;text-overflow:ellipsis"><span style="font-weight:500">' + esc(s.name) + '</span><span class="sub mono">' + esc(s.ref) + ' · ' + esc(s.matcher) + '</span></td><td><span class="tag">' + esc(s.surface) + '</span></td><td><span class="badge ' + ACTION_BADGE[s.action] + '"><span class="dot"></span>' + A.cap(s.action) + '</span></td><td class="r"><div class="row" style="justify-content:flex-end;gap:10px"><div class="mini-bars ' + (s.hits > 50 ? 'hot' : '') + '">' + s.spark.map((v) => '<i style="height:' + Math.max(2, Math.min(18, v / Math.max(1, Math.max.apply(null, s.spark)) * 18)) + 'px"></i>').join('') + '</div><span class="num" style="width:34px;text-align:right">' + fmtInt(s.hits) + '</span></div></td></tr>';

  const banner = () => S.feedBanner ? '<div class="banner block" id="fd-banner"><span class="b-icon">' + A.icon('shieldOff', 15) + '</span><div><div class="b-title">Tampered bundle rejected — serial #' + S.feedRejected.serial + '</div><div class="b-desc">Ed25519 signature did not verify: bundle bytes were modified after signing (sha256 mismatch vs <span class="mono">latest.json</span>). Enforcement remains on <b class="t1">#' + S.feedSerial + '</b> (last-known-good). No signature was loaded from the rejected bundle.</div><div class="b-meta">feed.rejected reason=bad_signature · key RWQf6LRC…GFO3 · ' + S.feedRejected.at + '</div></div><div class="b-actions"><button class="btn sm secondary" id="fd-audit">' + A.icon('hash', 13) + 'Audit event</button><button class="btn sm ghost icon" id="fd-dismiss" aria-label="Dismiss">' + A.icon('x', 14) + '</button></div></div>' : '';

  const tl = () => S.feedEvents.map((e) => '<div class="tl-item ' + (e._new ? 'arrive' : '') + '"><span class="tl-dot ' + e.kind + '">' + A.icon(e.kind === 'ok' ? 'check' : e.kind === 'bad' ? 'x' : 'info', 10) + '</span><div><div class="tl-title mono" style="font-size:12px">' + esc(e.title) + '</div><div class="tl-desc">' + esc(e.desc) + '</div><div class="tl-time">' + esc(e.ago) + '</div></div></div>').join('');

  const statusCells = () => {
    const act = sigs.filter((s) => s.status === 'active').length, mon = sigs.filter((s) => s.status === 'monitor').length, wd = sigs.filter((s) => s.status === 'withdrawn').length;
    return [
      ['Active serial', '<span class="serial-flip" id="fd-serial">#' + S.feedSerial + '</span>', A.feed.version.replace(/-\d+$/, '-' + (S.feedSerial - 39))],
      ['Signature', '<span class="c-allow row" style="gap:6px">' + A.icon('shieldCheck', 18) + 'Verified</span>', 'ed25519 · ' + A.feed.keyId],
      ['Last update', '<span id="fd-age">' + A.u.ago(Date.now() - S.feedUpdatedAt) + ' ago</span>', 'SSE push · poll 10 s · ETag'],
      ['Expires', '<span id="fd-exp">' + dur(S.feedExpires - Date.now()) + '</span>', 'freshness window 24 h'],
      ['Signatures', act + ' <span class="t3" style="font-size:13px;font-weight:500">active</span>', mon + ' monitor · ' + wd + ' withdrawn · compile ' + A.feed.compileMs + ' ms']
    ].map((c) => '<div class="fs-cell"><div class="fl">' + c[0] + '</div><div class="fv">' + c[1] + '</div><div class="fd">' + esc(c[2]) + '</div></div>').join('');
  };

  const steps = (bad) => [['Fetch latest.json', '4 ms'], ['Verify minisign (pinned key)', bad ? 'failed' : '0.3 ms'], ['sha256 == latest.sha256', bad ? 'skipped' : '0.1 ms'], ['JSON-Schema + limits', bad ? 'skipped' : '2 ms'], ['Run 412 inline test vectors', bad ? 'skipped' : '61 ms'], ['Compile RE2 / Aho-Corasick', bad ? 'skipped' : '38 ms'], ['Atomic swap · anti-rollback', bad ? 'kept #' + S.feedSerial : '0.2 ms']].map((x, i) => '<div class="step-row ' + (bad && i === 1 ? 'fail' : bad && i > 1 ? '' : 'ok') + '"><span class="si">' + (bad && i === 1 ? A.icon('x', 11) : bad && i > 1 ? '' : A.icon('check', 11)) + '</span><span>' + x[0] + '</span><span class="ms">' + x[1] + '</span></div>').join('');

  const draw = () => {
    $('#fd-banner-wrap').innerHTML = banner();
    $('#fd-status').innerHTML = statusCells();
    $('#fd-body').innerHTML = sigs.map(sigRow).join('');
    sigs.forEach((s) => { delete s._new; });
    $('#fd-tl').innerHTML = tl();
    S.feedEvents.forEach((e) => { delete e._new; });
    $('#fd-steps').innerHTML = steps(S.feedLastBad);
    const d = $('#fd-dismiss'); if (d) d.addEventListener('click', () => { S.feedBanner = false; draw(); A.refreshShell(); });
    const au = $('#fd-audit'); if (au) au.addEventListener('click', () => A.toast({ type: 'info', icon: 'hash', title: 'feed.rejected', desc: '<span class="mono" style="font-size:11.5px">{"event_type":"feed.rejected","serial":' + S.feedRejected.serial + ',"reason":"bad_signature","kept_serial":' + S.feedSerial + '}</span>', duration: 6000 }));
  };

  A.feedTamper = () => {
    S.feedRejected = { serial: S.feedSerial + 1, at: A.u.clock(Date.now()) };
    S.feedBanner = true; S.feedLastBad = true;
    S.feedEvents.unshift({ kind: 'bad', title: 'feed.rejected · serial #' + (S.feedSerial + 1), desc: 'bad_signature — bundle edited without re-signing. Kept #' + S.feedSerial + '.', ago: 'just now', _new: true });
    if (A.current === 'feed') draw();
    A.refreshShell();
    A.toast({ type: 'error', icon: 'shieldOff', title: 'Feed bundle #' + (S.feedSerial + 1) + ' rejected', desc: 'Ed25519 verification failed — enforcement stays on #' + S.feedSerial + ' (last-known-good).', meta: 'feed.rejected reason=bad_signature' });
  };
  const publish = () => {
    const next = S.feedSerial + 1;
    S.feedSerial = next; S.feedUpdatedAt = Date.now(); S.feedExpires = Date.now() + 24 * 3600e3; S.feedLastBad = false; S.feedBanner = false;
    if (!sigs.find((s) => s.id === 'AICL-TI-020')) sigs.splice(19, 0, { id: 'AICL-TI-020', name: 'Crescendo multi-turn escalation', ref: 'MSR 2024', surface: 'llm.request', matcher: 'semantic', action: 'block', status: 'monitor', hits: 0, spark: Array(12).fill(0), _new: true });
    S.feedEvents.unshift({ kind: 'ok', title: 'feed.updated · #' + (next - 1) + ' → #' + next, desc: 'TI-020 added in monitor mode · 418 vectors passed · signature verified.', ago: 'just now', _new: true });
    draw(); A.bus.emit('versions');
    const s = $('#fd-serial'); if (s) { s.classList.remove('serial-flip'); void s.offsetWidth; s.classList.add('serial-flip'); }
    A.toast({ type: 'success', icon: 'radar', title: 'Feed #' + next + ' verified & active in 1.1 s', desc: 'Signature ✓ · 418/418 vectors ✓ · compiled in 41 ms · every decision now stamped feed_serial=' + next });
  };

  A.views.feed = {
    render(root) {
      root.innerHTML =
        '<div class="page-head"><div><h1 class="page-title">Threat feed</h1><div class="page-sub">Historical-exploit signatures from an externally managed intel service — signed, verified against a pinned key, self-tested and hot-swapped. Refuses rollback.</div></div>' +
        '<div class="actions"><button class="btn secondary" id="fd-check">' + A.icon('refresh', 14) + 'Check now</button><button class="btn secondary" id="fd-tamper">' + A.icon('alert', 14) + 'Simulate tamper</button><button class="btn primary" id="fd-pub">' + A.icon('upload', 14) + 'Simulate publish</button></div></div>' +
        '<div id="fd-banner-wrap"></div>' +
        '<div class="card mb-3"><div class="fs-grid" id="fd-status"></div></div>' +
        '<div class="grid g-12"><div class="card span-8"><div class="card-h bordered"><div><div class="card-title">Signatures</div><div class="card-sub">Closed matcher set · RE2 (no ReDoS) · positive + negative vectors per signature · source <span class="mono">' + esc(A.feed.source) + '</span></div></div></div>' +
        '<div class="table-scroll"><table class="table tall"><thead><tr><th>ID · status</th><th>Attack · ref · matcher</th><th>Surface</th><th>Action</th><th class="r">Hits · 24h</th></tr></thead><tbody id="fd-body"></tbody></table></div></div>' +
        '<div class="col span-4" style="gap:12px"><div class="card"><div class="card-h bordered"><div class="card-title">Update pipeline</div><div class="right t3" style="font-size:12px">fail-closed</div></div><div class="card-b"><div class="steps" id="fd-steps"></div></div></div>' +
        '<div class="card"><div class="card-h bordered"><div class="card-title">Feed events</div></div><div class="timeline" id="fd-tl"></div></div></div></div>';
      draw();
      $('#fd-tamper').addEventListener('click', A.feedTamper);
      $('#fd-pub').addEventListener('click', publish);
      $('#fd-check').addEventListener('click', () => A.toast({ type: 'info', icon: 'refresh', title: 'Feed is current', desc: 'latest.json serial #' + S.feedSerial + ' · ETag unchanged · next poll in 10 s', duration: 2600 }));
    },
    onTick() { const a = $('#fd-age'); if (a) a.textContent = A.u.ago(Date.now() - S.feedUpdatedAt) + ' ago'; const e = $('#fd-exp'); if (e) e.textContent = dur(S.feedExpires - Date.now()); }
  };
})(window.A);
