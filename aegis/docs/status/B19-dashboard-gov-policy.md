# B19-dashboard-gov-policy — status

Budgets + kill switch page, Monaco policy editor, verdict-flip probes (plan 17, half B).

## Tasks
| ID | State | Notes |
|---|---|---|
| UIG-03 Budgets | **done** | `budgets.page.tsx`: dimension/window toggles, KPI tiles (org-day Gauge, month, compute, soft/hard count, kill state), `BudgetTree` (org→team→member/agent, sessions grouped last, twisty, sponsor line, `BudgetUsageBar` used + striped reserved + 80/100 marks, 640 ms width transition, state pill, reset countdown), `RaiseDialog` (limit chips, +25/+50/2×/2.5×, live +N %, live route via `/api/approvals/simulate` + G2 ext → fallback estimate labelled *estimate*, reason, ApplyResult toasts incl. *Open* → `/governance/approvals?id=`). Live: `refreshOn` budget.updated/threshold, policy.applied, killswitch + 5 s polling + mock-store refresh. |
| UIG-10 (kill half) | **done** | `KillSwitchControl` per row + `GlobalKillPanel`; confirm dialog with required reason → `POST /api/killswitch` → ApplyResult. Locked with tooltip when `!can_killswitch`; sponsors may engage on their own agent (rule `killswitch-own-agent`, SF-16); global release = owner only. |
| UIG-04 Policy editor | **done** | `policy.page.tsx` (tabs editor/diff/history via `?tab=`): bundled Monaco (lazy chunk, `?worker`, aegis-dark), PlainYamlEditor fallback (ErrorBoundary + load timeout), debounced validate+diff (latest wins) → markers at line:col, ValidationStatus bar, ChangeList, ApplyPanel (Apply now / Request approval · needs X / locked; ⌘S; real step strip), pending/rebase/rejected/reloaded banners, clean editor reloads + flashes changed lines on external `policy.applied`. |
| UIG-05 Toaster + probes | **done** | `GovernanceToaster` (singleton) + `probe-runner` (dry-run `/v1/guard`, fresh `ses_probe_*`, serialised, cached per version) + `policy-toast` (“Policy vN hot-reloaded in X ms” + changes + **Verdicts flipped** rows, id `policy-v<N>`) + `ProbePanel` (current verdicts, flip pulse). Mounted on budgets + policy pages. |
| UIG-08 History/rollback | **done** | `HistoryList`: source badges, actor, summary; diff vN→active; *Load into editor*; *Roll back* (reason dialog, governed like apply). |
| UIG-09 Quick edits | **done** | `QuickEdits`: profile segmented, featured control enable/monitor toggles, INJ-02 threshold slider, CUS-01 keyword, Break YAML, Revert — draft only, cursor jump + flash. |
| UIG-12 Impact preview | **done** | `ImpactPreview` on Diff tab: full self-test active (cached/version) vs draft → changed `got`, failing cases. |
| UIG-15 Burn-down | **done** | `BudgetHistoryChart` (AreaTimeseries used + dashed linear forecast + limit line, "hits limit at HH:MM"). |
| UIG-14 Schema completions | not started | could; skipped. |

## Verification
| ID | Command | Result |
|---|---|---|
| V01 | `cd web && npm run typecheck` | pass (whole project clean) |
| V01 | `npx eslint` on all B19 files | pass — 0 errors, 18 warnings (react-hooks set-state-in-effect / refs style, fast-refresh) |
| V02 | page discovery node script (plan §5) | `OK 5/5` |
| V03 (B19 part) | ad-hoc node type-stripping check of `lib/yaml-text.ts` + `lib/probe-defs.ts` against the real `config/policy.yaml` (DLP-02 edit confined to its block, comments kept, flow → null, profile/threshold/breakYaml, `diffProbes` exact ids, fake AKIA key) | pass (39 controls, 12 limits parsed). `tests/unit/dashboard_governance/logic_check.mjs` does not exist (not created by B18). |
| V05 | `grep -rnE "cdn\|jsdelivr\|unpkg\|monaco-yaml\|from 'yaml'"` on governance dirs | empty. Monaco referenced only from `components/governance/policy/*` (lazy). Dev-server smoke: worker loaded from same origin (`/ui/node_modules/monaco-editor/esm/vs/editor/editor.worker.js?worker`), `.monaco-editor` rendered with aegis-dark theme. |
| V04 (partial) | short Vite dev server (port 0-style random port, stopped) + browser | budgets page renders with live tree/KPIs/global kill panel in `?mock=1`; RaiseDialog shows "+25% team budget → Requires admin (raise-team-small)"; policy page renders Monaco. Shared browser pane was taken by other agents, so persona-switch walkthrough not completed. |
| V08 / V09 (live F7 / F6) | — | **not run** (needs integrated gateway + policy engine + demo agents) → integration window. |

## Files (all owned)
- `web/src/pages/governance/budgets.page.tsx`, `web/src/pages/governance/policy.page.tsx`
- `web/src/components/governance/budgets/{UsageBar,BudgetTree,RaiseDialog,KillSwitchControl,BudgetHistoryChart}.tsx`
- `web/src/components/governance/policy/{ChangeList,ApplyPanel,ProbePanel,QuickEdits,HistoryList,ImpactPreview}.tsx` (new) + pre-existing `EditorHost, PolicyEditor, PolicyDiffView, PlainYamlEditor, ValidationStatus, monaco-setup, editor-types, line-ops, config-route, policy-api, policy-toast, probe-runner, use-policy-draft`
- `web/src/components/governance/GovernanceToaster.tsx`, `lib/yaml-text.ts`, `lib/probe-defs.ts`
- `web/src/mocks/governance/{budgets,policy,probes}.ts`

## Demo
- `/ui/governance/budgets` (add `?mock=1` offline): as Piotr → *Increase* on Trading → +25 % → "Requires admin (raise-team-small)" → pending toast with *Open*; as Emily approve on Approvals → bar rescales. *Kill* on chaos-agent (admin) → row *Killed · 429*.
- `/ui/governance/policy`: as Marek toggle DLP-02 off in Quick edits → "Request approval · needs owner"; as Katarzyna → *Apply now* → toast "Policy vN hot-reloaded" + "AWS key → remote model: block → allow". *Break YAML* → red squiggle + rejection path.

## deps_needed
none (monaco-editor 0.57 + @monaco-editor/react already in deps; monaco-yaml / yaml not used).

## contract_deviations
- Monaco load fallback timeout is 10 s (plan said 6 s): cold Vite dev loads exceeded 6 s and fell back to the textarea.
- Budget raise routing estimate follows `docs/seed-fixes/approvals.yaml` (SF-09: team ≤ +100 % → admin), not the original CONTRACTS ≤ +50 %.
- G2 handling: simulate result is trusted only when its `rule_id` looks budget-related; otherwise the client estimate is shown (labelled).

## integration_todos
- dashboard-shell (B16): run `npm run build` once to confirm Monaco ESM + `?worker` bundling (`components/governance/policy/monaco-setup.ts` imports `monaco-editor/editor`, `monaco-editor/features/register.all`, `monaco-editor/languages/definitions/yaml/register`, `monaco-editor/editor/editor.worker?worker`). If bundling breaks, the page still works via `PlainYamlEditor`.
- dashboard-shell: optionally mount `<GovernanceToaster/>` once in the app layout (pages mount it too; singleton guard prevents duplicates). Shell toasts for `policy.applied` should use sonner id `policy-v<version>` so our flip toast updates in place.
- core-gateway: `/v1/guard` must accept `dry_run: true` + `destination` object (G4) for probe flips; otherwise the flips line is omitted silently.
- policy-engine: `/api/policy/validate` should accept `selftest:false` (G1) for keystroke validation; `PolicyDiffResponse.rule_id` (G2a) would replace the client estimate.
- approvals-engine: `/api/approvals/simulate` accepting `changes[]`/`scope_type`/`increase_pct` (G2b) makes the RaiseDialog route exact.
- Run UIG-V07/V08/V09 live in the integration window.
