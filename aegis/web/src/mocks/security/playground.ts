// Client-side simulated pipeline for POST /api/playground (used only on 404/405/501/network or forced mocks).
// Destination-aware: PII redacted for remote/third-party, kept for local (PAN masked + CVV dropped everywhere).
// Owner: dashboard-security.
import type {
  Action,
  Decision,
  DestClass,
  Finding,
  Mutation,
  PlaygroundRequest,
  PlaygroundResponse,
  Redaction,
  Surface,
} from '@/api/types';
import { FALLBACK_CONTROLS, phaseOf } from '@/components/security/lib/catalog';
import { dataClassOf } from '@/components/security/lib/placeholders';
import { MOCK_FEED_SERIAL, MOCK_POLICY_VERSION } from './decisions';
import { between, hashString, idHex, mulberry32, round } from './rng';

interface Hit {
  start: number;
  end: number;
  entity: string;
  detector: string;
}

const KNOWN_PEOPLE = ['Jan Kowalski', 'Anna Nowak', 'Piotr Zieliński', 'Maria Wiśniewska', 'John Smith'];

function luhn(digits: string): boolean {
  let sum = 0;
  let dbl = false;
  for (let i = digits.length - 1; i >= 0; i--) {
    let d = digits.charCodeAt(i) - 48;
    if (dbl) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
    dbl = !dbl;
  }
  return digits.length >= 13 && sum % 10 === 0;
}

function scan(text: string): Hit[] {
  const hits: Hit[] = [];
  const add = (re: RegExp, entity: string, detector: string, group = 0, ok?: (m: RegExpExecArray) => boolean) => {
    const r = new RegExp(re.source, re.flags.includes('g') ? re.flags : `${re.flags}g`);
    let m: RegExpExecArray | null;
    while ((m = r.exec(text)) !== null) {
      if (ok && !ok(m)) continue;
      const v = m[group] ?? m[0];
      const start = m.index + (group ? m[0].indexOf(v) : 0);
      hits.push({ start, end: start + v.length, entity, detector });
    }
  };
  for (const name of KNOWN_PEOPLE) {
    let at = text.indexOf(name);
    while (at >= 0) {
      hits.push({ start: at, end: at + name.length, entity: 'PERSON', detector: 'eu-pii-ner' });
      at = text.indexOf(name, at + name.length);
    }
  }
  add(/\bPL\d{2}(?: ?\d{4}){6}\b/, 'IBAN', 'iban_mod97');
  add(/\b(?:\d{4}[ -]?){3}\d{4}\b/, 'PAN', 'pan_luhn', 0, (m) => luhn(m[0].replace(/\D/g, '')));
  add(/\b\d{11}\b/, 'PESEL', 'pesel_checksum');
  add(/\b(?:exp(?:iry|ires)?\.?:?\s*)((?:0[1-9]|1[0-2])\/\d{2})\b/i, 'CARD_EXPIRY', 'card_expiry', 1);
  add(/\b(?:CVV|CVC|CVV2)[:\s]*(\d{3,4})\b/i, 'CVV', 'cvv_context', 1);
  add(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/, 'EMAIL', 'email_regex');
  add(/\+48[ -]?\d{3}[ -]?\d{3}[ -]?\d{3}\b/, 'PHONE', 'phone_pl');
  add(/\bAKIA[A-Z2-7]{16}\b/, 'AWS_KEY', 'aws_access_key');
  add(/\b(?:sk-ant-|ghp_|xoxb-|sk_live_)[A-Za-z0-9_-]{16,}/, 'GENERIC_SECRET', 'token_prefix');
  hits.sort((a, b) => a.start - b.start || b.end - a.end);
  const out: Hit[] = [];
  let lastEnd = -1;
  for (const h of hits) {
    if (h.start < lastEnd) continue;
    out.push(h);
    lastEnd = h.end;
  }
  return out;
}

const INJ_EN = /ignore (?:all |any )?(?:the )?(?:previous|prior|above) instructions|disregard (?:all )?previous|you are now (?:DAN|in developer mode)|reveal (?:your )?(?:system prompt|hidden instructions)/i;
const INJ_PL = /zignoruj (?:wszystkie )?(?:poprzednie|wcześniejsze) (?:instrukcje|polecenia)|ujawnij (?:swój |twój )?prompt systemowy/i;
const BORDERLINE = /pretend|hypothetical|role-?play|unfiltered|jailbreak/i;
const SCARY = /\bkill\b|\bterminate\b|\bexploit\b|\battack\b/i;

function decision(control_id: string, action: Action, reason: string, latency_ms: number, extra: Partial<Decision> = {}): Decision {
  return {
    action,
    control_id,
    reason,
    score: null,
    threshold: null,
    approval_id: null,
    mode: 'enforce',
    severity: action === 'block' ? 'high' : action === 'allow' ? 'info' : 'medium',
    findings: [],
    mutations: [],
    http_status: null,
    error_type: null,
    degraded: false,
    latency_ms,
    owasp: [],
    ...extra,
  };
}

const RANK: Record<Action, number> = { allow: 0, log: 1, redact: 2, require_approval: 3, block: 4 };

function destClassOf(dest: PlaygroundRequest['destination']): DestClass {
  if (dest === 'local' || dest === 'ollama') return 'local';
  if (dest === 'third_party') return 'third_party';
  return 'remote';
}

export function mockPlayground(req: PlaygroundRequest): PlaygroundResponse {
  const text = req.text ?? '';
  const surface: Surface = req.surface ?? 'prompt.user';
  const dc = destClassOf(req.destination);
  const argsText = req.tool_args ? JSON.stringify(req.tool_args) : '';
  const all = `${text}\n${argsText}`;
  const tool = req.tool_name ?? '';
  const rng = mulberry32(hashString(`${surface}|${dc}|${tool}|${all}`));
  const lat = (a: number, b: number) => round(between(rng, a, b), 2);

  const hits = scan(text);
  const special = new Map<string, Decision>();
  const redactions: Redaction[] = [];
  const counters: Record<string, number> = {};
  let outbound = '';
  let cursor = 0;
  const dlp01Findings: Finding[] = [];
  const dlp07Findings: Finding[] = [];
  const secretFindings: Finding[] = [];

  for (const h of hits) {
    const dclass = dataClassOf(h.entity);
    const isSecret = dclass === 'SECRET';
    if (isSecret) {
      secretFindings.push({ control_id: 'DLP-02', detector: h.detector, category: 'secret', entity: h.entity, data_class: dclass, severity: 'critical', score: 1, segment_index: 0, start: h.start, end: h.end, excerpt: `${text.slice(h.start, h.start + 4)}…` });
      continue;
    }
    const pci = h.entity === 'PAN' || h.entity === 'CVV' || h.entity === 'CARD_EXPIRY';
    if (dc === 'local' && !pci) continue; // destination matrix: PII may stay on host
    if (dc === 'local' && h.entity === 'CARD_EXPIRY') continue;
    let ph: string;
    if (h.entity === 'CVV') ph = '[REDACTED:CVV]';
    else if (h.entity === 'PAN') {
      const digits = text.slice(h.start, h.end).replace(/\D/g, '');
      ph = `${digits.slice(0, 6)}******${digits.slice(-4)}`;
    } else {
      counters[h.entity] = (counters[h.entity] ?? 0) + 1;
      ph = `[${h.entity}_${counters[h.entity]}]`;
    }
    const ctl = h.entity === 'PERSON' ? 'DLP-07' : 'DLP-01';
    outbound += text.slice(cursor, h.start);
    const start = h.start;
    redactions.push({ segment_index: 0, path: 'text', start, end: h.end, entity: h.entity, data_class: dclass, placeholder: ph, control_id: ctl, reversible: !ph.startsWith('[REDACTED') && !ph.includes('*') });
    outbound += ph;
    cursor = h.end;
    const f: Finding = { control_id: ctl, detector: h.detector, category: pci ? 'pci' : 'pii', entity: h.entity, data_class: dclass, severity: pci ? 'high' : 'medium', score: ctl === 'DLP-07' ? 0.96 : 1, segment_index: 0, start, end: h.end, excerpt: '•••', replacement: ph };
    (ctl === 'DLP-07' ? dlp07Findings : dlp01Findings).push(f);
  }
  outbound += text.slice(cursor);

  // markdown image exfil channels
  const img = /!\[[^\]]*\]\((https?:\/\/[^)\s]+)\)/.exec(text);
  const mutations: Mutation[] = [];
  if (img) {
    const url = img[1] ?? '';
    if (/assets\.(?:aegis-corp|acme-capital)\.example\/img\/proxy/.test(url)) {
      special.set('SIG-01', decision('SIG-01', 'block', 'AEGIS-TI-022 · EchoLeak via allowlisted image proxy', lat(0.2, 0.4), { findings: [{ control_id: 'SIG-01', detector: 'AEGIS-TI-022', category: 'signature', severity: 'high', score: 1, excerpt: url.slice(0, 48), meta: { signature_id: 'AEGIS-TI-022', title: 'EchoLeak exfiltration via an allowlisted image proxy / open redirector', aliases: ['CVE-2025-32711'] } }] }));
    } else {
      const start = text.indexOf(img[0]);
      outbound = outbound.replace(img[0], '[REDACTED:MD_IMAGE]');
      redactions.push({ segment_index: 0, path: 'text', start, end: start + img[0].length, entity: 'MD_IMAGE', data_class: null, placeholder: '[REDACTED:MD_IMAGE]', control_id: 'DLP-06', reversible: false });
      special.set('DLP-06', decision('DLP-06', 'redact', `external markdown image stripped (${url.replace(/^https?:\/\/([^/?#]+).*$/, '$1')})`, lat(0.1, 0.3)));
    }
  }

  if (secretFindings.length) special.set('DLP-02', decision('DLP-02', 'block', `${secretFindings.map((f) => f.entity).join(', ')} detected — nothing left the host`, lat(0.2, 0.4), { score: 5.2, threshold: 4.0, findings: secretFindings, severity: 'critical' }));
  if (dlp01Findings.length) special.set('DLP-01', decision('DLP-01', 'redact', `${dlp01Findings.length} entities tokenized for ${dc} destination${dlp01Findings.some((f) => f.entity === 'CVV') ? ' · CVV dropped (PCI)' : ''}`, lat(0.3, 0.6), { findings: dlp01Findings }));
  else if (hits.length && dc === 'local') special.set('DLP-01', decision('DLP-01', 'allow', 'destination local · PII may stay on host', lat(0.3, 0.5)));
  if (dlp07Findings.length) special.set('DLP-07', decision('DLP-07', 'redact', 'PERSON detected by eu-pii-ner (0.96 ≥ 0.60)', lat(11, 16), { score: 0.96, threshold: 0.6, findings: dlp07Findings }));

  if (INJ_EN.test(all) || INJ_PL.test(all)) {
    special.set('INJ-01', decision('INJ-01', 'block', `instruction override (${INJ_PL.test(all) ? 'PL' : 'EN'}) after normalization`, lat(0.15, 0.35), { score: 0.98, findings: [{ control_id: 'INJ-01', detector: 'override_instructions', category: 'injection', severity: 'high', score: 0.98, excerpt: (INJ_EN.exec(all) ?? INJ_PL.exec(all))?.[0] ?? null }] }));
  }
  const injScore = INJ_EN.test(all) || INJ_PL.test(all) ? 0.97 : BORDERLINE.test(all) ? 0.62 : SCARY.test(all) ? 0.18 : round(between(rng, 0.01, 0.06), 2);
  const command = typeof req.tool_args?.command === 'string' ? req.tool_args.command : tool === 'Bash' ? text : '';
  if (/pip3? install\s+litellm==1\.82\.8/.test(command || all)) {
    special.set('SIG-01', decision('SIG-01', 'block', 'AEGIS-TI-017 · compromised AI package litellm==1.82.8', lat(0.15, 0.3), { findings: [{ control_id: 'SIG-01', detector: 'AEGIS-TI-017', category: 'signature', severity: 'critical', score: 1, excerpt: 'pip install litellm==1.82.8', meta: { signature_id: 'AEGIS-TI-017', title: 'Compromised AI packages and MCP servers (known-bad versions + IOCs)', aliases: ['CVE-2025-8217'] } }] }));
    special.set('SIG-03', decision('SIG-03', 'block', 'pkg:pypi/litellm@1.82.8 is on the known-bad list', lat(0.05, 0.12)));
  }
  if (/(curl|wget)[^|\n]*\|\s*(ba|z)?sh\b/.test(command || all)) special.set('EXE-01', decision('EXE-01', 'block', 'pipe-to-shell: remote script piped into a shell', lat(0.1, 0.2), { severity: 'critical' }));
  if (/(^|\/)\.env\b|~\/\.ssh|~\/\.aws/.test(String(req.tool_args?.file_path ?? command))) special.set('EXE-02', decision('EXE-02', 'block', 'fs_deny matched a protected path', lat(0.05, 0.1)));
  if (surface === 'mcp.list' && /<IMPORTANT>/i.test(all)) {
    special.set('MCP-02', decision('MCP-02', 'redact', 'tool dropped: hidden <IMPORTANT> instructions in description', lat(3, 5), { score: 0.94, threshold: 0.8, mutations: [{ target: 'body', op: 'remove', path: 'result.tools[0]', reason: 'MCP-02 poisoned description' }] }));
  }
  if (tool === 'marketpulse.purchase_subscription' || /subscription/i.test(tool)) {
    const amount = Number(req.tool_args?.amount_usd ?? 50);
    special.set('ACT-01', decision('ACT-01', amount > 5000 ? 'block' : 'require_approval', `$${amount.toFixed(2)} subscription → ${amount <= 20 ? 'self' : amount <= 200 ? 'admin' : 'owner'} approval`, lat(0.1, 0.2), { approval_id: `apr_${idHex(rng, 12)}` }));
  }
  if (tool.endsWith('.query') && /customers|payment_cards/i.test(all)) special.set('ACT-02', decision('ACT-02', 'require_approval', 'db:customers is CONFIDENTIAL · prod → admin approval', lat(0.12, 0.2), { approval_id: `apr_${idHex(rng, 12)}` }));
  if (tool === 'mailer.send_email') special.set('ACT-03', decision('ACT-03', 'require_approval', 'recipient outside internal domains → approval', lat(0.08, 0.15), { approval_id: `apr_${idHex(rng, 12)}` }));
  if (/project kestrel|kestrel/i.test(all)) special.set('CUS-01', decision('CUS-01', 'block', 'deal code name "Kestrel" must not leave the firm', lat(0.3, 0.5), { score: 0.81, threshold: 0.7 }));

  // every applicable control appears (A-03); semantic phase skipped after a deterministic block
  const applicable = FALLBACK_CONTROLS.filter((c) => c.surfaces.includes(surface) && c.mode !== 'monitor' && c.id !== 'MCP-04');
  const det = applicable.filter((c) => phaseOf(c.kind) === 'deterministic');
  const sem = applicable.filter((c) => phaseOf(c.kind) === 'semantic');
  const decisions: Decision[] = [];
  for (const c of det) decisions.push(special.get(c.id) ?? decision(c.id, c.id === 'GOV-01' ? 'log' : 'allow', c.id === 'GOV-01' ? 'authenticated (playground)' : 'no finding', lat(0.02, 0.3), { meta: { no_finding: true }, ...(c.id === 'DLP-02' ? { score: round(between(rng, 2.2, 3.6)), threshold: 4.0 } : {}) }));
  for (const [id, d] of special) if (!applicable.some((c) => c.id === id) && phaseOf(FALLBACK_CONTROLS.find((c) => c.id === id)?.kind) === 'deterministic') decisions.push(d);
  const detBlock = decisions.some((d) => d.action === 'block' && d.mode === 'enforce');
  if (!detBlock) {
    for (const c of sem) {
      const s = special.get(c.id);
      if (s) decisions.push(s);
      else if (c.id === 'INJ-02') decisions.push(decision('INJ-02', injScore >= 0.9 ? 'block' : 'allow', injScore >= 0.9 ? `injection (${injScore.toFixed(2)} ≥ 0.90)` : `${injScore >= 0.5 ? 'borderline' : 'benign'} (${injScore.toFixed(2)} < 0.90)`, lat(5, 8), { score: injScore, threshold: 0.9 }));
      else if (c.id === 'INJ-03') decisions.push(decision('INJ-03', 'allow', 'safe · on-topic', lat(1.8, 3), { score: SCARY.test(all) ? 0.12 : 0.04, threshold: 0.8 }));
      else if (c.id === 'DLP-07') decisions.push(decision('DLP-07', 'allow', 'no NER entities', lat(10, 15), { score: 0.08, threshold: 0.6 }));
      else decisions.push(decision(c.id, 'allow', 'no finding', lat(0.3, 4), { meta: { no_finding: true } }));
    }
  }

  const enforce = decisions.filter((d) => d.mode === 'enforce');
  const primary = enforce.reduce<Decision | null>((a, b) => (!a || RANK[b.action] > RANK[a.action] ? b : a), null);
  const action: Action = primary && RANK[primary.action] > 1 ? primary.action : 'allow';
  let detMs = 0;
  let semMs = 0;
  for (const d of decisions) {
    if (phaseOf(FALLBACK_CONTROLS.find((c) => c.id === d.control_id)?.kind) === 'semantic') semMs = Math.max(semMs, d.latency_ms);
    else detMs += d.latency_ms;
  }
  const total = round(detMs + semMs + 0.4, 2);
  const id = `dec_${idHex(rng, 20)}`;
  const finalOutbound = action === 'block' ? '' : outbound;
  for (const d of decisions) if (d.mode === 'enforce' && (d.action === 'redact' || d.action === 'allow')) mutations.push(...d.mutations);

  let response: PlaygroundResponse['response'] = null;
  if (req.send && (action === 'allow' || action === 'redact')) {
    const raw = `Mock model received: ${finalOutbound}`;
    let local = raw;
    for (const r of redactions) if (r.reversible) local = local.split(r.placeholder).join(text.slice(r.start, r.end));
    response = { raw, local, model: req.model ?? (dc === 'local' ? 'aegis-judge' : 'mock-echo'), provider: dc === 'local' ? 'ollama' : 'mock' };
  }

  return {
    decision_id: id,
    verdict: {
      id,
      request_id: `req_${idHex(rng, 16)}`,
      interaction_id: `int_${idHex(rng, 16)}`,
      action,
      primary: action === 'allow' ? null : primary,
      decisions,
      segments: [{ path: 'text', text: finalOutbound, role: 'user', trusted: true, redactable: true }],
      redactions: action === 'block' ? [] : redactions,
      mutations,
      approval: null,
      policy_version: MOCK_POLICY_VERSION,
      feed_serial: MOCK_FEED_SERIAL,
      latency_ms: total,
      degraded: false,
      dry_run: false,
      ts: new Date().toISOString(),
    },
    original: text,
    outbound: finalOutbound,
    redactions: action === 'block' ? [] : redactions,
    response,
    timings: { total_ms: total, controls: decisions.map((d) => ({ control_id: d.control_id, ms: d.latency_ms })) },
  };
}
