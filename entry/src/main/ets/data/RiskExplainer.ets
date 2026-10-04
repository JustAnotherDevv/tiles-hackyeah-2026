import { ApprovalItem } from '../model/Models';

/** One factor that raised (or explains) the risk of a request. */
export class RiskFactor {
  text: string;
  points: number;

  constructor(text: string, points: number) {
    this.text = text;
    this.points = points;
  }
}

export class RiskSummary {
  /** 'low' | 'medium' | 'high' */
  level: string = 'low';
  score: number = 0;
  headline: string = '';
  factors: RiskFactor[] = [];
  advice: string = '';
}

/** Plain-language meaning of the Aegis gateway controls that can route a request to a human. */
const CONTROL_MEANING: Record<string, string> = {
  'ACT-01': 'Spend guard: agents may not buy or subscribe without a human',
  'ACT-02': 'Data access guard: the table is sensitive for this environment',
  'ACT-03': 'External send guard: data would leave the organisation',
  'ACT-04': 'Code execution / deploy guard: changes real infrastructure',
  'BUD-01': 'Budget control: the change raises what agents may spend',
  'DLP-01': 'Personal data detector: PII is involved',
  'EXE-03': 'Taint-flow breaker: private data + untrusted input + an outbound channel',
  'SIG-03': 'Package-install guard: supply-chain risk',
  'GOV-01': 'Identity control: the caller must be a known, active agent'
};

const SENSITIVE_WORDS: string[] = ['pii', 'pesel', 'health', 'confidential', 'restricted', 'customer', 'clinical',
  'account number', 'iban', 'card'];

function hasWord(text: string, words: string[]): string {
  const t: string = text.toLowerCase();
  for (const w of words) {
    if (t.indexOf(w) >= 0) {
      return w;
    }
  }
  return '';
}

function factValue(it: ApprovalItem, key: string): string {
  for (const kv of it.facts) {
    if (kv.key.toLowerCase() === key) {
      return kv.value;
    }
  }
  return '';
}

/**
 * On-device, rule-based explanation of why the gateway asked a human (the "Intelligent" touch):
 * combines the control that fired, the amount, the approval level, failed policy checks, the
 * environment and data sensitivity into a 0-100 score with readable reasons. Deterministic, no
 * model and no network: nothing about the request leaves the phone to produce it.
 * The agent's own note is never scored (it is untrusted, agent-supplied text).
 */
export function explainRisk(it: ApprovalItem): RiskSummary {
  const s: RiskSummary = new RiskSummary();
  const add = (text: string, points: number): void => {
    s.factors.push(new RiskFactor(text, points));
    s.score += points;
  };

  const meaning: string | undefined = CONTROL_MEANING[it.controlId];
  if (meaning !== undefined) {
    add(it.controlId + ' ' + meaning, 10);
  } else if (it.controlId.length > 0) {
    add('Flagged by gateway control ' + it.controlId, 10);
  }

  if (it.amountUsd >= 200) {
    add('Large amount: ' + '$' + it.amountUsd.toFixed(0), 30);
  } else if (it.amountUsd >= 20) {
    add('Moves money: ' + '$' + it.amountUsd.toFixed(0), 15);
  } else if (it.amountUsd > 0) {
    add('Small amount: ' + '$' + it.amountUsd.toFixed(0), 5);
  }

  if (it.budgetBefore > 0 && it.budgetAfter > it.budgetBefore) {
    const pct: number = Math.round((it.budgetAfter - it.budgetBefore) / it.budgetBefore * 100);
    add('Budget increase of ' + pct.toString() + '%', pct >= 100 ? 25 : 10);
  }

  if (it.twoPerson) {
    add('Policy demands two people (owner + admin)', 20);
  } else if (it.requiredRole === 'owner') {
    add('Only an owner may approve', 15);
  } else if (it.requiredRole === 'admin') {
    add('Needs an admin, not the agent\'s sponsor', 8);
  }

  const env: string = factValue(it, 'env');
  if (env === 'prod' || it.resource.indexOf('prod') >= 0) {
    add('Touches production', 15);
  }

  const sensitiveHit: string = hasWord(it.title + ' ' + it.summary + ' ' + factValue(it, 'sensitivity') + ' ' +
  factValue(it, 'columns'), SENSITIVE_WORDS);
  if (sensitiveHit.length > 0) {
    add('Sensitive data involved (' + sensitiveHit + ')', 15);
  }

  if (it.actionType.startsWith('egress') || it.actionType.startsWith('email')) {
    add('Data would leave the organisation', 10);
  }

  let failed: number = 0;
  for (const c of it.checks) {
    if (!c.ok && failed < 3) {
      add('Check failed: ' + c.name, 10);
      failed++;
    }
  }

  s.score = Math.max(0, Math.min(100, s.score));
  if (s.score >= 60) {
    s.level = 'high';
    s.headline = 'High risk: verify with the sponsor before approving';
  } else if (s.score >= 30) {
    s.level = 'medium';
    s.headline = 'Medium risk: check the facts below';
  } else {
    s.level = 'low';
    s.headline = 'Low risk: routine request';
  }
  s.advice = it.agentNote.length > 0 ?
    'The agent\'s note is untrusted text and does not change this score.' :
    'Score computed on this device from the gateway\'s policy data.';
  return s;
}
