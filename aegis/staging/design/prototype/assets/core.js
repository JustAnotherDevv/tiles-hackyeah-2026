/* Aegis prototype — core runtime: utils, icons, overlays (tooltip/toast/modal/drawer/menu/cmdk), state, live engine. */
(function (A) {
  'use strict';

  /* ======================= utils ======================= */
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmtInt = (n) => Math.round(n).toLocaleString('en-US');
  const fmtUsd = (n, dp) => '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: dp == null ? 2 : dp, maximumFractionDigits: dp == null ? 2 : dp });
  const fmtPct = (n, dp) => (n * 100).toFixed(dp == null ? 0 : dp) + '%';
  const fmtMs = (ms) => ms >= 100 ? Math.round(ms) + ' ms' : ms >= 10 ? ms.toFixed(1) + ' ms' : ms >= 1 ? ms.toFixed(2) + ' ms' : ms.toFixed(2) + ' ms';
  const compact = (n) => n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + 'K' : String(Math.round(n));
  const pad = (n) => String(n).padStart(2, '0');
  const clock = (t) => { const d = new Date(t); return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()); };
  const hhmm = (t) => { const d = new Date(t); return pad(d.getHours()) + ':' + pad(d.getMinutes()); };
  const ago = (ms) => { const s = Math.max(0, Math.round(ms / 1000)); if (s < 5) return 'now'; if (s < 60) return s + 's'; const m = Math.round(s / 60); if (m < 60) return m + 'm'; const h = Math.round(m / 60); return h + 'h'; };
  const dur = (ms) => { let s = Math.max(0, Math.floor(ms / 1000)); const h = Math.floor(s / 3600); s -= h * 3600; const m = Math.floor(s / 60); s -= m * 60; return h > 0 ? h + 'h ' + pad(m) + 'm' : m + 'm ' + pad(s) + 's'; };
  const B32 = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
  const ulid = (n) => { let s = ''; for (let i = 0; i < (n || 16); i++) s += B32[Math.floor(Math.random() * 32)]; return s; };
  const hex = (n) => { let s = ''; for (let i = 0; i < n; i++) s += '0123456789abcdef'[Math.floor(Math.random() * 16)]; return s; };
  const initials = (name) => name.split(/[\s-]+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join('').toUpperCase();
  const AV = ['#B4B9FF', '#8EE3B4', '#F5D27A', '#F7A8C8', '#9CC8FF', '#FDBA8C', '#7FE0CF', '#CDB8FF'];
  const avColor = (name) => { let h = 0; for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0; return AV[h % AV.length]; };
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const debounce = (fn, ms) => { let t; return function () { const args = arguments; clearTimeout(t); t = setTimeout(() => fn.apply(null, args), ms); }; };
  A.views = A.views || {};
  A.u = { $, $$, esc, fmtInt, fmtUsd, fmtPct, fmtMs, compact, clock, hhmm, ago, dur, ulid, hex, initials, avColor, clamp, debounce, pad };

  /* ======================= icons (Lucide-style, 24 grid) ======================= */
  const P = {
    shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
    shieldCheck: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    shieldOff: '<path d="m2 2 20 20"/><path d="M5 5a1 1 0 0 0-1 1v7c0 5 3.5 7.5 7.67 8.94a1 1 0 0 0 .67.01c2.35-.82 4.48-1.97 5.9-3.71"/><path d="M9.309 3.652A12.252 12.252 0 0 0 11.24 2.28a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1v7a9.784 9.784 0 0 1-.08 1.264"/>',
    gauge: '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    activity: '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
    eyeOff: '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/>',
    inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    wallet: '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
    fileCode: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="m10 13-2 2 2 2"/><path d="m14 17 2-2-2-2"/>',
    radar: '<path d="M19.07 4.93A10 10 0 0 0 6.99 3.34"/><path d="M4 6h.01"/><path d="M2.29 9.62A10 10 0 1 0 21.31 8.35"/><path d="M16.24 7.76A6 6 0 1 0 8.23 16.67"/><path d="M12 18h.01"/><path d="M17.99 11.66A6 6 0 0 1 15.77 16.67"/><circle cx="12" cy="12" r="2"/><path d="m13.41 10.59 5.66-5.66"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    power: '<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.77.04"/>',
    chevDown: '<path d="m6 9 6 6 6-6"/>',
    chevRight: '<path d="m9 18 6-6-6-6"/>',
    chevUpDown: '<path d="m7 15 5 5 5-5"/><path d="m7 9 5-5 5 5"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    lock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    play: '<polygon points="6 3 20 12 6 21 6 3"/>',
    pause: '<rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
    plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
    minus: '<path d="M5 12h14"/>',
    arrowUpRight: '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
    arrowRight: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    arrowDown: '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    cpu: '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
    zap: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
    commit: '<circle cx="12" cy="12" r="3"/><line x1="3" x2="9" y1="12" y2="12"/><line x1="15" x2="21" y1="12" y2="12"/>',
    key: '<path d="m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4"/><path d="m21 2-9.6 9.6"/><circle cx="7.5" cy="15.5" r="5.5"/>',
    database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5V19A9 3 0 0 0 21 19V5"/><path d="M3 12A9 3 0 0 0 21 12"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    terminal: '<polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>',
    bot: '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
    refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    card: '<rect width="20" height="14" x="2" y="5" rx="2"/><line x1="2" x2="22" y1="10" y2="10"/>',
    sparkles: '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>',
    layers: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    hash: '<line x1="4" x2="20" y1="9" y2="9"/><line x1="4" x2="20" y1="15" y2="15"/><line x1="10" x2="8" y1="3" y2="21"/><line x1="16" x2="14" y1="3" y2="21"/>',
    dollar: '<line x1="12" x2="12" y1="2" y2="22"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    trendDown: '<polyline points="22 17 13.5 8.5 8.5 13.5 2 7"/><polyline points="16 17 22 17 22 11"/>',
    ban: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
    send: '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
    sliders: '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
    command: '<path d="M15 6v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3"/>',
    flask: '<path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/>',
    rss: '<path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1"/>',
    undo: '<path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/>',
    more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    server: '<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    skip: '<path d="M10.1 2.182a10 10 0 0 1 3.8 0"/><path d="M13.9 21.818a10 10 0 0 1-3.8 0"/><path d="M17.609 3.721a10 10 0 0 1 2.69 2.7"/><path d="M2.182 13.9a10 10 0 0 1 0-3.8"/><path d="M20.279 17.609a10 10 0 0 1-2.7 2.69"/><path d="M21.818 10.1a10 10 0 0 1 0 3.8"/><path d="M3.721 6.391a10 10 0 0 1 2.7-2.69"/><path d="M6.391 20.279a10 10 0 0 1-2.69-2.7"/>',
    split: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M12 3v18"/>',
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    mail: '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>'
  };
  A.icon = (name, size, cls) => '<svg class="' + (cls || '') + '" width="' + (size || 16) + '" height="' + (size || 16) + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (P[name] || P.info) + '</svg>';
  A.logo = (size) => '<svg width="' + (size || 16) + '" height="' + (size || 16) + '" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 2.5 4.5 5.4v6.1c0 4.6 3.1 8.3 7.5 10 4.4-1.7 7.5-5.4 7.5-10V5.4L12 2.5Z" fill="rgba(255,255,255,0.14)" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/><path d="M8.6 15.6 12 7.4l3.4 8.2M9.8 12.9h4.4" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  /* ======================= small HTML helpers ======================= */
  const DEC_LABEL = { allow: 'Allow', redact: 'Redact', approval: 'Approval', block: 'Block', downgrade: 'Downgrade' };
  A.h = {
    badge: (d, lg) => '<span class="badge ' + d + (lg ? ' lg' : '') + '"><span class="dot"></span>' + (DEC_LABEL[d] || d) + '</span>',
    role: (r) => '<span class="role-badge ' + r + '">' + (r === 'self' ? 'Self' : r === 'agent' ? 'Agent' : A.roles[r].label) + '</span>',
    avatar: (name, size) => '<span class="avatar ' + (size || '') + '" style="background:' + avColor(name) + '">' + esc(initials(name)) + '</span>',
    agentAv: (size) => '<span class="avatar agent ' + (size || '') + '">' + A.icon('bot', size === 'sm' ? 12 : 14) + '</span>',
    tag: (t, cls) => '<span class="tag ' + (cls || '') + '">' + esc(t) + '</span>',
    seg: (name, opts, val, cls) => '<div class="seg ' + (cls || '') + '" data-seg="' + name + '"><span class="ind"></span>' + opts.map((o) => '<button type="button" data-v="' + o.v + '" class="' + (o.v === val ? 'on' : '') + '">' + (o.icon ? A.icon(o.icon, 13) : '') + esc(o.l) + '</button>').join('') + '</div>',
    ubar: (ratio, state, cls) => '<div class="ubar ' + (cls || '') + '"><div class="fill ' + state + '" data-w="' + clamp(ratio, 0, 1) * 100 + '"></div><span class="mark" style="left:80%"></span><span class="mark m100" style="left:calc(100% - 1px)"></span></div>'
  };
  A.cap = (s) => String(s).charAt(0).toUpperCase() + String(s).slice(1);
  A.budgetState = (r) => r >= 1 ? 'hard' : r >= 0.8 ? 'soft' : r >= 0.5 ? 'watch' : 'ok';
  A.stateLabel = { ok: 'Healthy', watch: 'Watch', soft: 'Soft limit · downgrade', hard: 'Hard limit · blocking' };
  A.stateDot = { ok: 'ok', watch: 'ok', soft: 'warn', hard: 'crit' };

  /* grow usage bars after insert (so the width transition plays) */
  A.growBars = (root) => { requestAnimationFrame(() => requestAnimationFrame(() => { $$('.ubar .fill[data-w]', root).forEach((f) => { f.style.width = f.dataset.w + '%'; }); $$('.score-bar .f[data-w]', root).forEach((f) => { f.style.width = f.dataset.w + '%'; }); })); };

  /* ======================= segmented controls ======================= */
  A.segHandlers = {};
  A.positionSeg = (seg) => {
    const on = seg.querySelector('button.on'); const ind = seg.querySelector('.ind');
    if (!on || !ind) return;
    ind.style.width = on.offsetWidth + 'px';
    ind.style.transform = 'translateX(' + (on.offsetLeft - 2) + 'px)';
    ind.style.left = '2px';
  };
  A.initSegs = (root) => { $$('.seg', root).forEach(A.positionSeg); };
  document.addEventListener('click', (ev) => {
    const b = ev.target.closest('.seg button'); if (!b) return;
    const seg = b.closest('.seg'); if (b.classList.contains('on')) return;
    $$('button', seg).forEach((x) => x.classList.toggle('on', x === b));
    A.positionSeg(seg);
    const fn = A.segHandlers[seg.dataset.seg]; if (fn) fn(b.dataset.v, seg);
  });
  A.setSeg = (name, v) => { $$('.seg[data-seg="' + name + '"]').forEach((seg) => { $$('button', seg).forEach((x) => x.classList.toggle('on', x.dataset.v === v)); A.positionSeg(seg); }); };

  /* ======================= number tween ======================= */
  A.tween = (el, to, fmt, ms) => {
    if (!el) return;
    const from = parseFloat(el.dataset.val || '0'); el.dataset.val = to;
    const t0 = performance.now(), d = ms || 600;
    const step = (t) => { const p = Math.max(0, Math.min(1, (t - t0) / d)); const e = 1 - Math.pow(1 - p, 4); el.textContent = fmt(from + (to - from) * e); if (p < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  };

  /* ======================= tooltip ======================= */
  const tip = document.createElement('div'); tip.className = 'tooltip'; tip.setAttribute('role', 'tooltip');
  A.tip = {
    show(html, x, y) {
      if (!tip.isConnected) document.body.appendChild(tip);
      tip.innerHTML = html; tip.classList.add('show');
      const r = tip.getBoundingClientRect();
      let left = x + 14, top = y + 14;
      if (left + r.width > window.innerWidth - 8) left = x - r.width - 14;
      if (top + r.height > window.innerHeight - 8) top = y - r.height - 14;
      tip.style.left = Math.max(8, left) + 'px'; tip.style.top = Math.max(8, top) + 'px';
    },
    hide() { tip.classList.remove('show'); }
  };
  document.addEventListener('mousemove', (ev) => {
    const t = ev.target.closest && ev.target.closest('[data-tip]');
    if (t) A.tip.show(t.getAttribute('data-tip'), ev.clientX, ev.clientY);
    else if (!ev.target.closest || !ev.target.closest('[data-xhair]')) A.tip.hide();
  });

  /* ======================= toasts ======================= */
  A.toast = (o) => {
    let wrap = $('.toasts'); if (!wrap) { wrap = document.createElement('div'); wrap.className = 'toasts'; document.body.appendChild(wrap); }
    const icons = { success: 'check', error: 'x', warn: 'alert', info: 'zap' };
    const el = document.createElement('div'); el.className = 'toast ' + (o.type || 'info');
    const d = o.duration || 5200;
    el.innerHTML = '<div class="ti">' + A.icon(o.icon || icons[o.type || 'info'], 15) + '</div><div class="grow"><div class="tt">' + esc(o.title) + '</div>' + (o.desc ? '<div class="td">' + o.desc + '</div>' : '') + (o.meta ? '<div class="tm">' + esc(o.meta) + '</div>' : '') + '</div><button class="btn ghost sm icon" aria-label="Dismiss">' + A.icon('x', 14) + '</button><div class="tbar" style="animation-duration:' + d + 'ms"></div>';
    wrap.appendChild(el);
    const kill = () => { el.classList.add('out'); setTimeout(() => el.remove(), 280); };
    el.querySelector('button').addEventListener('click', kill);
    setTimeout(kill, d);
    while (wrap.children.length > 4) wrap.firstChild.remove();
  };

  /* ======================= overlay / drawer / modal ======================= */
  let overlay;
  const ensureOverlay = () => { if (!overlay) { overlay = document.createElement('div'); overlay.className = 'overlay'; document.body.appendChild(overlay); overlay.addEventListener('click', () => { A.drawer.close(); A.modal.close(); }); } return overlay; };

  A.drawer = {
    el: null,
    open(html, onMount) {
      ensureOverlay();
      if (!this.el) { this.el = document.createElement('aside'); this.el.className = 'drawer'; this.el.setAttribute('role', 'dialog'); this.el.setAttribute('aria-modal', 'true'); document.body.appendChild(this.el); }
      this.el.innerHTML = html;
      requestAnimationFrame(() => { overlay.classList.add('show'); this.el.classList.add('show'); });
      $$('[data-close]', this.el).forEach((b) => b.addEventListener('click', () => this.close()));
      if (onMount) onMount(this.el);
      A.growBars(this.el);
    },
    close() { if (this.el) this.el.classList.remove('show'); if (overlay && !A.modal.isOpen) overlay.classList.remove('show'); },
    get isOpen() { return !!(this.el && this.el.classList.contains('show')); }
  };

  A.modal = {
    wrap: null, isOpen: false,
    open(o) {
      ensureOverlay();
      if (!this.wrap) { this.wrap = document.createElement('div'); this.wrap.className = 'modal-wrap'; document.body.appendChild(this.wrap); this.wrap.addEventListener('mousedown', (e) => { if (e.target === this.wrap) this.close(); }); }
      this.wrap.innerHTML = '<div class="modal" role="dialog" aria-modal="true" style="' + (o.width ? 'width:' + o.width + 'px' : '') + '"><div class="modal-h"><h3>' + esc(o.title) + '</h3>' + (o.desc ? '<p>' + o.desc + '</p>' : '') + '</div><div class="modal-b">' + (o.body || '') + '</div><div class="modal-f">' +
        (o.actions || []).map((a, i) => '<button class="btn ' + (a.kind || 'secondary') + '" data-ai="' + i + '"' + (a.id ? ' id="' + a.id + '"' : '') + '>' + (a.icon ? A.icon(a.icon, 14) : '') + esc(a.label) + '</button>').join('') + '</div></div>';
      this.isOpen = true;
      requestAnimationFrame(() => { overlay.classList.add('show'); this.wrap.classList.add('show'); });
      $$('[data-ai]', this.wrap).forEach((b) => b.addEventListener('click', () => { const a = o.actions[+b.dataset.ai]; if (a.onClick) { if (a.onClick(this.wrap) === false) return; } this.close(); }));
      if (o.onMount) o.onMount(this.wrap);
      const first = this.wrap.querySelector('input, textarea, select'); if (first) setTimeout(() => first.focus(), 60);
    },
    close() { if (!this.wrap) return; this.wrap.classList.remove('show'); this.isOpen = false; if (overlay && !A.drawer.isOpen) overlay.classList.remove('show'); }
  };

  /* ======================= dropdown menu ======================= */
  A.menu = {
    el: null,
    open(anchor, items) {
      this.close();
      const m = document.createElement('div'); m.className = 'menu';
      m.innerHTML = items.map((it, i) => it.sep ? '<div class="menu-sep"></div>' : it.group ? '<div class="menu-group">' + esc(it.group) + '</div>' : '<button class="menu-item" data-i="' + i + '">' + (it.icon ? A.icon(it.icon, 14) : '') + '<span>' + esc(it.label) + '</span>' + (it.hint ? '<span class="hint">' + esc(it.hint) + '</span>' : '') + '</button>').join('');
      document.body.appendChild(m);
      const r = anchor.getBoundingClientRect(); const mw = m.offsetWidth;
      m.style.top = (r.bottom + 6) + 'px'; m.style.left = Math.max(8, Math.min(window.innerWidth - mw - 8, r.right - mw)) + 'px';
      requestAnimationFrame(() => m.classList.add('show'));
      $$('.menu-item', m).forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); const it = items[+b.dataset.i]; this.close(); if (it.onClick) it.onClick(); }));
      this.el = m;
      setTimeout(() => document.addEventListener('click', this._out = () => this.close(), { once: true }), 0);
    },
    close() { if (this.el) { this.el.remove(); this.el = null; } if (this._out) document.removeEventListener('click', this._out); }
  };

  /* ======================= event bus ======================= */
  const subs = {};
  A.bus = {
    on(n, fn) { (subs[n] = subs[n] || []).push(fn); },
    emit(n, d) { (subs[n] || []).forEach((fn) => { try { fn(d); } catch (e) { console.error(e); } }); }
  };

  /* ======================= state ======================= */
  A.state = {
    role: 'admin',
    live: true,
    events: [],
    counts: { requests: A.kpi.requests, blocked: A.kpi.blocked, redacted: A.kpi.redacted, approval: 37, allow: A.kpi.requests - A.kpi.blocked - A.kpi.redacted - 37, avoided: A.kpi.avoided },
    policyVersion: 14,
    policyActive: A.policyYaml,
    policyDraft: A.policyYaml,
    feedSerial: 43,
    feedBanner: true,
    kill: null,
    approvals: A.approvals.map((a) => Object.assign({ created: Date.now() - a.createdAgo, expires: Date.now() + a.expiresIn }, a)),
    history: A.approvalHistory.slice(),
    disabledControls: []
  };
  A.me = () => A.member(A.viewAs[A.state.role]);
  A.canApprove = (ap) => {
    const r = A.state.role;
    if (ap.required === 'member') return ap.selfOnly ? (A.viewAs[r] === ap.selfOnly || A.roles[r].rank >= 2) : true;
    return A.roles[r].rank >= A.roles[ap.required].rank;
  };
  A.setRole = (r) => {
    if (A.state.role === r) return;
    A.state.role = r; A.setSeg('role', r);
    A.bus.emit('role', r);
    const m = A.me();
    A.toast({ type: 'info', icon: 'user', title: 'Viewing as ' + A.roles[r].label, desc: esc(m.name) + ' · ' + esc(m.title), duration: 2600 });
  };

  /* ======================= live engine ======================= */
  const totalW = A.templates.reduce((s, t) => s + t.w, 0);
  const pickTemplate = () => { let r = Math.random() * totalW; for (const t of A.templates) { r -= t.w; if (r <= 0) return t; } return A.templates[0]; };
  const jit = (v, a, b) => v * (a + Math.random() * (b - a));

  A.buildStages = (e) => {
    const hitIdx = e.hit ? A.pipeline.findIndex((p) => p.key === e.hit) : -1;
    const shortCircuit = e.decision === 'block' && hitIdx >= 0;
    const hitClass = e.hitAs || e.decision;
    const team = A.team(e.team);
    return A.pipeline.map((p, i) => {
      const s = { key: p.key, name: p.name, ctrl: p.ctrl, sub: p.sub, status: 'pass', ms: jit(p.ms, 0.7, 1.35), score: null, th: p.th, max: p.max, unit: p.unit, note: '' };
      if (p.key === 'judge') { s.status = 'skip'; s.ms = 0; s.note = 'not escalated — outside grey zone 0.60–0.85'; }
      if (shortCircuit && i > hitIdx && p.key !== 'policy') { s.status = 'skip'; s.ms = 0; s.note = 'short-circuit after definitive block'; }
      if (p.key === 'inj' && s.status !== 'skip') { s.score = (e.scores && e.scores.inj != null) ? e.scores.inj : 0.03; s.ms = jit(6.2, 0.6, 1.5); }
      if (p.key === 'secrets' && s.status !== 'skip') s.score = (e.scores && e.scores.secrets) || +(2.1 + Math.random() * 1.2).toFixed(2);
      if (p.key === 'pii' && s.status !== 'skip') { s.score = (e.scores && e.scores.pii != null) ? e.scores.pii : 0; s.note = e.hit === 'pii' ? (e.entities || 3) + ' entities' : '0 entities'; }
      if (p.key === 'budget' && s.status !== 'skip') { s.score = (e.scores && e.scores.budget) || +(0.05 + Math.random() * 0.3).toFixed(2); s.note = e.hit === 'budget' ? (e.decision === 'block' ? 'agent/' + e.agent + ' · hard limit' : 'team/' + (team ? team.id : '') + ' · soft limit') : 'session $' + (s.score * 0.5).toFixed(2) + ' / $0.50'; }
      if (p.key === 'loop' && s.status !== 'skip') { s.score = (e.scores && e.scores.loop) || 1; }
      if (p.key === 'sigs' && s.status !== 'skip') s.note = e.hit === 'sigs' ? (e.ctl || '').replace('SIG:', '') + ' matched' : '0 / 19 matched';
      if (p.key === 'approval' && s.status !== 'skip') s.note = e.hit === 'approval' ? 'rule ' + e.ctl + ' → ' + (e.ctl === 'APR-DB-PII' || e.ctl === 'APR-SPEND' ? 'Admin' : 'Admin') : 'no approval rule matched';
      if (p.key === 'policy') { s.note = e.decision + (e.tag ? ' (' + e.tag + ')' : '') + ' · catalog v' + A.state.policyVersion; s.status = 'final'; }
      if (i === hitIdx) { s.status = 'hit'; s.hitClass = hitClass; }
      if (p.key === 'sigs' && e.ctl === 'OUT-005') { s.status = 'hit'; s.hitClass = 'redact'; s.note = 'AICL-TI-014 matched'; }
      return s;
    });
  };

  A.makeEvent = (tpl, ts) => {
    const ag = A.agent(tpl.agent);
    let e = Object.assign({}, tpl, { id: 'req_01JB' + ulid(18), trace: hex(32), session: 'sess_' + hex(6), ts: ts || Date.now(), team: ag ? ag.team : 'eng' });
    if (A.state.kill && (A.state.kill.scope === 'global' || A.state.kill.agents.indexOf(e.agent) >= 0)) {
      e = Object.assign(e, { decision: 'block', tag: null, ctl: 'KILL-001', hit: 'policy', reason: 'Kill switch engaged for ' + (A.state.kill.scope === 'global' ? 'all agents' : 'agent/' + e.agent) + ' — request refused, in-flight streams cancelled.', cost: 0 });
    }
    e.stages = A.buildStages(e);
    e.overhead = e.stages.reduce((s, x) => s + (x.status === 'skip' ? 0 : x.ms), 0);
    e.upstream = (e.decision === 'block' || e.decision === 'approval') ? 0 : (e.local ? jit(520, 0.6, 1.6) : jit(880, 0.6, 1.6));
    e.cost = e.cost || 0;
    return e;
  };

  const pushEvent = (e) => {
    const S = A.state;
    S.events.unshift(e); if (S.events.length > 400) S.events.length = 400;
    S.counts.requests += 1 + Math.floor(Math.random() * 3);
    if (S.counts[e.decision] != null) S.counts[e.decision] += 1;
    if (e.avoided) S.counts.avoided += e.avoided;
    A.bus.emit('event', e);
  };
  A.emitTemplate = (tpl) => { const e = A.makeEvent(tpl); pushEvent(e); return e; };

  A.seedEvents = () => {
    const now = Date.now();
    for (let i = 60; i > 0; i--) { const e = A.makeEvent(pickTemplate(), now - i * 2600 - Math.random() * 1500); A.state.events.unshift(e); }
  };

  let timer = null;
  const loop = () => {
    if (A.state.live) pushEvent(A.makeEvent(pickTemplate()));
    timer = setTimeout(loop, 1100 + Math.random() * 1500);
  };
  A.startLive = () => { if (!timer) timer = setTimeout(loop, 900); };
  A.setLive = (on) => { A.state.live = on; A.bus.emit('live', on); };

  /* ======================= command palette ======================= */
  A.cmdk = {
    wrap: null, items: [], idx: 0,
    open() {
      if (!this.wrap) {
        this.wrap = document.createElement('div'); this.wrap.className = 'cmdk-wrap';
        this.wrap.innerHTML = '<div class="cmdk" role="dialog" aria-label="Command palette"><div class="cmdk-in">' + A.icon('search', 16) + '<input placeholder="Search views, simulate attacks, switch role…" aria-label="Command"><span class="kbd">esc</span></div><div class="cmdk-list"></div><div class="cmdk-f"><span><span class="kbd">↑</span><span class="kbd">↓</span> navigate</span><span><span class="kbd">↵</span> run</span><span style="margin-left:auto">Aegis · policy v<b class="pv"></b></span></div></div>';
        document.body.appendChild(this.wrap);
        this.wrap.addEventListener('mousedown', (e) => { if (e.target === this.wrap) this.close(); });
        const inp = this.wrap.querySelector('input');
        inp.addEventListener('input', () => { this.idx = 0; this.render(inp.value); });
        inp.addEventListener('keydown', (e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); this.idx = Math.min(this.idx + 1, this.filtered.length - 1); this.render(inp.value, true); }
          else if (e.key === 'ArrowUp') { e.preventDefault(); this.idx = Math.max(this.idx - 1, 0); this.render(inp.value, true); }
          else if (e.key === 'Enter') { e.preventDefault(); const it = this.filtered[this.idx]; if (it) { this.close(); it.run(); } }
        });
      }
      this.wrap.querySelector('.pv').textContent = A.state.policyVersion;
      const inp = this.wrap.querySelector('input'); inp.value = ''; this.idx = 0; this.render('');
      this.wrap.classList.add('show'); setTimeout(() => inp.focus(), 30);
    },
    close() { if (this.wrap) this.wrap.classList.remove('show'); },
    get isOpen() { return !!(this.wrap && this.wrap.classList.contains('show')); },
    render(q, keepScroll) {
      const all = A.commands();
      const qq = q.trim().toLowerCase();
      this.filtered = all.filter((c) => !qq || (c.label + ' ' + c.group).toLowerCase().indexOf(qq) >= 0);
      let html = '', g = null;
      this.filtered.forEach((c, i) => { if (c.group !== g) { g = c.group; html += '<div class="cmdk-group">' + esc(g) + '</div>'; } html += '<div class="cmdk-item ' + (i === this.idx ? 'on' : '') + '" data-i="' + i + '">' + A.icon(c.icon, 15) + '<span>' + esc(c.label) + '</span>' + (c.hint ? '<span class="hint">' + esc(c.hint) + '</span>' : '') + '</div>'; });
      const list = this.wrap.querySelector('.cmdk-list'); list.innerHTML = html || '<div class="empty">No results</div>';
      $$('.cmdk-item', list).forEach((el) => {
        el.addEventListener('mouseenter', () => { this.idx = +el.dataset.i; $$('.cmdk-item', list).forEach((x) => x.classList.toggle('on', x === el)); });
        el.addEventListener('click', () => { const it = this.filtered[+el.dataset.i]; this.close(); it.run(); });
      });
      const on = list.querySelector('.cmdk-item.on'); if (on && keepScroll) on.scrollIntoView({ block: 'nearest' });
    }
  };
})(window.A);
