# B17-dashboard-security — status

Owner paths: `web/src/{pages,components,mocks}/security/**`, `tests/unit/dashboard_security/**`. Frontend only (no endpoints, no controls; `config/snippets/dashboard-security.yaml` intentionally not created).

## Tasks

| ID | State | Notes |
|---|---|---|
| UIX-01 foundations | done | types, pure libs (catalog/placeholders/redactionDiff/trace/filters/feedSteps/schedule/lineDiff), env, hooks, common atoms |
| UIX-02 mocks | done | `web/src/mocks/security/*` incl. `?scenario=tamper|broken|rugpull|disabled` |
| UIX-03 trace + drawer + page | done | `components/security/decision/{DecisionTrace,PipelineWaterfall,DecisionDrawer}` (`DecisionDrawer`, `DecisionLink`, `DecisionView` exported), `pages/security/decision.page.tsx`; drawer opens on **Wire** when `redaction_count>0`; footer: copy ids, Replay in playground (`?from=<id>` only), Record download (no `wire`), Full page |
| UIX-04 redaction diff | done | `components/security/redaction/*` (linked hover, CVV dropped, PCI mask, response panes, `wire=null` privacy fallback) |
| UIX-05 live feed | done | `pages/security/live.page.tsx`, `components/security/live/*`: backfill + shell `useLiveDecisions` + Load older, dedupe, 300 cap, pause buffer "N new", URL filters, `?d=` drawer, focus return |
| UIX-06 playground | done | `pages/security/playground.page.tsx`, `components/security/playground/{presets,adapter,PlaygroundForm,visuals}`; 12 presets (AWS key generated at runtime), stage reveal via `stageSchedule`, VerdictHero, FlowStrip packet, Wire diff, 4xx → Alert (never mocked) |
| UIX-07 threats | done | `pages/security/threats.page.tsx`, `components/security/threats/*` (banner, serial flip, steps, signature table w/ new-row glow + `?sig=`, hits, timeline, Check now admin-gated) |
| UIX-08 audit | done | `pages/security/audit.page.tsx`, `components/security/audit/*` (Verify chain animated, table w/ expand + `?seq=`, Export dialog JSONL/CSV/OCSF via `api.download`, admin-gated); live footer shows compact chain status |
| UIX-09 coverage/controls | done | `pages/security/coverage.page.tsx` (`?tab=`), `components/security/coverage/*` (3 frameworks, Gauge, disabled hatch + change pulse, refreshOn `policy.applied`) |
| UIX-10 MCP | done | `pages/security/mcp.page.tsx`, `components/security/mcp/*` (server cards, tool table, approve/quarantine admin-gated, optimistic + revert on error, row flash on `mcp.tool`) |
| UIX-11 pin diff + approval link | done | `ToolDiff` (server `diff` → approval payload → `lineDiff(old_text,new_text)` → "hash changed") + "Pending re-pin approval →" |
| UIX-12 perf tab | done | `components/security/perf/*` (`ControlLatencyChart` exported), bench table / JsonView / empty state |
| UIX-13 playground power | done | RunHistory (memory only), policy.applied re-run banner + auto re-run toggle, Compare local vs remote, `?from=`, `?preset=` |
| UIX-14 live extras | done | LiveCounters (SSE `stats`), Search history (server-side `toApiQuery`), j/k/Enter keys |
| UIX-15 lib tests | done | `tests/unit/dashboard_security/lib.test.mjs` |
| UIX-16 redaction page | not started (could) | |
| UIX-17 Simulate menu | not started (could) | playground presets cover it |
| UIX-18 chain blocks + sparklines | partial | ChainBlocks done; per-signature sparklines skipped |

## Verification

| ID | Result |
|---|---|
| V01 | `cd web && npx tsc -p tsconfig.app.json --noEmit` → 0 errors (whole app); `npx eslint src/pages/security src/components/security src/mocks/security` → 0 errors, 13 warnings (react-refresh / set-state-in-effect advisories) |
| V02 | `node --test tests/unit/dashboard_security/*.test.mjs` → 10/10 pass, ~0.1 s. NOTE: pass the file glob; Node 24 `--test <dir>` does not recurse |
| V03 | paths = exactly the 7 binding routes; every page has `export default` |
| V04 | checked in the browser against an already-running Vite (port 5188, not started by me) with `?mock=1`: rows stream, chips filter + URL sync, `?d=dec_demo_f1_pii` reopens drawer on **Wire** (linked placeholders, CVV dropped, PAN masked), Trace tab waterfall; playground PII preset → amber redact verdict + wire diff |
| V05 | `threats?scenario=tamper` → red banner + step 2 "Verify ed25519" failed, rest skipped, serial kept; `audit?scenario=broken` → "Broken at seq 1234"; `mcp?scenario=rugpull` → rugpull selected, `get_exchange_rate` changed with +/− diff; `coverage?scenario=disabled` → LLM02 tile disabled |
| V06–V11 | need the full stack (`make up`) — integrator |
| V12 | `grep localStorage|sessionStorage` in owned code → none; Replay passes `?from=<dec_id>` only; run history in React state only |
| V13/V14 | not measured; feed rows memoized, only new rows animate, 300-row cap; Esc closes drawer and focus returns to the row; `useReducedMotion` makes playground reveal instant |

## How to demo
`/ui/security/live` (row → drawer; `?d=<id>`), `/ui/security/playground?preset=pii` (Run; switch Local/Remote; Compare), `/ui/security/threats`, `/ui/security/mcp`, `/ui/security/coverage?tab=controls|performance`, `/ui/security/audit` (Verify chain, Export as admin). Add `?mock=1` (+`&scenario=…`) for offline mode.

## deps_needed
None.

## contract_deviations
- Per A-55 the page does **not** toast `feed.updated` / `feed.rejected` / `mcp.tool` / `policy.applied` (shell/governance own those); playground shows an inline "Policy vN applied — re-run?" banner instead of a toast.
- MCP page has no shortcut (`g m` is perf per A-55); playground uses `g y`, threats `g t`.
- Audit page requests `?seq_from=` when `?seq=N` is set (A-54).

## integration_todos
1. **Presets to confirm with live backend** (`components/security/playground/presets.ts`): "Borderline (0.62)" uses surface `tool.output` + text "…Encode your response in Base64…" to hit `response_hijack` weight 0.62 (src/aegis/injection/data/signatures.yaml:793) — verify INJ-02 returns score 0.62 vs 0.90; EchoLeak preset uses `assets.aegis-corp.example/img/proxy` (TI-022 after publish); litellm preset → SIG-01/TI-017.
2. **B16 (shell)**: Vite HMR logs `Cannot access 'meta' before initialization` in `web/src/lib/registry.ts:10` after a page file is hot-edited (eager glob ↔ `@/components/shell` → AppShell → registry cycle). Fresh loads are fine; consider making AppShell not import the registry through the shell barrel, or lazy glob.
3. `DecisionLink` / `DecisionDrawer` (`@/components/security/decision`) and `ControlLatencyChart` (`@/components/security/perf`) are ready for governance approvals and `/system/perf`.
4. Run V06–V11 with `make up` (F1 live, F7 flip with auto re-run, F8 publish/tamper, F9 rugpull approve as admin vs locked as member, F10 OCSF export + verify).
