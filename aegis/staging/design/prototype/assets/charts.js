/* Aegis prototype — dependency-free SVG chart primitives.
   Specs (from the data-viz method): bars ≤ 24px with 4px rounded data-end, 2px surface gap
   between stacked segments, 2px lines, ≥ 8px markers with a 2px surface ring, hairline solid grid,
   10% area wash, legend for ≥ 2 series, hover layer on every plot. */
(function (A) {
  'use strict';
  const { esc } = A.u;
  const SURFACE = '#0E1013';
  const C = {};

  const niceMax = (v) => { if (v <= 0) return 1; const e = Math.pow(10, Math.floor(Math.log10(v))); const f = v / e; const n = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10; return n * e; };
  const roundTop = (x, y, w, h, r) => { r = Math.min(r, w / 2, h); if (h <= 0) return ''; return 'M' + x + ',' + (y + h) + 'V' + (y + r) + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y + 'H' + (x + w - r) + 'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) + 'V' + (y + h) + 'Z'; };
  const roundRight = (x, y, w, h, r) => { r = Math.min(r, h / 2, w); if (w <= 0) return ''; return 'M' + x + ',' + y + 'H' + (x + w - r) + 'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) + 'V' + (y + h - r) + 'Q' + (x + w) + ',' + (y + h) + ' ' + (x + w - r) + ',' + (y + h) + 'H' + x + 'Z'; };
  const mix = (a, b, t) => { const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16)); const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16)); return '#' + pa.map((v, i) => Math.round(v + (pb[i] - v) * t).toString(16).padStart(2, '0')).join(''); };
  C.mix = mix;
  const tipRows = (title, rows) => '<div class="tt-title">' + esc(title) + '</div>' + rows.map((r) => '<div class="tt-row">' + (r.c ? '<span class="sw" style="background:' + r.c + '"></span>' : '') + esc(r.l) + '<b>' + esc(r.v) + '</b></div>').join('');
  C.tipRows = tipRows;
  const legend = (items) => '<div class="legend">' + items.map((it) => '<span class="li">' + (it.line ? '<span class="ln' + (it.dash ? ' dash' : '') + '" style="background:' + it.c + '"></span>' : '<span class="sw" style="background:' + it.c + '"></span>') + esc(it.l) + '</span>').join('') + '</div>';
  C.legend = legend;

  /* ---------- sparkline (single series → no legend) ---------- */
  C.spark = (values, color, opts) => {
    const o = opts || {}; const w = o.w || 160, h = o.h || 28, p = 3;
    const mx = Math.max.apply(null, values), mn = Math.min.apply(null, values) * (o.zero ? 0 : 0.85);
    const x = (i) => p + i * (w - 2 * p) / (values.length - 1);
    const y = (v) => h - p - (v - mn) / ((mx - mn) || 1) * (h - 2 * p);
    const pts = values.map((v, i) => x(i).toFixed(1) + ',' + y(v).toFixed(1));
    const last = values.length - 1;
    return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" width="100%" height="' + h + '" aria-hidden="true">' +
      '<path d="M' + pts.join('L') + 'L' + x(last) + ',' + h + 'L' + x(0) + ',' + h + 'Z" fill="' + color + '" fill-opacity="0.10"/>' +
      '<path d="M' + pts.join('L') + '" fill="none" stroke="' + color + '" stroke-width="1.75" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>' +
      '</svg>';
  };

  /* ---------- ring gauge ---------- */
  C.ring = (value, opts) => {
    const o = opts || {}; const s = o.size || 64, sw = o.stroke || 6, r = (s - sw) / 2, c = 2 * Math.PI * r;
    const off = c * (1 - value / 100);
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 ' + s + ' ' + s + '" aria-label="' + value + ' out of 100"><circle cx="' + s / 2 + '" cy="' + s / 2 + '" r="' + r + '" fill="none" stroke="#1E2228" stroke-width="' + sw + '"/>' +
      '<circle class="ring-arc" cx="' + s / 2 + '" cy="' + s / 2 + '" r="' + r + '" fill="none" stroke="' + (o.color || '#3CCB7F') + '" stroke-width="' + sw + '" stroke-linecap="round" stroke-dasharray="' + c.toFixed(1) + '" stroke-dashoffset="' + c.toFixed(1) + '" data-off="' + off.toFixed(1) + '" transform="rotate(-90 ' + s / 2 + ' ' + s / 2 + ')" style="transition:stroke-dashoffset 1100ms cubic-bezier(0.16,1,0.3,1)"/>' +
      (o.label ? '<text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" style="font: 600 ' + (o.fs || 18) + 'px var(--font-sans); fill: var(--text-1); letter-spacing:-0.02em">' + o.label + '</text>' : '') + '</svg>';
  };
  C.animateRings = (root) => requestAnimationFrame(() => requestAnimationFrame(() => A.u.$$('.ring-arc', root).forEach((a) => a.setAttribute('stroke-dashoffset', a.dataset.off))));

  /* redraw a chart whenever its container width changes (layout, sidebar collapse, emulation) */
  const watch = (el, redraw) => {
    el._w = el.clientWidth; el._redraw = redraw;
    if (el._ro || typeof ResizeObserver === 'undefined') return;
    el._ro = new ResizeObserver(() => {
      cancelAnimationFrame(el._raf);
      el._raf = requestAnimationFrame(() => { if (el.isConnected && Math.abs(el.clientWidth - el._w) > 2) el._redraw(); });
    });
    el._ro.observe(el);
  };

  /* ---------- stacked columns ---------- */
  C.stacked = (el, cfg) => {
    watch(el, () => C.stacked(el, cfg));
    const W = Math.max(320, el.clientWidth), H = cfg.height || 220;
    const m = { l: 40, r: 8, t: (cfg.annotations || []).some((a) => a.row) ? 32 : 18, b: 24 };
    const pw = W - m.l - m.r, ph = H - m.t - m.b, n = cfg.labels.length;
    const totals = cfg.labels.map((_, i) => cfg.series.reduce((s, se) => s + se.values[i], 0));
    const ymax = niceMax(Math.max.apply(null, totals) * 1.05);
    const band = pw / n, bw = Math.min(24, band * 0.64);
    const y = (v) => ph * v / ymax;
    let g = '<g class="grid">';
    [0, 0.25, 0.5, 0.75, 1].forEach((f) => { const yy = m.t + ph - ph * f; g += '<line x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + yy + '" y2="' + yy + '"/>'; });
    g += '</g>';
    let ticks = '';
    [0, 0.5, 1].forEach((f) => { const yy = m.t + ph - ph * f; ticks += '<text x="' + (m.l - 8) + '" y="' + (yy + 3.5) + '" text-anchor="end">' + A.u.compact(ymax * f) + '</text>'; });
    let bars = '', xl = '';
    cfg.labels.forEach((lab, i) => {
      const x = m.l + band * i + (band - bw) / 2;
      let acc = 0; let col = '<g class="hov hov-dim">';
      const nonzero = cfg.series.map((se) => se.values[i] > 0);
      const topIdx = nonzero.lastIndexOf(true);
      cfg.series.forEach((se, si) => {
        const v = se.values[i]; if (v <= 0) return;
        const hgt = y(v); const gap = acc > 0 ? 2 : 0;
        const yTop = m.t + ph - y(acc) - hgt;
        const hh = Math.max(0.5, hgt - gap);
        if (si === topIdx) col += '<path d="' + roundTop(x, yTop, bw, hh, 3) + '" fill="' + se.color + '"/>';
        else col += '<rect x="' + x + '" y="' + yTop + '" width="' + bw + '" height="' + hh + '" fill="' + se.color + '"/>';
        acc += v;
      });
      const tip = tipRows(cfg.tipTitle ? cfg.tipTitle(i) : lab, cfg.series.map((se) => ({ c: se.color, l: se.label, v: A.u.fmtInt(se.values[i]) })).reverse().concat([{ l: 'Total', v: A.u.fmtInt(totals[i]) }]));
      col += '<rect x="' + (m.l + band * i) + '" y="' + m.t + '" width="' + band + '" height="' + ph + '" fill="transparent" data-tip="' + esc(tip) + '"/>';
      col += '</g>';
      bars += col;
      if (cfg.xEvery ? i % cfg.xEvery === 0 : true) xl += '<text x="' + (x + bw / 2) + '" y="' + (H - 6) + '" text-anchor="middle">' + esc(lab) + '</text>';
    });
    let ann = '';
    (cfg.annotations || []).forEach((a) => {
      const x = m.l + band * a.i + band / 2;
      const flip = a.flip != null ? a.flip : x + 8 + a.label.length * 6.2 > W - 2;
      const ly = a.row ? m.t - 15 : m.t - 1, top = a.row ? m.t - 18 : m.t - 4;
      ann += '<line x1="' + x + '" x2="' + x + '" y1="' + top + '" y2="' + (m.t + ph) + '" stroke="#9A8CFF" stroke-width="1" stroke-opacity="0.55"/><circle cx="' + x + '" cy="' + top + '" r="3" fill="#9A8CFF"/><text x="' + (flip ? x - 6 : x + 6) + '" y="' + ly + '" text-anchor="' + (flip ? 'end' : 'start') + '" style="fill:#B5A8FF;font-family:var(--font-mono);font-size:10px">' + esc(a.label) + '</text>';
    });
    el.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="' + esc(cfg.aria || 'Stacked column chart') + '">' + g + '<g class="grow-y">' + bars + '</g>' + xl + ticks + ann + '</svg>';
  };

  /* ---------- line chart with crosshair ---------- */
  C.line = (el, cfg) => {
    watch(el, () => C.line(el, cfg));
    const W = Math.max(320, el.clientWidth), H = cfg.height || 200;
    const m = { l: 44, r: cfg.endLabels ? 64 : 12, t: 16, b: 24 };
    const pw = W - m.l - m.r, ph = H - m.t - m.b, n = cfg.labels.length;
    let ymaxRaw = 0; cfg.series.forEach((s) => s.values.forEach((v) => { if (v != null) ymaxRaw = Math.max(ymaxRaw, v); })); (cfg.refs || []).forEach((r) => { ymaxRaw = Math.max(ymaxRaw, r.y); });
    const ymax = cfg.yMax || niceMax(ymaxRaw * 1.08);
    const x = (i) => m.l + (n === 1 ? 0 : i * pw / (n - 1));
    const y = (v) => m.t + ph - ph * v / ymax;
    const fmtY = cfg.fmtY || ((v) => A.u.compact(v));
    let g = '<g class="grid">';
    [0, 0.25, 0.5, 0.75, 1].forEach((f) => { g += '<line x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + y(ymax * f) + '" y2="' + y(ymax * f) + '"/>'; });
    g += '</g>';
    let ticks = '';
    [0, 0.5, 1].forEach((f) => { ticks += '<text x="' + (m.l - 8) + '" y="' + (y(ymax * f) + 3.5) + '" text-anchor="end">' + esc(fmtY(ymax * f)) + '</text>'; });
    cfg.labels.forEach((lab, i) => { if (cfg.xEvery && i % cfg.xEvery !== 0) return; ticks += '<text x="' + x(i) + '" y="' + (H - 6) + '" text-anchor="' + (i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle') + '">' + esc(lab) + '</text>'; });
    let refs = '';
    (cfg.refs || []).forEach((r) => { refs += '<line x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + y(r.y) + '" y2="' + y(r.y) + '" stroke="' + (r.color || '#7A808C') + '" stroke-width="1"/><text x="' + (m.l + 6) + '" y="' + (y(r.y) - 6) + '" text-anchor="start" style="fill:' + (r.textColor || 'var(--text-2)') + ';font-size:10.5px">' + esc(r.label) + '</text>'; });
    let paths = '';
    cfg.series.forEach((s, si) => {
      const pts = []; s.values.forEach((v, i) => { if (v != null) pts.push([x(i), y(v)]); });
      if (!pts.length) return;
      const d = 'M' + pts.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join('L');
      let len = 0; for (let k = 1; k < pts.length; k++) len += Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]);
      if (s.area) paths += '<path class="fade" d="' + d + 'L' + pts[pts.length - 1][0] + ',' + (m.t + ph) + 'L' + pts[0][0] + ',' + (m.t + ph) + 'Z" fill="' + s.color + '" fill-opacity="0.10"/>';
      paths += '<path class="' + (s.dash ? 'fade' : 'draw') + '" style="--len:' + Math.ceil(len + 2) + '" d="' + d + '" fill="none" stroke="' + s.color + '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"' + (s.dash ? ' stroke-dasharray="4 4"' : '') + '/>';
      const lp = pts[pts.length - 1];
      if (s.endDot) paths += '<circle cx="' + lp[0] + '" cy="' + lp[1] + '" r="4" fill="' + s.color + '" stroke="' + SURFACE + '" stroke-width="2"/>';
      if (cfg.endLabels && s.endLabel !== false) paths += '<text x="' + (lp[0] + 8) + '" y="' + (lp[1] + 3.5 + (s.labelDy || 0)) + '" style="fill:var(--text-2);font-size:11px;font-weight:500">' + esc(s.endLabel || (s.label + ' ' + fmtY(s.values.filter((v) => v != null).slice(-1)[0]))) + '</text>';
    });
    let ann = '';
    (cfg.annotations || []).forEach((a) => {
      const xx = x(a.i);
      const flip = xx + 8 + a.label.length * 6.2 > W - 2;
      ann += '<line x1="' + xx + '" x2="' + xx + '" y1="' + (m.t - 4) + '" y2="' + (m.t + ph) + '" stroke="#9A8CFF" stroke-width="1" stroke-opacity="0.5"/><circle cx="' + xx + '" cy="' + (m.t - 4) + '" r="3" fill="#9A8CFF"/><text x="' + (flip ? xx - 6 : xx + 6) + '" y="' + (m.t - 1) + '" text-anchor="' + (flip ? 'end' : 'start') + '" style="fill:#B5A8FF;font-family:var(--font-mono);font-size:10px">' + esc(a.label) + '</text>';
    });
    const xh = '<g class="xh" style="display:none"><line class="xh-l" y1="' + m.t + '" y2="' + (m.t + ph) + '" stroke="#4B5160" stroke-width="1"/>' + cfg.series.map((s, si) => '<circle class="xh-d" data-si="' + si + '" r="4" fill="' + s.color + '" stroke="' + SURFACE + '" stroke-width="2"/>').join('') + '</g>';
    el.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="' + esc(cfg.aria || 'Line chart') + '">' + g + refs + paths + ticks + ann + xh + '<rect data-xhair="1" x="' + m.l + '" y="' + m.t + '" width="' + pw + '" height="' + ph + '" fill="transparent"/></svg>';
    const svg = el.querySelector('svg'), hit = svg.querySelector('[data-xhair]'), grp = svg.querySelector('.xh');
    hit.addEventListener('mousemove', (ev) => {
      const r = svg.getBoundingClientRect(); const sx = (ev.clientX - r.left) * (W / r.width);
      const i = Math.max(0, Math.min(n - 1, Math.round((sx - m.l) / (pw / (n - 1)))));
      grp.style.display = '';
      grp.querySelector('.xh-l').setAttribute('x1', x(i)); grp.querySelector('.xh-l').setAttribute('x2', x(i));
      A.u.$$('.xh-d', grp).forEach((d) => { const s = cfg.series[+d.dataset.si]; const v = s.values[i]; if (v == null) { d.style.display = 'none'; return; } d.style.display = ''; d.setAttribute('cx', x(i)); d.setAttribute('cy', y(v)); });
      const rows = cfg.series.filter((s) => s.values[i] != null).map((s) => ({ c: s.color, l: s.label, v: (cfg.fmtTip || fmtY)(s.values[i]) }));
      A.tip.show(tipRows(cfg.tipTitle ? cfg.tipTitle(i) : cfg.labels[i], rows), ev.clientX, ev.clientY);
    });
    hit.addEventListener('mouseleave', () => { grp.style.display = 'none'; A.tip.hide(); });
  };

  /* ---------- horizontal bars (HTML, crisp text) ---------- */
  C.hbars = (items, opts) => {
    const o = opts || {}; const mx = Math.max.apply(null, items.map((i) => i.value));
    return '<div class="hbars">' + items.map((it, k) => '<div class="hb-row" data-tip="' + esc(tipRows(it.label, [{ c: it.color, l: it.kindLabel || '', v: (o.fmt || A.u.fmtInt)(it.value) }].concat(it.extra || []))) + '"><div class="hb-l"><span class="mono">' + esc(it.id || '') + '</span><span class="t3">' + esc(it.label) + '</span></div><div class="hb-bar"><div class="hb-fill" style="width:' + (it.value / mx * 100).toFixed(1) + '%;background:' + it.color + ';animation-delay:' + (k * 40) + 'ms"></div></div><div class="hb-v num">' + (o.fmt || A.u.fmtInt)(it.value) + '</div></div>').join('') + '</div>';
  };

  /* ---------- heatmap (sequential: one hue, surface → hue) ---------- */
  C.heatmap = (cfg) => {
    let mx = 0; cfg.rows.forEach((r) => r[1].forEach((v) => { mx = Math.max(mx, v); }));
    const base = '#13161A', hue = cfg.color || '#E5446D';
    const col = (v) => v === 0 ? base : mix(base, hue, 0.12 + 0.88 * Math.sqrt(v / mx));
    let html = '<div class="heat" style="grid-template-columns: 128px repeat(' + cfg.cats.length + ', minmax(0,1fr))"><div></div>' + cfg.cats.map((c) => '<div class="heat-col">' + esc(c) + '</div>').join('');
    cfg.rows.forEach((r, ri) => {
      html += '<div class="heat-row mono">' + esc(r[0]) + '</div>';
      r[1].forEach((v, ci) => { html += '<div class="heat-cell" style="background:' + col(v) + ';animation-delay:' + (ri * 30 + ci * 20) + 'ms" data-tip="' + esc(tipRows(r[0], [{ c: col(v), l: cfg.cats[ci], v: A.u.fmtInt(v) + ' hits' }])) + '"></div>'; });
    });
    html += '</div><div class="heat-legend"><span>0</span><span class="ramp" style="background:linear-gradient(90deg,' + base + ',' + mix(base, hue, 0.4) + ',' + hue + ')"></span><span>' + A.u.compact(mx) + ' hits / 24h</span></div>';
    return html;
  };

  A.charts = C;
})(window.A);
