export const meta = {
  name: 'iskra-fanout',
  description: 'Iskra (HubMI.pl): run one partition of work packages as a dependency DAG; each WP owns exclusive files',
  whenToUse: 'After the Iskra foundation (F0–F4) is merged and tsc --watch + next dev are running. Launch once per partition (A, B) concurrently.',
  phases: [{ title: 'Fan-out', detail: 'one agent per work package, started as soon as its dependencies finish' }],
}

// args: { repo, research, rules: string[], wps: WP[], partition: 'A' | 'B' | 'DOCS', only?: string[] }
const PARTITIONS = {
  A: ['M1', 'M2', 'M3', 'M4', 'M5', 'E1', 'U1', 'U4', 'U6', 'U2', 'U3', 'U5', 'L1', 'L2', 'L3', 'T1', 'T2', 'A3', 'X1', 'L4', 'X2', 'X3', 'U7', 'U8'],
  B: ['C1', 'C2', 'K1', 'K2', 'K4', 'K3', 'K5', 'W3', 'W1', 'W2', 'W4', 'A1', 'A2', 'A4', 'A5'],
  DOCS: ['D1', 'G1', 'G2', 'G3', 'G4'],
}

const RESULT = {
  type: 'object',
  properties: {
    id: { type: 'string' },
    status: { type: 'string', enum: ['done', 'partial', 'blocked'] },
    files: { type: 'array', items: { type: 'string' } },
    verify: {
      type: 'array',
      items: {
        type: 'object',
        properties: { cmd: { type: 'string' }, pass: { type: 'boolean' }, note: { type: 'string' } },
        required: ['cmd', 'pass'],
      },
    },
    contract_requests: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['id', 'status', 'files', 'verify'],
}

const fill = (s) => s.split('{repo}').join(args.repo).split('{research}').join(args.research)
const byId = Object.fromEntries(args.wps.map((w) => [w.id, w]))
const ids = (args.only && args.only.length ? args.only : PARTITIONS[args.partition]).filter((id) => byId[id])
const inPartition = new Set(ids)

function prompt(w, depResults) {
  const depNotes = depResults
    .filter(Boolean)
    .map((r) => `- ${r.id}: ${r.status}${r.notes ? ' — ' + r.notes.slice(0, 400) : ''}`)
    .join('\n')
  return [
    '# Shared rules',
    ...args.rules.map((r) => '- ' + fill(r)),
    '',
    `# Your work package: ${w.id} — ${w.title}`,
    `Owned paths (create/edit ONLY these): ${w.owns.join(', ')}`,
    `Depends on: ${(w.after || []).join(', ') || 'foundation'}${depNotes ? '\nDependency results:\n' + depNotes : ''}`,
    '',
    '## Spec',
    fill(w.spec),
    '',
    '## Verify (run these; report each with pass/fail)',
    fill(w.verify),
    w.cut ? `\nThis WP is cuttable (CUT ${w.cut}). If you are running long, ship the minimum and mark it partial.` : '',
    `\nTime box: about ${w.est} minutes. Return the structured result.`,
  ].join('\n')
}

const memo = {}
function run(id) {
  if (!memo[id]) {
    memo[id] = (async () => {
      const w = byId[id]
      const deps = (w.after || []).filter((d) => inPartition.has(d))
      const depResults = await Promise.all(deps.map(run))
      const res = await agent(prompt(w, depResults), { label: `${w.id} ${w.title}`, phase: 'Fan-out', schema: RESULT })
      log(`${w.id}: ${res ? res.status : 'no result'}`)
      return res || { id: w.id, status: 'blocked', files: [], verify: [], notes: 'agent returned null' }
    })()
  }
  return memo[id]
}

const results = await parallel(ids.map((id) => () => run(id)))
const summary = results.filter(Boolean)
const notDone = summary.filter((r) => r.status !== 'done').map((r) => `${r.id}:${r.status}`)
const requests = summary.flatMap((r) => (r.contract_requests || []).map((c) => `${r.id}: ${c}`))
log(`partition ${args.partition}: ${summary.length} WPs, not done: ${notDone.join(', ') || 'none'}`)
return { partition: args.partition, results: summary, notDone, contractRequests: requests }
