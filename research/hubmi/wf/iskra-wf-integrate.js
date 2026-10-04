export const meta = {
  name: 'iskra-integrate',
  description: 'Iskra (HubMI.pl): build-fix loop by file owner, seed + eval, a11y scan + fixes, local smoke, screenshots',
  whenToUse: 'After both fan-out partitions finish and the lead has stopped next dev (build needs the .next dir).',
  phases: [
    { title: 'Build-fix', detail: 'pnpm build → route errors to the owning WP → parallel fixers (≤3 rounds)' },
    { title: 'Data+Eval', detail: 'X4 seed, E2 eval' },
    { title: 'A11y', detail: 'Q1 scan → parallel fixers per owner' },
    { title: 'Smoke+Shots', detail: 'Q2 local smoke, G5 mockups' },
  ],
}

// args: { repo, research, rules: string[], wps: WP[] }
const fill = (s) => s.split('{repo}').join(args.repo).split('{research}').join(args.research)
const byId = Object.fromEntries(args.wps.map((w) => [w.id, w]))
const RESULT = {
  type: 'object',
  properties: {
    id: { type: 'string' },
    status: { type: 'string', enum: ['done', 'partial', 'blocked'] },
    files: { type: 'array', items: { type: 'string' } },
    verify: { type: 'array', items: { type: 'object', properties: { cmd: { type: 'string' }, pass: { type: 'boolean' }, note: { type: 'string' } }, required: ['cmd', 'pass'] } },
    contract_requests: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['id', 'status', 'files', 'verify'],
}
const BUILD = {
  type: 'object',
  properties: {
    pass: { type: 'boolean' },
    errors: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, message: { type: 'string' } }, required: ['file', 'message'] } },
  },
  required: ['pass', 'errors'],
}
const A11Y = {
  type: 'object',
  properties: {
    issues: { type: 'array', items: { type: 'object', properties: { route: { type: 'string' }, file: { type: 'string' }, rule: { type: 'string' }, impact: { type: 'string' }, detail: { type: 'string' } }, required: ['route', 'rule', 'impact'] } },
  },
  required: ['issues'],
}

// owner lookup: longest owned-path prefix wins; frozen shared files go to the lead ("LEAD")
const owners = args.wps.flatMap((w) => w.owns.filter((p) => !p.includes(' ') && p !== '*').map((p) => ({ p, id: w.id })))
function ownerOf(file) {
  const f = file.replace(args.repo + '/', '').replace(/^\.\//, '')
  let best = null
  for (const o of owners) if (f.startsWith(o.p) && (!best || o.p.length > best.p.length)) best = o
  return best ? best.id : 'LEAD'
}
const rulesText = args.rules.map((r) => '- ' + fill(r)).join('\n')
function fixerPrompt(id, items, kind) {
  const w = byId[id]
  const scope = w ? `You own: ${w.owns.join(', ')}. Original spec for context:\n${fill(w.spec)}` : 'You are the LEAD fixer: you may edit frozen shared files (contracts, schema, ui, layout, configs) minimally to fix these errors. Do not change public signatures unless unavoidable.'
  return `${rulesText}\n- EXCEPTION: next dev is stopped. Do not run next build; the integrator runs it.\n\n# Fix ${kind} for ${id}\n${scope}\n\n## Problems\n${items.map((e) => `- ${e.file || e.route}: ${e.message || e.rule + ' (' + e.impact + ') ' + (e.detail || '')}`).join('\n')}\n\nFix them with minimal changes in your owned files, re-run your unit tests, and return the structured result.`
}

// Build-fix (≤ args.rounds, default 2) runs CONCURRENTLY with seed + eval: those use tsx scripts and do not need next build.
async function buildFix() {
  let build = null
  const rounds = args.rounds || 2
  for (let round = 1; round <= rounds; round++) {
    build = await agent(`In ${args.repo} run \`pnpm build 2>&1 | tail -200\` (allowed for you). Return pass plus a list of {file, message} for every TypeScript/Next build error (repo-relative file paths). Do not fix anything.`, { label: `build round ${round}`, phase: 'Build-fix', schema: BUILD })
    if (!build || build.pass) break
    const groups = {}
    for (const e of build.errors) (groups[ownerOf(e.file)] = groups[ownerOf(e.file)] || []).push(e)
    log(`round ${round}: ${build.errors.length} errors across ${Object.keys(groups).join(', ')}`)
    await parallel(Object.entries(groups).map(([id, items]) => () => agent(fixerPrompt(id, items, 'build errors'), { label: `fix ${id} (r${round})`, phase: 'Build-fix', schema: RESULT })))
  }
  return build
}
const dataEval = (id) => () => agent(`${rulesText}\n- EXCEPTION: next dev is stopped; your scripts run with tsx and need no server.\n\n# ${id} — ${byId[id].title}\nOwned: ${byId[id].owns.join(', ')}\n## Spec\n${fill(byId[id].spec)}\n## Verify\n${fill(byId[id].verify)}`, { label: id, phase: 'Data+Eval', schema: RESULT })

phase('Build-fix')
const [build, seed, evalRes] = await parallel([buildFix, dataEval('X4'), dataEval('E2')])
const seedEval = [seed, evalRes]

phase('A11y')
const scan = await agent(`${rulesText}\n- EXCEPTION: run \`pnpm build && pnpm start\` (port 3000) yourself for this scan, and stop the server at the end.\n\n# Q1 — ${byId.Q1.title}\nOwned: ${byId.Q1.owns.join(', ')}\n## Spec\n${fill(byId.Q1.spec)}\nReturn every serious/critical axe issue with the route, rule, impact and (best guess) the source file that renders it.`, { label: 'Q1 a11y scan', phase: 'A11y', schema: A11Y })
if (scan && scan.issues.length) {
  const groups = {}
  for (const i of scan.issues) (groups[ownerOf(i.file || '')] = groups[ownerOf(i.file || '')] || []).push(i)
  await parallel(Object.entries(groups).map(([id, items]) => () => agent(fixerPrompt(id, items, 'accessibility violations'), { label: `a11y fix ${id}`, phase: 'A11y', schema: RESULT })))
}

phase('Smoke+Shots')
const finalBuild = await agent(`In ${args.repo} run \`pnpm build 2>&1 | tail -60\`. Return pass and the errors.`, { label: 'final build', phase: 'Smoke+Shots', schema: BUILD })
const tail = await parallel(['Q2', 'G5'].map((id) => () => agent(`${rulesText}\n- EXCEPTION: start \`pnpm start\` on port ${id === 'Q2' ? 3002 : 3003} for your run (BASE_URL accordingly) and stop it after.\n\n# ${id} — ${byId[id].title}\nOwned: ${byId[id].owns.join(', ')}\n## Spec\n${fill(byId[id].spec)}\n## Verify\n${fill(byId[id].verify)}`, { label: id, phase: 'Smoke+Shots', schema: RESULT })))
return { build, finalBuild, seedEval: seedEval.filter(Boolean), a11yIssues: scan ? scan.issues.length : null, tail: tail.filter(Boolean) }
