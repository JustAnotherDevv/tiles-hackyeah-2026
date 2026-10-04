export const meta = {
  name: 'iskra-foundation',
  description: 'Iskra (HubMI.pl): scaffold (F0), then contracts/design system/DB/data in parallel (F1–F4)',
  whenToUse: 'First build step for Iskra, after the human preflight (repo, Vercel, AI Gateway, Neon) is done.',
  phases: [
    { title: 'Scaffold', detail: 'F0: Next.js + all deps + configs' },
    { title: 'Contracts', detail: 'F1 design system, F2 DB, F3 contracts/stubs/routes, F4 data' },
  ],
}

// args: { repo, research, rules: string[], wps: WP[] }
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
const prompt = (w, extra) =>
  [
    '# Shared rules',
    ...args.rules.map((r) => '- ' + fill(r)),
    w.id === 'F0'
      ? '- EXCEPTION for F0: you own the whole repo and MAY run pnpm install/add, next build and tsc. Shared processes are not running yet.'
      : '- EXCEPTION for foundation WPs: shared processes may not be running yet. Instead of check:owned, run `pnpm tsc --noEmit -p . 2>&1 | grep -E "<your paths>"` (only your files matter). For curl checks, start nothing: skip curl and note it.',
    '',
    `# Your work package: ${w.id} — ${w.title}`,
    `Owned paths: ${w.owns.join(', ')}`,
    extra || '',
    '## Spec',
    fill(w.spec),
    '## Verify',
    fill(w.verify),
    `Time box ~${w.est} min. Return the structured result.`,
  ].join('\n')

phase('Scaffold')
const f0 = await agent(prompt(byId.F0), { label: 'F0 scaffold', phase: 'Scaffold', schema: RESULT })
if (!f0 || f0.status === 'blocked') {
  return { stoppedAt: 'F0', f0 }
}

phase('Contracts')
const contractIds = ['F3', 'F1', 'F2', 'F4']
const results = await parallel(
  contractIds.map((id) => () =>
    agent(prompt(byId[id], `F0 notes: ${(f0.notes || '').slice(0, 600)}`), { label: `${id} ${byId[id].title}`, phase: 'Contracts', schema: RESULT }),
  ),
)
const out = [f0, ...results.filter(Boolean)]
log(out.map((r) => `${r.id}:${r.status}`).join(' · '))
return { results: out, contractRequests: out.flatMap((r) => (r.contract_requests || []).map((c) => `${r.id}: ${c}`)) }
