# B16-dashboard-shell — status

Workstream **dashboard-shell** (plan `docs/plan/15-dashboard-shell.md`, tasks UIS-01…UIS-21).
Two agent sessions: agent 1 (22:56–23:17) landed UIS-01…06 and parts of UIS-07/09; agent 2 (23:3x–00:1x) finished the rest.

## Tasks

| ID | State | Notes |
|---|---|---|
| UIS-01 foundations (tokens/globals/effects css, lib/*) | done | agent 1 |
| UIS-02 shadcn primitives (24 + toggle + sonner) | done | `sonner.tsx` now also re-exports `toast` |
| UIS-03 API client | done | agent 1; view-as header, A-55 mock-fallback rules, admin token |
| UIS-04 SSE hub + hooks | done | agent 1; `useDecisionBatches`, `invalidateApi`, `getMember` extras |
| UIS-05 shell kit | done | KpiTile fixed: a bump no longer restarts the count-up from 0 |
| UIS-06 chart wrappers | done | agent 1 |
| UIS-07 app frame | done | `AppShell` (collapsible sidebar, auto icon rail ≤1180 px, persisted), `router.tsx` `PageFrame` (role lock → `LockedPage`, per-page `ErrorBoundary`, framer transition, `document.title`), `LockedPage`, `NotFound`, `RouteError`; Sidebar compacts at heights ≤940 px so every nav item fits at 1536×864 |
| UIS-08 shell mocks + forced pump | done | agent 1 |
| UIS-09 global toasts & banners | done | `EventToasts` (+`mcp.tool` per A-55) and new `SystemBanners` (kill switch from `/api/budgets` + SSE, feed-rejected red banner, offline-after-10 s banner); `<GovernanceToaster/>` mounted once in AppShell (A-55) |
| UIS-10 overview rows A–C | done | `components/shell/overview/{useOverviewData,KpiRow,LiveTicker,DecisionsChartCard,LiveStreamCard}` + `pages/overview.page.tsx` |
| UIS-11 build gate | done | `npm run build` passes (see verification) |
| UIS-12 overview rows D–E | done | `SpendBurnCard`, `TeamSpendCard`, `PostureCard`, `InsightCards` (top controls, data protected, destinations, top agents); "k awaiting you" chip |
| UIS-13 `/system/perf` | done | overhead p50/p95/p99, throughput, overhead share of upstream, live p50/p95 line from `stats` ticks, per-control p95, upstream table, local models, `bench.json` headline per A-54 ("not measured" when missing), Server-Timing note |
| UIS-14 `/system/health` | done | status banner, `/healthz` components, versions, SSE status + last event, feed, `/api/semantic/status`, Verify audit chain, demo-data switch |
| UIS-15 command palette + `g <key>` | done | `CommandPalette` (Go to / View as / Actions), hotkeys from `meta.shortcut` |
| UIS-16 motion & video polish | partial | staggered tile/row entrance, count-up, bump flash, ticker ~45 px/s, reduced-motion path; checked at 1536×864 only |
| UIS-17 version annotations | not started | could |
| UIS-18 kill switch control | done | agent 1 (`KillSwitch.tsx`) |
| UIS-19 export report | partial | print button on the overview (`window.print()`, `.no-print`); no audit CSV button |
| UIS-20 admin token | done | input on the Health page; client already sends `Authorization: Bearer` |
| UIS-21 shared Monaco | not needed | governance ships its own `monaco-setup.ts` |

## Verification

| ID | Result |
|---|---|
| UIS-V01 | `npx tsc -b --noEmit` clean (whole web app). `npx eslint <owned paths>` → **0 errors**, 28 warnings (react-hooks `set-state-in-effect` / react-refresh advisories). |
| UIS-V02 | `uv run --frozen pytest -q tests/unit/dashboard_shell` → **57 passed** (public surface, primitives, page metas, no CDN). |
| UIS-V03 | forced mocks `/ui/?mock=1` at 1536×864 (on an already-running dev server): sidebar lists every discovered page by section; 6 KPI tiles; ticker scrolling; stream rows sliding in; "Demo data" pill; approval toasts; no console errors except HMR dep-array notices from live edits. |
| UIS-V04 | not run separately (no `vite preview`, to save RAM). Fallback logic is unchanged from agent 1. |
| UIS-V05 | partly: another agent's gateway on :8787 behind the dev proxy → `/ui/?mock=0` showed the "Live" pill, real decisions in ticker and stream, real `/api/stats`, `/api/budgets` and **`/api/stats/posture` (87, B+)** with no demo badges. Server started by me: none. |
| UIS-V06 | Segmented "Member" → localStorage `aegis.viewAs=u_piotr`, toast "Viewing as Piotr Zieliński · Member", kill switch hidden for members. (Reset afterwards.) Network header not inspected in this session. |
| UIS-V07/V08 | not run end-to-end (needs policy edit / feed tamper on a gateway I don't own). Toast and banner code paths exist; the policy toast uses sonner id `policy-v<N>` so GovernanceToaster updates it in place. |
| UIS-V09 | `npm run build` **passed** (9 m 44 s under load ~20). `dist/index.html` present, 23 woff2 files, `NO_CDN`, `du -sh dist` = 7.2 MB (Monaco ≈ 4 MB from governance). A rebuild after the final polish edits also **passed** (14 s, typecheck clean, NO_CDN). |
| UIS-V10 | `?mock=1&mockRate=20`: ticker DOM capped at 30 items, ~28 fps in the dev build on a machine at load ~20, no horizontal scroll at 1536 px (scrollWidth = innerWidth). 1280/1920 and reduced-motion not captured. |
| UIS-V11 | `/system/perf` and `/system/health` render with mocks (screenshots OK); Verify chain shows "Chain OK · 48,216 records" (mock) with a badge. |

## Files (created or rewritten by agent 2)
- `web/src/App.tsx` (Toaster `visibleToasts=4`), `web/src/router.tsx` (PageFrame)
- `web/src/components/shell/{AppShell,SystemBanners,CommandPalette,LockedPage,NotFound,RouteError}.tsx`; edits in `EventToasts.tsx`, `Topbar.tsx`, `Sidebar.tsx`, `KpiTile.tsx`, `index.ts`
- `web/src/components/shell/overview/{useOverviewData.ts,KpiRow,LiveTicker,DecisionsChartCard,LiveStreamCard,SpendBurnCard,TeamSpendCard,PostureCard,InsightCards}.tsx`
- `web/src/pages/overview.page.tsx`, `web/src/pages/system/{perf,health}.page.tsx`
- `web/src/lib/posture.ts` (rewritten to the A-51 formula), `web/src/components/ui/sonner.tsx` (re-export `toast`)
- `tests/unit/dashboard_shell/test_public_surface.py`

## How to run / demo
- `cd web && npm run build` → the gateway serves `web/dist` at `/ui/`; or `make web` (dev server).
- `/ui/?mock=1` forces demo data and the synthetic event pump (`&mockRate=20` for a burst); `?mock=0` clears it. `?view_as=u_emily` deep-links a viewer.
- ⌘K opens the palette; `g o`, `g m` and `g h` go to the overview, perf and health pages.

## deps_needed
none.

## contract_deviations
- **A-55 toast ownership:** the shell mounts `<GovernanceToaster/>` once, **and also keeps** the plain `policy.applied/rejected`, `approval.created/updated` and `killswitch` toasts. Reason: B19's GovernanceToaster (see its header comment) only toasts when verdicts flip or SSE is down, and it relies on the shell's toast with the same sonner id `policy-v<N>`. Dropping the shell toasts would lose the F7 "Policy vN applied in X ms" toast. There are no duplicates because the ids are shared. If governance takes over all of these, delete the matching `case` blocks in `web/src/components/shell/EventToasts.tsx`.
- **A-51 posture:** the overview uses `GET /api/stats/posture` (no mock factory). When it is missing, `lib/posture.ts` `computePosture` mirrors the A-51 weights and grades; components it cannot know client-side (selftests, governance) are excluded from the denominator.

## integration_todos
- `web/src/components/shell/AppShell.tsx` imports `@/components/governance/GovernanceToaster` (owner B19). It must keep that export name.
- G12 (core-gateway): no gzip or buffering on `/api/events`, plus an SPA fallback for deep links. Not verified against the built `dist` behind the real `ui.py`.
- UIS-V07/V08 still need a live check on the integrated gateway: edit `config/policy.yaml` → toast + VersionPill flash; feed tamper → red banner; `POST /api/killswitch` → killbar.
- The overview "active agents" chip links to `/governance/org` and the MCP toast links to `/security/mcp`. These pages come from B18/B17; if the paths differ, update the links.
