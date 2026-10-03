/* View 3 — Redaction diff (before / on-the-wire / rehydrated) */
(function (A) {
  'use strict';
  const { $, $$, esc } = A.u;
  let zone = 'external';

  const fp = (s) => { let h = 2166136261; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619) >>> 0; } return 'hmac:' + h.toString(16).padStart(8, '0').slice(0, 8); };
  const actFor = (en) => zone === 'external' ? en.act : en.onprem;
  const color = (en) => A.entityTypes[en.t].color;

  const sample = () => A.redactionSamples.find((s) => s.id === (A.state.redactionSample || 'client-reply')) || A.redactionSamples[0];
  const ents = (s) => s.segs.filter((x) => typeof x !== 'string');

  const srcHtml = (s) => { let i = -1; return s.segs.map((x) => { if (typeof x === 'string') return esc(x); i++; return '<span class="ent src" data-ek="' + i + '" style="--ec:' + color(x) + '" data-tip="' + esc(A.charts.tipRows(x.k, [{ c: color(x), l: 'Detector', v: x.det }, { l: 'Confidence', v: x.conf.toFixed(2) }, { l: 'Action (' + zone + ')', v: actFor(x) }])) + '">' + esc(x.v) + '</span>'; }).join(''); };
  const dstToken = (x, i) => {
    const a = actFor(x);
    if (a === 'tokenize') return '<span class="ent dst" data-ek="' + i + '" style="--ec:' + color(x) + '">' + esc(x.ph) + '</span>';
    if (a === 'drop') return '<span class="ent dropped" data-ek="' + i + '" style="--ec:#F2556F">[DROPPED · PCI]</span>';
    if (a === 'mask') return '<span class="ent dst" data-ek="' + i + '" style="--ec:' + color(x) + '">' + esc(x.masked) + '</span>';
    return '<span class="ent kept" data-ek="' + i + '" style="--ec:' + color(x) + '">' + esc(x.v) + '</span>';
  };
  const dstHtml = (s) => { let i = -1; return s.segs.map((x) => { if (typeof x === 'string') return esc(x); i++; return dstToken(x, i); }).join(''); };
  const respHtml = (s, restored) => {
    const list = ents(s);
    return s.response.map((x) => {
      if (typeof x === 'string') return esc(x);
      const i = list.findIndex((e) => e.k === x.ref); const en = list[i]; if (!en) return '';
      const a = actFor(en);
      if (!restored) return dstToken(en, i);
      if (a === 'tokenize') return '<span class="ent restored" data-ek="' + i + '" style="--ec:#3CCB7F">' + esc(en.v) + '</span>';
      if (a === 'mask') return '<span class="ent dst" data-ek="' + i + '" style="--ec:' + color(en) + '">' + esc(en.masked) + '</span>';
      return '<span class="ent kept" data-ek="' + i + '" style="--ec:' + color(en) + '">' + esc(en.v) + '</span>';
    }).join('');
  };

  const draw = () => {
    const s = sample(); const list = ents(s);
    const tok = list.filter((e) => actFor(e) === 'tokenize').length, drop = list.filter((e) => actFor(e) === 'drop').length, kept = list.filter((e) => actFor(e) === 'allow').length, mask = list.filter((e) => actFor(e) === 'mask').length;
    const dest = zone === 'external' ? 'anthropic/claude-sonnet-4-5' : 'ollama/qwen3:4b';
    $('#rd-stats').innerHTML = [[list.length, 'Entities detected'], [tok, 'Tokenized (reversible)'], [drop + mask, 'Dropped / masked'], [kept, 'Kept · zone policy'], [s.meta.length, 'Metadata fields stripped'], ['0.62 ms', 'Redaction latency']].map((x) => '<div><div class="sv">' + x[0] + '</div><div class="sl">' + x[1] + '</div></div>').join('');
    $('#rd-src').innerHTML = srcHtml(s);
    $('#rd-dst').innerHTML = dstHtml(s);
    $('#rd-dst-h').innerHTML = A.icon('send', 13) + '<b>On the wire</b><span>→ <span class="mono">' + dest + '</span></span><span class="grow"></span>' + (zone === 'external' ? '<span class="badge redact"><span class="dot"></span>External zone</span>' : '<span class="badge allow"><span class="dot"></span>On-prem zone</span>');
    $('#rd-ret').innerHTML = respHtml(s, false);
    $('#rd-usr').innerHTML = respHtml(s, true);
    $('#rd-ents').innerHTML = list.map((e, i) => {
      const a = actFor(e);
      const sent = a === 'tokenize' ? '<span class="ent dst" style="--ec:' + color(e) + ';padding:1px 5px">' + esc(e.ph) + '</span>' : a === 'drop' ? '<span class="ent dropped" style="padding:1px 5px">dropped</span>' : a === 'mask' ? '<span class="mono t2">' + esc(e.masked) + '</span>' : '<span class="t3">kept (on-prem)</span>';
      return '<tr data-ek="' + i + '"><td><span class="row" style="gap:8px"><span style="width:8px;height:8px;border-radius:2px;background:' + color(e) + '"></span><span class="mono" style="font-size:12px">' + esc(e.k) + '</span></span></td><td class="mono t2" style="font-size:12px">' + esc(e.v) + '</td><td>' + sent + '</td><td class="t3" style="font-size:12px">' + esc(e.det) + '</td><td class="r mono" style="font-size:12px">' + e.conf.toFixed(2) + '</td><td class="mono t3" style="font-size:11.5px">' + fp(e.v) + '</td></tr>';
    }).join('');
    $('#rd-meta').innerHTML = s.meta.map((m) => '<div class="sys-row" style="grid-template-columns:auto 1fr auto"><span class="tag">' + m[0] + '</span><span class="mono t2 ellipsis" style="font-size:11.5px">' + esc(m[1]) + '</span><span class="mono c-redact" style="font-size:11.5px">' + esc(m[2]) + '</span></div>').join('');
    $('#rd-zone-note').innerHTML = zone === 'external'
      ? A.icon('lock', 14) + '<span>Zone <b class="t1">external</b>: PII-002 <span class="mono">tokenize</span>, card <span class="mono">first6_last4</span>, CVV <span class="mono">drop</span>. Reversible map held in-process for 15 min, never logged.</span>'
      : A.icon('shieldCheck', 14) + '<span>Zone <b class="t1">on_prem</b>: personal data may reach the local model; CVV still dropped (PCI), card masked, secrets always tokenized.</span>';
  };

  A.views.redaction = {
    render(root) {
      const s = sample();
      root.innerHTML =
        '<div class="page-head"><div><h1 class="page-title">Redaction</h1><div class="page-sub">Local data minimization — PII, Polish IDs, card data, secrets and metadata are tokenized <i>before</i> anything leaves for a remote model, and restored only on the way back.</div></div>' +
        '<div class="actions">' + A.h.seg('rd-sample', A.redactionSamples.map((x) => ({ v: x.id, l: x.label })), s.id) + '</div></div>' +
        '<div class="row mb-3" style="gap:10px;flex-wrap:wrap"><span class="t3" style="font-size:12.5px">Destination</span>' + A.h.seg('rd-zone', [{ v: 'external', l: 'anthropic/claude-sonnet-4-5', icon: 'globe' }, { v: 'onprem', l: 'ollama/qwen3:4b', icon: 'cpu' }], zone) +
        '<span class="lock-note" id="rd-zone-note" style="border-style:solid;padding:6px 10px;font-size:12px"></span></div>' +
        '<div class="card mb-3"><div class="stat-strip" id="rd-stats"></div></div>' +
        '<div class="card"><div class="rd-panes" style="position:relative">' +
        '<div class="rd-pane"><div class="rd-pane-h">' + A.icon('lock', 13) + '<b>Local · original</b><span>' + esc(s.agent) + ' · <span class="mono">' + esc(s.surface) + '</span></span><span class="grow"></span><span class="badge neutral">Never leaves host</span></div><div class="rd-text" id="rd-src"></div></div>' +
        '<div class="rd-pane"><div class="rd-pane-h" id="rd-dst-h"></div><div class="rd-text" id="rd-dst"></div></div>' +
        '<span class="rd-arrow">' + A.icon('arrowRight', 15) + '</span></div>' +
        '<div class="card-f"><div class="ent-legend">' + Object.keys(A.entityTypes).filter((k) => k !== 'META').map((k) => '<span class="li"><span class="sw" style="--ec:' + A.entityTypes[k].color + '"></span>' + A.entityTypes[k].label + '</span>').join('') + '<span class="li"><span class="sw" style="--ec:#F2556F;background:var(--block-subtle)"></span>Dropped (PCI)</span></div><span class="grow"></span><span>Hover any span to trace it across panes</span></div></div>' +
        '<div class="card mt-3"><div class="card-h bordered"><div class="card-title">Response</div><div class="card-sub">Placeholders are rehydrated locally, only for the requesting user</div></div><div class="rd-panes" style="position:relative">' +
        '<div class="rd-pane"><div class="rd-pane-h">' + A.icon('arrowDown', 13) + '<b>Model returned</b><span>placeholders only</span></div><div class="rd-text" id="rd-ret"></div></div>' +
        '<div class="rd-pane"><div class="rd-pane-h">' + A.icon('user', 13) + '<b>User sees</b><span>rehydrated · local</span></div><div class="rd-text" id="rd-usr"></div></div>' +
        '<span class="rd-arrow">' + A.icon('arrowRight', 15) + '</span></div></div>' +
        '<div class="grid g-12 mt-3"><div class="card span-8"><div class="card-h bordered"><div class="card-title">Detected entities</div><div class="card-sub">Audit stores keyed HMAC fingerprints — never raw values or plain hashes</div></div><div class="table-scroll"><table class="table"><thead><tr><th>Type</th><th>Original (local)</th><th>Sent as</th><th>Detector</th><th class="r">Conf.</th><th>Fingerprint</th></tr></thead><tbody id="rd-ents"></tbody></table></div></div>' +
        '<div class="card span-4"><div class="card-h bordered"><div class="card-title">Metadata stripped</div><div class="card-sub">Headers & request metadata</div></div><div id="rd-meta"></div></div></div>';
      A.segHandlers['rd-sample'] = (v) => { A.state.redactionSample = v; A.rerender(); };
      A.segHandlers['rd-zone'] = (v) => { zone = v; draw(); };
      draw();
      if (!root._rdHover) root._rdHover = true, root.addEventListener('mouseover', (ev) => { if (A.current !== 'redaction') return; const t = ev.target.closest('[data-ek]'); $$('.ent.hl', root).forEach((x) => x.classList.remove('hl')); $$('#rd-ents tr', root).forEach((x) => x.classList.remove('selected')); if (!t) return; const k = t.dataset.ek; $$('.ent[data-ek="' + k + '"]', root).forEach((x) => x.classList.add('hl')); const tr = $('#rd-ents tr[data-ek="' + k + '"]', root); if (tr) tr.classList.add('selected'); });
    }
  };
})(window.A);
