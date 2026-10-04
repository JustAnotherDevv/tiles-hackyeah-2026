/* Aegis Threat Intel - feed editor (vanilla JS, no build, no CDN). */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const SURFACES = ["prompt.user", "model.request", "model.response", "model.admin", "tool.input", "tool.output",
    "mcp.init", "mcp.list", "mcp.call", "mcp.result", "egress.request", "egress.response", "artifact.file", "a2a.message"];
  const S = { rows: [], sel: null, savedYaml: "", state: null, lastSerial: null, lastGwKey: "", busy: false };

  // ------------------------------------------------------------------ helpers
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  async function api(method, path, body, ctype) {
    const opt = { method, headers: {} };
    if (body !== undefined) {
      if (ctype === "text") { opt.body = body; opt.headers["content-type"] = "text/plain"; }
      else { opt.body = JSON.stringify(body); opt.headers["content-type"] = "application/json"; }
    }
    const r = await fetch(path, opt);
    let data = null;
    try { data = await r.json(); } catch (_) { data = null; }
    if (!r.ok && r.status !== 422) {
      const msg = (data && (data.error?.message || data.detail)) || `HTTP ${r.status}`;
      throw new Error(msg);
    }
    return { status: r.status, data };
  }
  function toast(msg, kind = "") {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.innerHTML = msg;
    $("toasts").appendChild(el);
    setTimeout(() => { el.style.transition = "opacity .3s"; el.style.opacity = "0"; }, 4200);
    setTimeout(() => el.remove(), 4600);
  }
  const actionBadge = (a) => `<span class="badge ${esc(a)}">${esc(a === "require_approval" ? "approval" : a)}</span>`;
  const sevBadge = (s) => `<span class="badge sev-${esc(s)}">${esc(s)}</span>`;
  function relTime(iso) {
    if (!iso) return "";
    const d = (new Date(iso).getTime() - Date.now()) / 1000;
    const a = Math.abs(d);
    const txt = a < 90 ? `${Math.round(a)} s` : a < 5400 ? `${Math.round(a / 60)} min` : a < 172800 ? `${Math.round(a / 3600)} h` : `${Math.round(a / 86400)} d`;
    return d >= 0 ? `in ${txt}` : `${txt} ago`;
  }
  function rowState(r) {
    if (!r.valid) return "invalid";
    if (r.status === "withdrawn") return "withdrawn";
    if (!r.enabled) return "draft";
    if (r.status === "experimental") return "monitor";
    return "enforcing";
  }

  // ------------------------------------------------------------------ state + chips
  async function loadState() {
    let st;
    try { st = (await api("GET", "/api/state")).data; } catch (_) { return; }
    const prev = S.state;
    S.state = st;
    renderChips(st, prev);
    renderBanner(st);
    const p = st.pending || {};
    const n = (p.added || []).length + (p.removed || []).length + (p.modified || []).length;
    $("btn-publish").textContent = n ? `Publish +${n}` : "Publish";
    $("btn-publish").title = n ? `Pending: ${[...(p.added || []).map((x) => "+" + x), ...(p.removed || []).map((x) => "−" + x), ...(p.modified || []).map((x) => "~" + x)].join(", ")}` : "Nothing pending (re-publish bumps the serial)";
    if (prev && prev.last_event?.ts !== st.last_event?.ts) loadTimeline();
  }
  function renderChips(st, prev) {
    const gw = st.gateway;
    let sync;
    if (!gw) sync = `<span class="chip sync-off"><span class="dot"></span>Gateway offline</span>`;
    else if (gw.status === "rejected") sync = `<span class="chip sync-bad"><span class="dot"></span>Gateway rejected${st.tampered ? " #" + esc(st.served_serial) : ""}: ${esc(String(gw.last_error || "").split(":")[0])} · enforcing #${esc(gw.serial)}</span>`;
    else if (gw.status === "unreachable") sync = `<span class="chip sync-warn"><span class="dot"></span>Gateway can't reach feed · enforcing #${esc(gw.serial)}</span>`;
    else if (gw.serial === st.serial) sync = `<span class="chip sync-ok"><span class="dot"></span>Gateway enforcing #${esc(gw.serial)} ✓</span>`;
    else sync = `<span class="chip sync-warn"><span class="dot"></span>Gateway on #${esc(gw.serial ?? "–")}, syncing…</span>`;
    const flash = prev && prev.serial !== st.serial ? " flash" : "";
    $("chips").innerHTML =
      `<span class="chip${flash}">serial <b>#${esc(st.serial ?? "–")}</b></span>` +
      `<span class="chip">version <b>${esc(st.version ?? "–")}</b></span>` +
      `<span class="chip">key <b>${esc(st.key_id ?? "none")}</b></span>` +
      `<span class="chip">expires <b>${esc(relTime(st.expires) || "–")}</b></span>` + sync;
    if (prev && prev.serial !== st.serial) loadList(true);
  }
  function renderBanner(st) {
    const gw = st.gateway;
    const b = $("banner");
    if (gw && gw.status === "rejected") {
      const what = st.tampered ? `bundle #${esc(st.served_serial)}` : "the latest bundle";
      b.className = "banner";
      b.innerHTML = `<b>Gateway refused ${what}:</b> ${esc(gw.last_error || "rejected")}. Still enforcing <b>#${esc(gw.serial)}</b> (last-known-good). Publish a signed release to recover.`;
    } else {
      b.className = "banner hidden";
    }
  }

  // ------------------------------------------------------------------ list
  async function loadList(pulse = false) {
    try { S.rows = (await api("GET", "/api/signatures")).data.items || []; } catch (e) { toast(esc(e.message), "bad"); return; }
    renderList(pulse);
    if (!S.sel && S.rows.length) select((S.rows.find((r) => !r.enabled) || S.rows[0]).id);
  }
  function renderList(pulse) {
    const q = $("search").value.trim().toLowerCase();
    const rows = S.rows.filter((r) => !q || [r.id, r.title, ...(r.aliases || []), ...(r.tags || [])].join(" ").toLowerCase().includes(q));
    const enforcing = S.rows.filter((r) => rowState(r) === "enforcing").length;
    const drafts = S.rows.filter((r) => rowState(r) === "draft").length;
    const vec = S.rows.reduce((a, r) => a + (r.vectors?.total || 0), 0);
    $("list-meta").textContent = `${S.rows.length} signatures · ${enforcing} enforcing · ${drafts} draft · ${vec} test vectors`;
    $("sig-list").innerHTML = rows.map((r) => {
      const st = rowState(r);
      const cves = (r.aliases || []).filter((a) => /^CVE-/.test(a)).slice(0, 2).map((a) => `<span class="tag cve">${esc(a)}</span>`).join("");
      const draft = !r.enabled ? `<span class="tag draft">Draft · not published</span>` : "";
      const changed = r.enabled && r.changed && r.published ? `<span class="tag changed">modified</span>` : (r.enabled && !r.published ? `<span class="tag changed">new</span>` : "");
      const wd = r.status === "withdrawn" ? `<span class="badge neutral">withdrawn</span>` : "";
      return `<li class="sig ${S.sel === r.id ? "active" : ""} ${st === "draft" || st === "withdrawn" ? "off" : ""} ${pulse && r.changed ? "pulse" : ""}" data-id="${esc(r.id)}">
        <span class="sdot ${st}" title="${st}"></span><span class="sid">${esc(r.id)}</span>
        <span class="switch ${r.enabled ? "on" : ""}" data-toggle="${esc(r.id)}" role="switch" aria-checked="${r.enabled}" title="${r.enabled ? "Enabled (ships in the next publish)" : "Disabled draft"}"></span>
        <span class="stitle" title="${esc(r.title)}">${esc(r.title)}</span>
        <span class="smeta">${sevBadge(r.severity)}${actionBadge(r.action)}${wd}${cves}${draft}${changed}${r.valid ? "" : `<span class="badge block">invalid</span>`}</span>
      </li>`;
    }).join("");
  }
  $("sig-list").addEventListener("click", async (e) => {
    const t = e.target.closest("[data-toggle]");
    if (t) {
      e.stopPropagation();
      const id = t.dataset.toggle;
      const row = S.rows.find((r) => r.id === id);
      await setEnabled(id, !row.enabled);
      return;
    }
    const li = e.target.closest(".sig");
    if (li) {
      if (dirty() && !confirm("Discard unsaved changes?")) return;
      select(li.dataset.id);
    }
  });
  $("search").addEventListener("input", () => renderList(false));

  // ------------------------------------------------------------------ editor
  const dirty = () => $("yaml").value !== S.savedYaml;
  function gutter() {
    const n = $("yaml").value.split("\n").length;
    let s = "";
    for (let i = 1; i <= n; i++) s += i + "\n";
    $("gutter").textContent = s;
    $("gutter").scrollTop = $("yaml").scrollTop;
  }
  async function select(id) {
    S.sel = id;
    renderList(false);
    let d;
    try { d = (await api("GET", `/api/signatures/${encodeURIComponent(id)}`)).data; } catch (e) { toast(esc(e.message), "bad"); return; }
    S.savedYaml = d.yaml || "";
    $("yaml").value = S.savedYaml;
    gutter();
    renderHead(d.signature, id);
    renderReport(d.report);
  }
  function renderHead(sig, id) {
    const row = S.rows.find((r) => r.id === id) || {};
    $("ed-id").textContent = id;
    $("ed-title").textContent = sig?.title || row.title || "";
    $("ed-eyebrow").textContent = !row.enabled ? "Draft signature · not in the published feed" : row.status === "withdrawn" ? "Withdrawn signature (shipped, not evaluated)" : "Published signature";
    const surf = (sig?.applies_to?.surfaces || row.surfaces || []).map((s) => `<span class="tag">${esc(s)}</span>`).join("");
    const al = (row.aliases || []).map((a) => `<span class="tag ${/^CVE-/.test(a) ? "cve" : ""}">${esc(a)}</span>`).join("");
    $("ed-tags").innerHTML = (row.severity ? sevBadge(row.severity) : "") + (row.action ? actionBadge(row.action) : "") + al + surf;
    $("btn-enable").textContent = row.enabled ? "Disable" : "Enable";
    $("btn-enable").className = row.enabled ? "btn secondary" : "btn primary";
  }
  function renderReport(rep) {
    if (!rep) { $("validation").innerHTML = `<div class="empty">No report.</div>`; return; }
    const checks = (rep.checks || []).map((c) => `<span class="check ${c.ok ? "" : "bad"}">${c.ok ? "✓" : "✕"} ${esc(c.name)} <span>${esc(c.detail || "")}</span></span>`).join("");
    const rows = (rep.tests || []).map((t) => `<tr><td>${t.ok ? '<span class="ok">✓</span>' : '<span class="bad">✕</span>'}</td><td>${esc(t.name)}</td><td class="mono">${esc(t.surface || "")}</td><td>${esc(t.expected)}</td><td>${esc(t.got)}</td><td class="ev" title="${esc(t.evidence || t.error || "")}">${esc(t.evidence || t.error || "")}</td></tr>`).join("");
    const probs = (rep.problems || []).length ? `<ul class="problems">${rep.problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : "";
    const warns = (rep.warnings || []).length ? `<ul class="warnings">${rep.warnings.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : "";
    $("validation").innerHTML = `<div class="checks">${checks}</div>` +
      (rows ? `<table class="vec"><thead><tr><th></th><th>Vector</th><th>Surface</th><th>Expected</th><th>Got</th><th>Evidence</th></tr></thead><tbody>${rows}</tbody></table>` : "") + probs + warns;
  }
  async function validate() {
    try {
      const r = await api("POST", "/api/validate", { yaml: $("yaml").value });
      renderReport(r.data);
      const v = r.data.vectors || {};
      toast(r.data.valid ? `Valid · ${v.passed}/${v.total} vectors pass` : `Invalid: ${esc((r.data.problems || [])[0] || "see report")}`, r.data.valid ? "ok" : "bad");
    } catch (e) { toast(esc(e.message), "bad"); }
  }
  async function save() {
    if (!S.sel) return;
    const m = $("yaml").value.match(/^id:\s*["']?([A-Z0-9-]+)/m);
    const id = m ? m[1] : S.sel;
    try {
      const r = await api("PUT", `/api/signatures/${encodeURIComponent(id)}`, $("yaml").value, "text");
      if (r.status === 422) { toast(esc(r.data?.error?.message || "Not saved"), "bad"); return; }
      S.savedYaml = $("yaml").value;
      S.sel = id;
      renderReport(r.data.report || r.data);
      toast(r.data.valid ? `Saved <b>${esc(id)}</b> · valid` : `Saved <b>${esc(id)}</b> · has problems (publish will refuse)`, r.data.valid ? "ok" : "warn");
      await loadList();
      loadState();
    } catch (e) { toast(esc(e.message), "bad"); }
  }
  async function setEnabled(id, on) {
    try {
      await api("POST", `/api/signatures/${encodeURIComponent(id)}/enabled`, { enabled: on });
      toast(`${esc(id)} ${on ? "enabled - will ship in the next publish" : "disabled"}`, on ? "ok" : "");
      await loadList();
      if (S.sel === id) select(id);
      loadState();
    } catch (e) { toast(esc(e.message), "bad"); }
  }
  async function withdraw() {
    if (!S.sel || !confirm(`Withdraw ${S.sel}? It stays in the feed with status: withdrawn and is no longer evaluated.`)) return;
    try {
      await api("DELETE", `/api/signatures/${encodeURIComponent(S.sel)}`);
      toast(`${esc(S.sel)} withdrawn`, "warn");
      await loadList();
      select(S.sel);
      loadState();
    } catch (e) { toast(esc(e.message), "bad"); }
  }
  function newSig() {
    const nums = S.rows.map((r) => parseInt(r.id.split("-").pop(), 10)).filter((n) => !isNaN(n));
    const id = `AEGIS-TI-${String(Math.max(22, ...nums) + 1).padStart(3, "0")}`;
    S.sel = id;
    S.savedYaml = "";
    $("yaml").value = `id: ${id}
title: Judge-authored signature
description: What this detects and why.
status: stable
severity: high
aliases: []
tags: [LLM01:2026]
enabled: true
applies_to:
  surfaces: [prompt.user, model.request]
match:
  type: regex
  pattern: '(?i)\\bproject\\s+nightingale\\b'
action: block
message: Blocked by a judge-authored threat-intel signature.
tests:
  positive:
    - {name: direct mention, surface: prompt.user, text: "Tell me about Project Nightingale."}
    - {name: in a request, surface: model.request, text: "summarise project  nightingale docs"}
  negative:
    - {name: benign bird, surface: prompt.user, text: "A nightingale sang in Berkeley Square."}
    - {name: other project, surface: model.request, text: "Status of project Falcon?"}
`;
    gutter();
    renderHead({ title: "New signature (unsaved)" }, id);
    $("validation").innerHTML = `<div class="empty">Edit, <b>Validate</b>, then <b>Save</b> (⌘S) and <b>Publish</b>.</div>`;
    $("yaml").focus();
  }

  // ------------------------------------------------------------------ publish / tamper / reset
  async function publish(force = false) {
    if (dirty() && !confirm("You have unsaved edits in the editor. Publish the saved workspace anyway?")) return;
    $("btn-publish").disabled = true;
    try {
      const r = await api("POST", "/api/publish", { force });
      if (r.status === 422) {
        const probs = r.data.problems || {};
        const ids = Object.keys(probs);
        toast(`Publish refused: ${ids.length} invalid signature(s): <b>${esc(ids.join(", "))}</b>`, "bad");
        if (confirm(`Validation failed for ${ids.join(", ")}.\n\nForce-publish anyway? The gateway re-runs every vector and will quarantine failing signatures.`)) return publish(true);
        return;
      }
      const d = r.data;
      const delta = [...(d.added || []).map((x) => "+" + x), ...(d.removed || []).map((x) => "−" + x), ...(d.modified || []).map((x) => "~" + x)];
      toast(`Published <b>serial #${d.serial}</b> · ${d.signatures} signatures · ${d.vectors} vectors ✓ · sha ${esc(d.sha256.slice(0, 8))}${delta.length ? "<br>" + esc(delta.join(" ")) : ""}`, "ok");
      await loadState();
      await loadList(true);
      loadTimeline();
    } catch (e) { toast(esc(e.message), "bad"); }
    finally { $("btn-publish").disabled = false; }
  }
  async function loadTamperMenu() {
    let modes = {};
    try { modes = (await api("GET", "/api/tamper/modes")).data; } catch (_) { /* ignore */ }
    const labels = { unsigned: "Unsigned edit", rollback: "Replay old bundle", wrong_key: "Rogue signing key", swap_bundle: "Swap bundle bytes" };
    $("tamper-menu").innerHTML = Object.entries(modes).map(([k, v]) =>
      `<button data-mode="${esc(k)}" role="menuitem"><div class="m-title"><span class="badge block">${esc(k)}</span>${esc(labels[k] || k)}</div><div class="m-desc">${esc(v)}</div></button>`).join("");
  }
  async function tamper(mode) {
    $("tamper-menu").hidden = true;
    try {
      const r = await api("POST", "/api/tamper", { mode });
      toast(`Tampered: <b>${esc(mode)}</b> · serving #${esc(r.data.serial_attempted)} — watch the gateway reject it`, "warn");
      setTimeout(loadState, 300);
      loadTimeline();
    } catch (e) { toast(esc(e.message), "bad"); }
  }
  async function reset() {
    if (!confirm("Reset the workspace to the repo signatures and publish a new serial?")) return;
    try {
      const r = await api("POST", "/api/reset", { hard: false });
      toast(`Reset · serial #${esc(r.data.serial)}`, "ok");
      S.sel = null;
      await loadList(true);
      loadState();
      loadTimeline();
    } catch (e) { toast(esc(e.message), "bad"); }
  }

  // ------------------------------------------------------------------ try it + timeline
  async function scan() {
    const body = { surface: $("try-surface").value, set: $("try-set").value, text: $("try-text").value };
    try {
      const d = (await api("POST", "/api/scan", body)).data;
      const hits = (d.hits || []).map((h) => `<div class="hit">${actionBadge(h.action)}<span class="mono">${esc(h.signature_id)}</span>${(h.aliases || []).filter((a) => /^CVE-/.test(a)).slice(0, 1).map((a) => `<span class="tag cve">${esc(a)}</span>`).join("")}<span class="muted">${esc(h.title || "")}</span></div>`).join("");
      $("try-result").innerHTML = `<div class="hit">Decision ${actionBadge(d.decision)}<span class="muted">${d.signatures} signatures (${esc(d.set)})</span></div>${hits || '<span class="muted">no signature matched</span>'}`;
    } catch (e) { toast(esc(e.message), "bad"); }
  }
  async function loadTimeline() {
    let items = [];
    try { items = (await api("GET", "/api/events?limit=40")).data.items || []; } catch (_) { return; }
    const fmt = (e) => {
      switch (e.type) {
        case "published": {
          const delta = [...(e.added || []).map((x) => "+" + x), ...(e.removed || []).map((x) => "−" + x), ...(e.modified || []).map((x) => "~" + x)];
          return [`Published #${e.serial}${e.forced ? " (forced)" : ""}`, `${delta.join(" ") || "no changes"} · ${e.vectors} vectors ✓ · sha ${String(e.sha256 || "").slice(0, 8)}`];
        }
        case "tampered": return [`Tampered #${e.serial_attempted} (${e.mode})`, `gateway should keep #${e.kept}`];
        case "reset": return [`Reset${e.hard ? " (hard)" : ""}`, e.serial ? `serial #${e.serial}` : "workspace restored"];
        case "keygen": return ["New signing key", `key ${e.key_id} · seed #${e.serial}`];
        case "saved": return [`Saved ${e.id}`, e.valid ? "valid" : "invalid"];
        case "enabled": case "disabled": case "withdrawn": return [`${e.type[0].toUpperCase() + e.type.slice(1)} ${e.id}`, ""];
        default: return [e.type, ""];
      }
    };
    $("timeline").innerHTML = items.map((e) => {
      const [main, sub] = fmt(e);
      const t = e.ts ? new Date(e.ts).toLocaleTimeString() : "";
      return `<li class="tl-item ${esc(e.type)}"><span class="tdot"></span><div><div class="tl-main">${esc(main)}</div><div class="tl-sub">${esc(t)}${sub ? " · " + esc(sub) : ""}</div></div></li>`;
    }).join("") || `<li class="tl-item"><span class="tdot"></span><div class="tl-sub">No activity yet</div></li>`;
  }

  // ------------------------------------------------------------------ wiring
  $("yaml").addEventListener("input", gutter);
  $("yaml").addEventListener("scroll", () => { $("gutter").scrollTop = $("yaml").scrollTop; });
  $("yaml").addEventListener("keydown", (e) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const ta = e.target, s = ta.selectionStart;
      ta.setRangeText("  ", s, ta.selectionEnd, "end");
      gutter();
    }
  });
  document.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
    if (mod && e.key === "Enter") { e.preventDefault(); validate(); }
    if (e.key === "Escape") $("tamper-menu").hidden = true;
  });
  $("btn-validate").onclick = validate;
  $("btn-save").onclick = save;
  $("btn-enable").onclick = () => { const r = S.rows.find((x) => x.id === S.sel); if (r) setEnabled(r.id, !r.enabled); };
  $("btn-withdraw").onclick = withdraw;
  $("btn-new").onclick = newSig;
  $("btn-publish").onclick = () => publish(false);
  $("btn-reset").onclick = reset;
  $("btn-tamper").onclick = (e) => { e.stopPropagation(); $("tamper-menu").hidden = !$("tamper-menu").hidden; };
  $("tamper-menu").addEventListener("click", (e) => { const b = e.target.closest("[data-mode]"); if (b) tamper(b.dataset.mode); });
  document.addEventListener("click", (e) => { if (!e.target.closest(".menu-wrap")) $("tamper-menu").hidden = true; });
  $("try-surface").innerHTML = SURFACES.map((s) => `<option ${s === "model.response" ? "selected" : ""}>${s}</option>`).join("");
  $("try-scan").onclick = scan;
  $("try-echoleak").onclick = async () => {
    try {
      const r = await fetch("/api/demo/echoleak");
      $("try-text").value = await r.text();
      $("try-surface").value = "model.response";
    } catch (e) { toast(esc(e.message), "bad"); }
  };
  window.addEventListener("beforeunload", (e) => { if (dirty()) { e.preventDefault(); e.returnValue = ""; } });

  loadTamperMenu();
  loadState();
  loadList();
  loadTimeline();
  setInterval(loadState, 1000);
})();
