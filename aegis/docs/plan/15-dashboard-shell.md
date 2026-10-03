# 15 · dashboard-shell — Dashboard shell, design system & management overview

> Workstream **dashboard-shell** · task prefix **UIS** · research refs 04 (§4.6 dashboard views, §1.7 budget actions), 05 (§4.4 judge affordances, §4.5 demo script, §5.5 perf presentation) · staging input `staging/design/prototype/` (+ `staging/design/DESIGN_TOKENS.md` if it exists at implementation time — read it first; it mirrors `tokens.css`).
> Binding sources: `docs/CONTRACTS.md` §1.2 (ownership), §2.2 (page plug-ins, FROZEN `web/src/lib/page.ts`), §3.4 (decision/role colours), §5.4 (dashboard API + **shared shell API names/props**), §5.5 (FROZEN `web/src/api/types.ts`), §6.3 (SSE), §6.5/6.6 (env, ports), §7 (parallel-work rules). Where the prototype disagrees with CONTRACTS, CONTRACTS wins (adaptations listed in §3.2).

---

## 1. Goal & demo value

Ship the frame every other dashboard page lives in, the shared kit they import, and the one page management sees first.

1. **Shell** — Vite + React 19 + TS SPA under `/ui/`, pages auto-discovered from `web/src/pages/**/*.page.tsx` (`meta: PageMeta`), sidebar grouped Overview → Security → Governance → System with live badges, role-locked items shown with a lock (not hidden), topbar with **"view as" role switcher**, policy/feed/audit version pill, live-connection pill, ⌘K command palette, global toasts/banners driven by SSE.
2. **Design system** — dark, premium security-ops look: graphite surfaces, hairline borders, glassy panels, faint grid + glow, Inter / JetBrains Mono (bundled, offline), tabular numbers, framer-motion entry/feed animations, Recharts wrappers, hand-written shadcn/ui primitives. Decision colours (allow emerald · log slate · redact amber · require_approval violet · block rose) and role colours (owner fuchsia · admin sky · member slate · agent teal) are the same on every page.
3. **Typed data layer** — `api` client with **mock fallback when endpoints are missing** (404/405/501/network → mock + "demo data" badge; never for real 4xx policy answers), one shared SSE connection (`/api/events?view_as=`) with reconnect/backoff, hooks (`useApi`, `useEvents`, `useLiveDecisions`, `useViewAs`, `usePendingApprovals`, …) so pages are thin.
4. **Management overview `/`** ("Command Center") — 6 KPI tiles (requests, blocked, redacted, **spend vs budget**, **cost avoided**, **posture score**), a **live animated decision ticker**, a stacked decisions-over-time chart that grows live, a live decision stream, and (should) spend burn-down vs budget, team bullet bars, posture breakdown, top controls / data protected / local-vs-remote / top agents.
5. **System pages** — `/system/perf` (gateway overhead p50/p95/p99, per-control latency, upstream share; flow F10 "Proof") and `/system/health` (components, versions, SSE, audit-chain verify).

**What judges / the 60 s video see:** the establishing shot of a live, moving control room (ticker scrolling, counters ticking, bars growing as the demo agents run); the role switch (member → admin) changing what is approvable; the toast **"Policy v15 applied in 0.21 s · INJ-02 threshold 0.90 → 0.50"** when a judge edits YAML (F7, video shot 6); a red banner when the feed is tampered (F8); the approvals badge incrementing (F4). **Criteria served:** security reporting & auditing (20 %) directly — real-time management metrics, blocked interactions, budget usage; architecture & performance (20 %) via the perf page and hot-reload latency in toasts; practical implementability (page plug-ins, typed contract, offline build).

---

## 2. Design

### 2.1 Files (all inside dashboard-shell ownership, CONTRACTS §1.2)

```
web/public/
  favicon.svg                      shield logomark (indigo gradient), from prototype index.html
web/src/
  main.tsx                         fonts (@fontsource-variable/inter, …/jetbrains-mono) + styles/globals.css; createRoot(<StrictMode><App/></StrictMode>)
  App.tsx                          TooltipProvider + RouterProvider + sonner <Toaster/>
  router.tsx                       createBrowserRouter from lib/registry; basename from import.meta.env.BASE_URL ('/ui/' → '/ui')
  vite-env.d.ts                    vite/client ref + ImportMetaEnv { VITE_AEGIS_API?: string; VITE_AEGIS_MOCK?: string }
  styles/
    tokens.css                     ported design tokens (CSS vars) + shadcn semantic vars (§2.4)
    globals.css                    @import "tailwindcss"; @import "tw-animate-css"; tokens; effects; @custom-variant dark; @theme inline mapping; base layer
    effects.css                    keyframes & utilities: live-dot ping, value bump, row flash per action, skeleton shimmer, ticker edge mask, .bg-grid, .glow, .glass, scrollbars, prefers-reduced-motion overrides
  lib/                             (page.ts is FROZEN, scaffold-owned — never edit)
    utils.ts                       cn()
    format.ts                      fmtUsd fmtNum fmtPct fmtMs fmtTime fmtAgo (+ fmtRatio fmtCompact fmtDateTime fmtDuration)
    colors.ts                      ACTION_COLORS ROLE_COLORS CHART_PALETTE (+ TEAM_PALETTE teamColor SEVERITY_COLORS DEST_COLORS BUDGET_STATE_COLORS STATUS_TONE)
    icons.ts                       resolveIcon(name) → LucideIcon via lucide-react `icons` map, fallback Circle
    registry.ts                    page discovery: import.meta.glob('../pages/**/*.page.tsx', { eager: true }); normalise/validate/sort; isLocked(); navSections(); findPage()
    viewer.ts                      module-level viewer store (localStorage 'aegis.viewAs', boot override ?view_as=), subscribe/get/set, epoch
    mockMode.ts                    isMockForced() (VITE_AEGIS_MOCK=1 | ?mock=1 persisted in sessionStorage, ?mock=0 clears), setMockForced()
    storage.ts                     try/catch-wrapped localStorage/sessionStorage JSON helpers
    motion.ts                      framer presets: fadeUp, stagger(), listItem, pageTransition, springSnappy, useMotionSafe()
    posture.ts                     computePosture(inputs) → {score, grade, tone, factors[]} (§2.7)
    hotkeys.ts                     useHotkeys: ⌘K / Ctrl+K, "g <key>" sequences from meta.shortcut
  api/
    client.ts                      api.get/post/patch/download/url, ApiResult<T>, ApiRequestError, mock fallback (§2.5)
    sse.ts                         SSE_EVENTS list, eventHub singleton (ref-counted EventSource, backoff, stale detection, batching), SseStatus
    hooks.ts                       useApi useEvents useLiveDecisions useViewAs usePendingApprovals (+ useSseStatus useStatsTick useVersions useWhoAmI useMembers usePendingApprovalsDetail)
  components/ui/                   hand-written shadcn (new-york, Tailwind v4) primitives — see §2.3
  components/shell/
    index.ts                       barrel: every name in CONTRACTS §5.4 "@/components/shell" + extras
    PageHeader.tsx Panel.tsx KpiTile.tsx ActionBadge.tsx RoleBadge.tsx DestBadge.tsx IdentityChip.tsx
    StatusDot.tsx MockBadge.tsx EmptyState.tsx JsonView.tsx TimeAgo.tsx RoleGate.tsx
    AnimatedNumber.tsx UsageBar.tsx LiveDot.tsx Kbd.tsx ErrorBoundary.tsx
    AppShell.tsx Sidebar.tsx Topbar.tsx ViewAsSwitcher.tsx VersionPill.tsx ConnectionPill.tsx
    CommandPalette.tsx EventToasts.tsx SystemBanners.tsx LockedPage.tsx NotFound.tsx RouteError.tsx Brand.tsx
    overview/                      overview widgets (page-local helpers can't live in pages/ root — not owned)
      useOverviewData.ts KpiRow.tsx LiveTicker.tsx DecisionsChartCard.tsx LiveStreamCard.tsx
      SpendBurnCard.tsx TeamSpendCard.tsx PostureCard.tsx TopControlsCard.tsx DataProtectedCard.tsx
      DestinationsCard.tsx TopAgentsCard.tsx
  components/charts/
    index.ts                       barrel: AreaTimeseries BarList Gauge Sparkline (+ ChartTooltip ChartLegend chartTheme)
    AreaTimeseries.tsx BarList.tsx Gauge.tsx Sparkline.tsx ChartTooltip.tsx ChartLegend.tsx theme.ts
  mocks/shell/
    rng.ts                         mulberry32 seeded RNG (from prototype data.js)
    org.ts                         demo cast (§4.5 ids), MEMBERS, AGENTS, ORG, whoamiFor(id), mockApprovalsPending()
    decisions.ts                   weighted templates (prototype → contract vocabulary), makeMockDecision(), mockDecisionsPage()
    stats.ts                       mockStats(window) (seeded diurnal curves), mockStatsTick()
    budgets.ts                     mockBudgets(), mockBudgetHistory(scope)
    perf.ts health.ts posture.ts   mockPerf(), mockHealth(), mockControls/Coverage/FeedStatus/AuditVerify (minimal, only for shell use)
    pump.ts                        synthetic SSE pump — ONLY when mocks are forced (contract §5.4); ?mockRate=<ev/s> for burst tests
  pages/
    overview.page.tsx              meta {path:'/', title:'Command Center', icon:'Gauge', section:'Overview', order:10, shortcut:'g o'}
    system/perf.page.tsx           meta {path:'/system/perf', title:'Performance', icon:'Timer', section:'System', order:10, shortcut:'g m'}
    system/health.page.tsx         meta {path:'/system/health', title:'System health', icon:'HeartPulse', section:'System', order:20, shortcut:'g h'}
    system/*.tsx                   page-local helpers for the two system pages (no .page.tsx suffix)
```

No Python, no backend routes, no `config/snippets/dashboard-shell.yaml` (frontend only: **no policy entries**). Static build output `web/dist/` is generated (gitignored) and served by core-gateway `ui.py` at `/ui/`.

### 2.2 Runtime architecture & data flow

```
            ┌───────── lib/registry (eager glob of pages/**/*.page.tsx) ─────────┐
main.tsx → App → Router(basename /ui) → AppShell ─ Sidebar (nav from registry, badges, locks, health footer)
                                          ├─ Topbar (crumbs · ⌘K · ConnectionPill · VersionPill · ViewAsSwitcher)
                                          ├─ SystemBanners (feed rejected · kill switch · offline)
                                          ├─ EventToasts (global SSE → sonner)
                                          ├─ CommandPalette
                                          └─ <ErrorBoundary key=path><motion page transition><Outlet/></…>
data:  lib/viewer ──viewer id──► api/client (X-Aegis-View-As header) ──► fetch(VITE_AEGIS_API + path)
                         └──────► api/sse eventHub (EventSource /api/events?view_as=…&replay=100)
       hooks: useApi (SWR cache keyed viewer+path, dedupe, refreshMs, refreshOn SSE) · useLiveDecisions (shared ring buffer)
       forced mocks (?mock=1 / VITE_AEGIS_MOCK=1): client returns mocks; eventHub attaches mocks/shell/pump instead of EventSource
```

- **Page discovery** (`lib/registry.ts`): eager glob per CONTRACTS §2.2 (path is `'../pages/**/*.page.tsx'` because the module lives in `lib/`). Each module must have a default component and `meta`; invalid modules are skipped with a `console.warn` (never crash the shell). Defaults: `order 100`, `minRole 'member'`, `nav true`, `badge null`. Sort: section order (Overview, Security, Governance, System) → `order` → `title`. Duplicate `path` → warn, first wins. `isLocked(meta, role) = VIEW_ROLE_RANK[role] < VIEW_ROLE_RANK[meta.minRole ?? 'member']`. Locked items stay in the sidebar with a lock icon + tooltip "Requires admin — switch View as"; navigating to a locked route renders `LockedPage` (with a one-click "View as <eligible member>" button) instead of the page.
- **Routing** (`router.tsx`): `createBrowserRouter([{ element: <AppShell/>, errorElement: <RouteError/>, children: [...pages.map(p => ({ path: p.meta.path, element: <PageFrame page={p}/> })), { path: '*', element: <NotFound/> }] }], { basename })`. `PageFrame` = role check + `ErrorBoundary` (one broken sibling page never kills the shell) + framer page transition (fade/translate 6 px, 220 ms) + `document.title = "<title> · Aegis"`. Breadcrumb = "Acme Capital / <section> / <title>".
- **Viewer ("view as")** (`lib/viewer.ts` + `useViewAs`): no React provider needed — a module store read through `useSyncExternalStore`, so `api/client` and `eventHub` can read it outside React. Boot order: `?view_as=` (then removed via `history.replaceState`) → `localStorage['aegis.viewAs']` → `GET /api/whoami` default (`AEGIS_DEFAULT_VIEWER`, u_katarzyna). Changing the viewer: bump epoch → every `useApi` refetches (cache key includes viewer), eventHub reconnects with the new `view_as`, toast "Viewing as Emily Carter · Admin". Members list from `GET /api/members` (fallback `mocks/shell/org.ts`). `role` = member.role (`ViewRole`).
- **Live decisions** (`useLiveDecisions`): module-level ring buffer (max 500, newest first, dedupe by `id`), backfilled once from `GET /api/decisions?limit=50` (mock fallback) and fed by SSE `decision`. SSE messages are **batched and flushed every 200 ms** (rAF-aligned) so runaway-agent bursts (F6) don't thrash React. `connected` = hub status is `live` (or `mock`).
- **KPI live overlay** (overview): base numbers from `GET /api/stats?window=` (refresh 15 s and on `policy.applied`); decisions newer than `stats.generated_at` are added client-side per action so tiles tick instantly; `stats` SSE ticks (2 s) update spend today, pending approvals, p50/p95; the latest timeseries bucket is incremented live so the last bar grows.

### 2.3 Primitives (`components/ui/*`, binding list from CONTRACTS §5.4)

`button card badge table tabs dialog sheet dropdown-menu select input textarea label switch slider tooltip popover command separator scroll-area skeleton avatar progress alert toggle toggle-group sonner` — written by hand in shadcn new-york / Tailwind v4 style (`data-slot` attrs, `cva` variants, `cn`), using only `@radix-ui/*` packages from the manifest, `cmdk` (command) and `sonner`. **No `npx shadcn add`** (it edits manifests / needs network). Extra variants: `Button` `variant: default|secondary|ghost|outline|destructive|success|link`, `size: sm|default|lg|icon`; `Badge` `variant: default|secondary|outline|destructive` + `tone` matching ACTION/ROLE colours. `sonner.tsx` exports the themed `<Toaster/>` and re-exports `toast`.

### 2.4 Design tokens (port of `staging/design/prototype/assets/tokens.css`, adapted to CONTRACTS)

- **Kept from prototype:** graphite surfaces `--bg #07080A`, `--bg-sidebar #0A0B0E`, `--surface-1..4 #0E1013 #13161A #191C21 #20242A`; borders `#15181C / #1E2228 / #2A2F37`; text `#ECEEF1 / #A2A8B3 / #7A808C / #4B5160`; type scale 10.5–44 px; 4 px spacing; radii 4/6/8/12/16; shadows (hairline + inset highlight + soft drop); motion durations 80/140/220/360/640 ms and easings (expo-out default, spring for toasts/badges); layout `--sidebar-w 236px`, `--topbar-h 52px`, `--content-max 1680px`; reduced-motion overrides.
- **Changed (contract wins):** fonts Geist (Google Fonts CDN) → **Inter Variable + JetBrains Mono Variable** via `@fontsource-variable/*` (offline); decision colours re-mapped per §3.4 (prototype had redact = blue, approval = amber); brand Iris `#6D5DFC` → **indigo** (`--primary #6366F1`, hover `#818CF8`, accent text `#A5B4FC`, focus ring indigo) so violet stays unambiguous for `require_approval`; roles per §3.4 (prototype owner = gold, admin = iris); prototype "no glows" → contract "glassy panels, subtle grid/glow" (very low-opacity indigo radial glow behind the header, 24 px grid at ~3 % opacity masked radially, `.glass` = surface-1 at 80 % + `backdrop-blur-md` + inset highlight).
- **Decision colours** (text/badge on dark · chart mark):
  | action | label | icon (lucide) | text/badge `fg` | chart mark | subtle bg / border |
  |---|---|---|---|---|---|
  | allow | Allow | ShieldCheck | `#34D399` emerald-400 | `#059669` emerald-600 | 10 % / 28 % of emerald-500 |
  | log | Log | ScrollText | `#94A3B8` slate-400 | `#64748B` slate-500 | 12 % / 28 % |
  | redact | Redact | EyeOff | `#FBBF24` amber-400 | `#D97706` amber-600 | 10 % / 28 % |
  | require_approval | Approval | UserCheck | `#A78BFA` violet-400 | `#8B5CF6` violet-500 | 10 % / 28 % |
  | block | Block | Ban | `#FB7185` rose-400 | `#E11D48` rose-600 | 10 % / 30 % |
  Chart marks validated with the dataviz palette validator against `#0E1013` (dark): lightness band, chroma floor, contrast PASS; adjacent CVD worst allow↔redact ΔE 7.9 (floor band) ⇒ **secondary encoding is mandatory**: legend always shown, 2 px surface gaps between stacked segments, badges always carry label + icon (never colour alone). `log` is intentionally neutral (low chroma).
- **Roles:** owner `#E879F9` fuchsia-400 · admin `#38BDF8` sky-400 · member `#94A3B8` slate-400 · agent `#2DD4BF` teal-400; approver levels for governance reuse: self = emerald, auto = slate, deny = rose.
- **Categorical (teams/entities) — `TEAM_PALETTE`/`CHART_PALETTE`:** trading `#2563EB` · research `#DB2777` · platform `#0891B2` · 4th `#EA580C` (validated all-pairs for the 3 teams; adjacent for 4). `teamColor(teamId)` maps by fixed team order; **`Team.color` from the seed (amber/emerald/blue) is ignored in charts** because it collides with decision semantics (Contract gap G6).
- **Status tones:** good emerald, warn amber, bad rose, off slate — always with icon + label.
- shadcn semantic vars (`--background --foreground --card --popover --primary --secondary --muted --accent --destructive --border --input --ring --chart-1..5 --sidebar-*`, `--radius: 0.75rem`) are defined in `tokens.css` from the above and exposed via `@theme inline` so `bg-card`, `text-muted-foreground`, `bg-allow/10`, `text-block`, `border-role-admin/30` etc. exist as Tailwind utilities. `<html class="dark">` is the only theme (dark by default, no light mode).

### 2.5 API client semantics (`api/client.ts`)

- Base URL `import.meta.env.VITE_AEGIS_API ?? ''` (same origin; Vite dev proxies `/api`, `/v1`, `/healthz`, `/metrics` → 8787).
- Headers: `Accept: application/json`, `X-Aegis-View-As: <viewer id>` on every `/api/*` call; JSON bodies `Content-Type: application/json`; (could, UIS-20) `Authorization: Bearer <localStorage aegis.adminToken>` on mutating `/api/*` when set (for `AEGIS_ADMIN_TOKEN`).
- **Mock fallback** (only when a `mock` factory is passed): network error (`TypeError`/abort-not-by-us), **404, 405, 501**, or a 2xx response that is not JSON (SPA-fallback HTML from a static server), or a 5xx whose body is **not** an `ApiError` envelope (Vite proxy error page while the gateway is down) → return `{data: mock(), isMock: true}` and `console.info` once per path. **Never** for 400/401/402/403/409/422/429 or any JSON error envelope: those throw `ApiRequestError` (real policy answers must surface). `isMockForced()` → skip the network entirely and return mocks (`isMock: true`); without a mock factory a forced-mock call still hits the network.
- `ApiRequestError extends Error { status; envelope: ApiError | null; type; approvalId; requiredRole; decisionId; controlId }` + `isApiRequestError(e)`.
- `api.download(path, filename?)`: fetch with the same headers → Blob → temporary `<a download>`; filename from `Content-Disposition` else `filename` arg; throws `ApiRequestError` on 403 (pages toast it).
- Datetimes stay ISO strings (types.ts); `lib/format` parses.

### 2.6 SSE hub (`api/sse.ts`)

- One `EventSource(`${base}/api/events?view_as=${id}&replay=100`)` shared by all subscribers (ref-counted; StrictMode-safe). Listeners registered for every name in `SSE_EVENTS` (runtime list of `SseEventName`: decision, approval.created, approval.updated, budget.updated, budget.threshold, policy.applied, policy.rejected, feed.updated, feed.rejected, killswitch, mcp.tool, org.updated, stats, system, heartbeat); `JSON.parse` guarded.
- Status store: `connecting | live | reconnecting | offline | mock`. Native auto-reconnect keeps `Last-Event-ID`; if the source closes (HTTP error) or no message incl. heartbeat for 35 s → manual reconnect with backoff 1 → 2 → 5 → 10 s (cap), status `reconnecting`, after 3 failures `offline` (pill "Offline · retrying"). Viewer change → close + reopen.
- Forced mocks → no EventSource; `mocks/shell/pump.ts` emits decision every 0.9–2.4 s (or `?mockRate=N` per second), `stats` every 2 s, `heartbeat` every 15 s, `approval.created` every ~45 s. **No synthetic events in unforced mode** (contract).
- Delivery: subscribers receive `(name, data)`; `decision` events are batched (200 ms) for the live buffer; other events dispatch immediately.

### 2.7 Overview page (`pages/overview.page.tsx` + `components/shell/overview/*`)

Grid (12 cols ≥ 1280 px; designed for 1920×1080 at 125 % browser zoom ≈ 1536×864 CSS px, rows A–C above the fold):

| Row | Content | Data |
|---|---|---|
| Header | "Command Center" · "Acme Capital · every model, tool, MCP and egress call through one policy decision point" · window toggle 1h/24h/7d (persisted) · chips "N approvals pending" (violet, "k awaiting you" when `can_vote`) and "N active agents" · (could) Export report | `/api/stats`, `/api/approvals?status=pending` |
| A — 6 KPI tiles (stagger-in, count-up) | **Requests** (sparkline of bucket totals, "x rps now") · **Blocked** (rose sparkline, "% of traffic") · **Redacted** (amber sparkline, "N entities tokenized" from `by_entity`) · **Spend today vs budget** (`$12.48 / $150`, `UsageBar` with 80 % soft and 100 % hard markers, "forecast $X by midnight" linear projection, tone by `BudgetState`) · **Cost avoided** (`kpis.cost_avoided_usd`, emerald, "blocks · downgrades · loop kills") · **Posture score** (`Gauge` ring + grade A–D, "k items to review", links to `/system/health`) | `StatsResponse.kpis/timeseries/by_entity`, `StatsTick`, `BudgetsResponse` (org scope, `usd`/`day`), posture inputs |
| B — Live ticker (full width, 40 px) | rAF marquee (port of prototype `startTicker`): ActionBadge · IdentityChip (agent/member) · `control_id` mono (else surface) · masked `preview` (≤ 60 ch) · redaction count · `fmtMs(latency_ms)`; new events appended to a queue, pause on hover, click → `/security/decisions/:id`; reduced motion → static row of latest 6 | `useLiveDecisions` |
| C | **Decisions over time** (8 cols): `AreaTimeseries kind="bar" stacked`, toggle *Interventions* (redact, require_approval, block) / *All traffic* (+allow, log); legend; last bucket grows live; (could) version annotations · **Live decisions** (4 cols): 8 newest, framer `AnimatePresence` slide-in with action-tinted flash, TimeAgo, "View all" → `/security/live` | `stats.timeseries` + live overlay |
| D (should) | **Spend vs budget today** (5): cumulative used line + 10 % area wash, dashed `ReferenceLine` at 80 % ("soft · downgrade", amber) and 100 % ("hard · block", rose), dashed forecast segment to midnight; single USD axis · **Spend by team** (4): `UsageBar` per team (day USD) with state badge (ok / soft "downgrading" / hard "blocking" / killed) + team swatch · **Posture** (3): Gauge + factor checklist with points | `/api/budgets/history?scope=<org scope>&dimension=usd&window=24h`, `/api/budgets`, posture inputs |
| E (should) | **Top controls fired** (`BarList` by_control, bar colour = dominant outcome) · **Data protected** (`BarList` by_entity, "N values never left the machine") · **Local vs remote vs third-party** (3 stat columns + proportional bar, redactions per destination) · **Top agents** (requests, blocks, spend) | `stats.by_control / by_entity / by_destination / top_agents` |

**Posture score** (`lib/posture.ts`, client-side, explainable; not in the API — see gap G1). 100 points:

| Factor | Max | Rule | Source |
|---|---|---|---|
| Controls enforced | 30 | implemented controls: enforce = 1, monitor = 0.5, disabled/off = 0 → share × 30 | `GET /api/controls` |
| Framework coverage | 20 | covered = 1, partial = 0.5, uncovered/disabled = 0 → share × 20 | `GET /api/coverage` |
| Threat feed | 15 | ok 15 · seed 10 · stale/rejected(last-good)/unreachable 8 · disabled 0 | `GET /api/feed/status` |
| Audit chain | 15 | verify ok 15 else 0 | `GET /api/audit/verify` (refresh 60 s) |
| Runtime health | 10 | `/healthz` ok 10, degraded 5, −2 per `down` component (min 0) | `GET /healthz` |
| Semantic guardrails | 10 | `kpis.degraded=false` and semantic not degraded 10, degraded 5 | `stats.kpis.degraded`, `/api/perf` semantic |

Grade ≥ 90 A, ≥ 80 B, ≥ 70 C, else D; tone good ≥ 85, warn ≥ 70, bad < 70. Disabling DLP-02 (F5/F7) visibly drops the score (refetch on `policy.applied`) — a nice live moment. Each factor shows its points in a tooltip so the number is never magic.

### 2.8 Global SSE toasts & banners (`EventToasts`, `SystemBanners`)

The shell owns toasts for **SSE events** (pages must not duplicate them — see §4.3 requests). Dedupe by key (same kind + subject within 2 s), max 4 visible.

| Event | UI |
|---|---|
| `policy.applied` | success toast **"Policy v{version} applied in {latency_ms} ms"**, description = first 2 `changes[].summary` joined " · " (+N more), meta = source · actor; action "View" → `/governance/policy`; VersionPill flashes; posture/control fetches refresh |
| `policy.rejected` | error toast "Policy change rejected — still on v{kept_version}", first error `line:col message` |
| `feed.updated` | success toast "Threat feed #{serial} verified ✓ · +{added} −{removed} ~{modified}"; sidebar feed badge "+N" for 10 s |
| `feed.rejected` | persistent rose banner under the topbar "Feed update rejected: {reason} — enforcement stays on #{kept_serial}" + error toast; feed badge "!" until a later `feed.updated` |
| `approval.created` | violet toast "{title}" · "needs {required_role}" · action "Review" → `/governance/approvals?id={id}`; approvals badge bumps |
| `approval.updated` | small toast when status becomes approved/denied/expired ("Approved by Emily Carter") |
| `budget.threshold` | warn toast at 50/80 % ("team:trading at 82 % of daily USD — downgrading"), error at 100 % |
| `killswitch` | rose killbar "Kill switch engaged · {scope} · by {actor}" (+ "Manage" → `/governance/budgets`); toast on change; also initialised from `BudgetsResponse.kill_switch` |
| `system` | toast by level (info/warning/error) |
| SSE offline | slim amber banner "Live updates offline — retrying" after 10 s offline (not shown when mocks forced) |

### 2.9 Config keys, env, events, endpoints

- **Reads (frontend env/URL/storage):** `VITE_AEGIS_API` (default same origin), `VITE_AEGIS_MOCK` (`1` forces mocks); URL `?mock=1|0`, `?view_as=<member_id>`, `?mockRate=<n>`; localStorage `aegis.viewAs`, `aegis.overview.window`, `aegis.sidebarCollapsed`, `aegis.adminToken` (could); sessionStorage `aegis.mock`.
- **Consumes endpoints:** `GET /healthz`, `/api/whoami`, `/api/members`, `/api/org`, `/api/stats`, `/api/perf`, `/api/decisions`, `/api/budgets`, `/api/budgets/history`, `/api/approvals?status=pending`, `/api/controls`, `/api/coverage`, `/api/feed/status`, `/api/audit/verify`, `/api/semantic/status` (health), `/api/policy/history` (could, annotations), `POST /api/killswitch` (could), `GET /api/audit/export` (could), SSE `GET /api/events`.
- **Emits:** nothing to the backend bus. **Serves:** nothing (static `web/dist`, served by core-gateway `ui.py`).

---

## 3. Reuse map

### 3.1 From `staging/design/prototype/` (read-only; port, don't import)

| Staging file | → Owned path | What moves / how it is adapted |
|---|---|---|
| `assets/tokens.css` | `web/src/styles/tokens.css` | surfaces, borders, text ramp, type scale, spacing, radii, shadows, motion, layout vars verbatim; fonts/decision/brand/role colours replaced per §2.4; add shadcn semantic vars |
| `assets/app.css` | `styles/globals.css`, `styles/effects.css`, Tailwind classes inside components | shell grid, sidebar/nav, topbar/glass, cards, KPI tile anatomy, badges/role badges/tags/chips, live-dot ping, segmented control, ubar (→ `UsageBar` with 80/100 markers), ticker (mask + track), stream-item enter animation, toasts, cmdk, kbd, scrollbars, table row flash (`row-in`, `row-in-block`), skeleton, responsive breakpoints (1360 / 1180 / 760) |
| `assets/core.js` utils | `lib/format.ts`, `mocks/shell/rng.ts`, `components/shell/IdentityChip.tsx` | `fmtInt/fmtUsd/fmtMs/compact/clock/ago/dur/initials/avColor`, mulberry32; avatar colour hashing |
| `assets/core.js` tween / cmdk / toast / live engine | `AnimatedNumber`, `CommandPalette` (cmdk), sonner theme, `mocks/shell/pump.ts` | number tween (expo-out 600 ms) → framer `animate`; cmdk groups/footer; live loop timing (1.1–2.6 s) |
| `assets/data.js` templates & pipeline | `mocks/shell/decisions.ts` | 19 weighted event templates translated to contract vocabulary (table §3.2); members/teams/agents **not** reused (contract cast §4.5 replaces them) |
| `assets/view-overview.js` | `pages/overview.page.tsx` + `components/shell/overview/*` | layout (6 KPI · ticker · 8/4 · 4/4/4 · 7/5), tile contents, ticker rAF loop, stream insertion, interventions/all toggle, posture ring list, system-status rows |
| `assets/charts.js` | `components/charts/*` (Recharts) | mark specs: bars ≤ 24 px with 4 px rounded data-ends, 2 px surface gaps, 2 px lines, 10 % area wash, hairline grid, legend for ≥ 2 series, hover tooltip on every plot, grow/draw animations ≈ 640 ms; sparkline, ring gauge, hbars (→ `BarList`) |
| `assets/app.js` | `Sidebar`, `Topbar`, `VersionPill`, `SystemBanners`, `lib/hotkeys.ts` | nav groups + count badges, side-footer health lines (Gateway p95 · Policy v · Feed # · Audit chain), version pill flash, killbar, `g`-key navigation, ⌘K |
| `index.html` | `web/public/favicon.svg`, `Brand.tsx` | logomark SVG |
| `staging/design/DESIGN_TOKENS.md` (if present at implementation time) | informs `tokens.css` comments | read first; contract colour/font rules still win |

### 3.2 Prototype → contract translation (mock data & labels)

| Prototype | Contract |
|---|---|
| decision `approval` / `downgrade` | `require_approval` / `allow` (downgrade shown only as reason text) |
| surfaces `llm.request`, `llm.response`, `tool.call`, `tool.result`, `tool.list`, `http.egress`, `package.install` | `model.request`, `model.response`, `tool.input` or `mcp.call`, `tool.output` or `mcp.result`, `mcp.list`, `egress.request`, `tool.input` |
| controls `PII-002`, `SEC-001`, `INJ-003`, `LOOP-001`, `BUD-002`, `OUT-005`, `APR-DB-PII`, `APR-SPEND`, `SIG:AICL-TI-0xx`, `KILL-001` | `DLP-01`, `DLP-02`, `INJ-02` (+`INJ-01`), `EXE-04`, `BUD-01`, `DLP-06`, `ACT-02`, `ACT-01`, `SIG-01` (`AEGIS-TI-0xx` in reason), `EXE-04` (403 killed) |
| agents `analyst-bot`, `trade-desk-copilot`, `research-agent`, `claude-code`, … | `trading-copilot@trading`, `research-agent@research`, `claude-code@platform`, `chaos-agent@platform` |
| members `u_anna`, `u_piotr (admin)`, … | §4.5 cast: `u_katarzyna` owner, `u_marek`/`u_emily` admin, `u_piotr`, `u_olivia`, `u_james`, `u_agnieszka`, `u_tomasz` members |
| teams trading/research/risk/eng/client | `trading`, `research`, `platform` |
| previews with `⟨PESEL_1⟩` | `[PESEL_1]`, `[REDACTED:CVV]` — mock previews contain **only masked values** (privacy rule 7.1-8) |
| org budget $8,000/month | `org:acme-capital` $150/day, $3,000/month; teams trading $60, research $15, platform $50 per day |

---

## 4. Interfaces

### 4.1 Consumed (exactly as CONTRACTS)

- FROZEN `web/src/lib/page.ts`: `PageMeta`, `ViewRole`, `NavSection`, `VIEW_ROLE_RANK`.
- FROZEN `web/src/api/types.ts`: `Action`, `ACTION_ORDER`, `Role`, `ROLE_RANK`, `DestClass`, `Destination`, `Identity`, `DecisionSummary`, `Page<T>`, `ApiError`, `StatsResponse`, `StatsKpis`, `StatsBucket`, `StatsTick`, `PerfResponse`, `BudgetsResponse`, `BudgetScopeView`, `BudgetStatus`, `BudgetState`, `BudgetHistoryResponse`, `KillSwitch`, `Member`, `Agent`, `OrgResponse`, `WhoAmI`, `ApprovalsResponse`, `ApprovalRequest`, `ApproverLevel`, `ControlView`, `CoverageResponse`, `FeedStatus`, `AuditVerifyResult`, `HealthResponse`, `PolicyVersionInfo`, `SseEventMap`, `SseEventName`, `Severity`.
- Endpoints & SSE listed in §2.9 with shapes from §5.5; viewer via `X-Aegis-View-As` / `?view_as=` (§5.2, §5.4); SSE wire format §6.3.
- Scaffold-provided: `web/package.json` deps (§7 below), `vite.config.ts` (`base: '/ui/'`, alias `@`, `@tailwindcss/vite`, dev proxy §6.6), `tsconfig*` (`@/*` path), `web/index.html`, `components.json`, `eslint.config.js`.

### 4.2 Provided (binding names from CONTRACTS §5.4; props/signatures defined here and frozen once UIS-01 lands)

```ts
// @/api/client
export interface ApiResult<T> { data: T; isMock: boolean }
export class ApiRequestError extends Error {
  status: number; envelope: ApiError | null; type: string;
  approvalId: string | null; requiredRole: ApproverLevel | null; decisionId: string | null; controlId: string | null;
}
export function isApiRequestError(e: unknown): e is ApiRequestError;
export const api: {
  get<T>(path: string, mock?: () => T): Promise<ApiResult<T>>;
  post<T>(path: string, body?: unknown, mock?: () => T): Promise<ApiResult<T>>;
  patch<T>(path: string, body?: unknown, mock?: () => T): Promise<ApiResult<T>>;
  download(path: string, filename?: string): Promise<void>;
  url(path: string): string;            // absolute URL incl. VITE_AEGIS_API base
};

// @/api/sse
export const SSE_EVENTS: readonly SseEventName[];
export type SseStatus = 'connecting' | 'live' | 'reconnecting' | 'offline' | 'mock';

// @/api/hooks
export interface UseApiResult<T> { data: T | null; error: Error | null; loading: boolean; isMock: boolean; refresh: () => Promise<void> }
export function useApi<T>(path: string | null, opts?: { mock?: () => T; refreshMs?: number; refreshOn?: SseEventName[] }): UseApiResult<T>;
export function useEvents<N extends SseEventName>(names: N[], handler: (name: N, data: SseEventMap[N]) => void): void;
export function useLiveDecisions(limit?: number /* 200 */): { items: DecisionSummary[]; connected: boolean };
export function useViewAs(): { member: Member | null; role: ViewRole; members: Member[]; setViewAs(id: string): void };
export function usePendingApprovals(): number;
// extras (additive)
export function usePendingApprovalsDetail(): { total: number; forMe: number };
export function useSseStatus(): SseStatus;
export function useStatsTick(): StatsTick | null;
export function useVersions(): { policyVersion: number | null; feedSerial: number | null; changedAt: number };
export function useWhoAmI(): UseApiResult<WhoAmI>;
export function useMembers(): Member[];

// @/components/shell  (all named exports from index.ts)
PageHeader({ title, subtitle?, icon?: string | LucideIcon, actions?: ReactNode, badge?: ReactNode })
Panel({ title?, description?, actions?, className?, children, bodyClassName?, flush?: boolean, isMock?: boolean })
KpiTile({ label, value: ReactNode | number, delta?: number /* signed % */, deltaGoodWhen?: 'up'|'down', hint?: ReactNode,
          icon?: string | LucideIcon, tone?: 'neutral'|'good'|'warn'|'bad', sparkline?: number[],
          format?: (n: number) => string, footer?: ReactNode, href?: string, loading?: boolean })
ActionBadge({ action: Action, size?: 'sm'|'md'|'lg', monitor?: boolean /* dashed "would …" */ })
RoleBadge({ role: Role | ApproverLevel })
DestBadge({ dest: DestClass | Destination })                 // Laptop local · Cloud remote · Globe third_party
IdentityChip({ identity: Identity | null, size?: 'sm'|'md', showTeam?: boolean })
StatusDot({ status: 'ok'|'warn'|'error'|'off', pulse?: boolean, label?: string })
MockBadge()                                                   // "demo data" pill + tooltip
EmptyState({ icon?, title, hint?, action?: ReactNode })
JsonView({ value: unknown, collapsed?: boolean | number /* depth */ })
TimeAgo({ ts: ISODate | number })
RoleGate({ min: ViewRole, children, fallback?: ReactNode })
AnimatedNumber({ value: number, format?: (n: number) => string, duration?: number })
UsageBar({ pct: number /* 0–100+ */, state?: BudgetState, markers?: number[] /* [80, 100] */, size?: 'sm'|'md'|'lg' })
LiveDot({ tone?: 'good'|'bad'|'warn', paused?: boolean }) · Kbd({ children }) · ErrorBoundary({ children, fallback? })

// @/components/charts
Sparkline({ data: number[], color?: string, height?: number /* 28 */, area?: boolean })
AreaTimeseries<T>({ data: T[], xKey?: string /* 'ts' */, series: { key: string; label: string; color: string }[],
                    kind?: 'area'|'bar'|'line', stacked?: boolean, height?: number, yFormat?, xFormat?,
                    referenceLines?: { y: number; label?: string; color?: string; dashed?: boolean }[],
                    annotations?: { x: string | number; label: string }[], legend?: boolean })
BarList({ items: { key: string; label: ReactNode; value: number; color?: string; hint?: ReactNode; href?: string }[],
          valueFormat?: (n: number) => string, max?: number, limit?: number, emptyText?: string })
Gauge({ value: number, max: number, label: string, sublabel?: string, tone?: 'auto'|'good'|'warn'|'bad'|'neutral', size?: number, format? })

// @/lib/format   (fmtPct takes 0–100 like every API *_pct field; fmtRatio takes 0–1 for scores/thresholds)
fmtUsd(v, { dp?, compact? }?) fmtNum(v, { dp?, compact? }?) fmtPct(pct, dp = 0) fmtMs(ms) fmtTime(ts, { seconds? }?) fmtAgo(ts)
fmtRatio(r, dp = 0) fmtCompact(n) fmtDateTime(ts) fmtDuration(seconds)     // all return "—" for null/undefined/NaN
// @/lib/utils  cn(...inputs)
// @/lib/colors ACTION_COLORS: Record<Action, {label, icon, fg, chart, bg, border, className}>; ROLE_COLORS; CHART_PALETTE;
//              TEAM_PALETTE; teamColor(teamId); SEVERITY_COLORS; DEST_COLORS; BUDGET_STATE_COLORS; STATUS_TONE
// @/lib/icons  resolveIcon(name: string): LucideIcon
// @/lib/registry  PAGES, isLocked(meta, role), navSections(role)
// @/components/ui/*  the 24 primitives + toggle + sonner (Toaster, toast)
```

Conventions for sibling dashboards (documented in the barrel's JSDoc): wrap every data panel in `Panel isMock={result.isMock}`; use `ActionBadge`/`ACTION_COLORS` for any decision; never toast SSE events the shell already toasts (§2.8); keep mock factories in your own `web/src/mocks/<area>/`; link to decisions via `/security/decisions/:id` and approvals via `/governance/approvals?id=`.

### 4.3 Contract gaps (proposed addenda; no conflicting shapes invented)

| # | Gap | Proposal / handling |
|---|---|---|
| G1 | No posture score in `StatsResponse` | computed client-side in `lib/posture.ts` from existing endpoints (§2.7); no API change needed. Optional later addendum: `StatsKpis.posture_score?`. |
| G2 | §5.4 names `KpiTile`, `AreaTimeseries`, `BarList`, `Sparkline`, `Gauge` but not all props | props defined in §4.2 (additive, optional fields only); treat them as binding once UIS-01 lands. |
| G3 | `types.ts` exports `SseEventName` as a type only | shell exports the runtime list `SSE_EVENTS` from `@/api/sse`. |
| G4 | Ownership of global toasts for SSE events is unspecified (risk of double toasts) | addendum to §5.4: "dashboard-shell renders toasts/banners for `policy.*`, `feed.*`, `approval.created/updated`, `budget.threshold`, `killswitch`, `system`; pages toast only the results of their own HTTP actions." |
| G5 | Prototype colours (redact blue, approval amber, iris brand, Geist CDN fonts) conflict with §3.4/§5.4 | contract wins; brand moved to indigo so violet stays `require_approval`; fonts bundled via `@fontsource-variable/*`. |
| G6 | Seed `Team.color` (amber/emerald/blue) collides with decision hues | charts use `teamColor()` (validated palette); recommend dashboard-governance uses `teamColor()` too. |
| G7 | Mock fallback list is 404/405/501/network only; in dev the Vite proxy returns a non-JSON 500 when the gateway is down, and static preview servers return HTML 200 | contract-compatible extension: also fall back on 2xx-non-JSON and 5xx-without-JSON-envelope; **never** on 4xx or on any JSON error envelope. |
| G8 | `AEGIS_ADMIN_TOKEN` (§6.5) has no frontend mechanism | (could) `localStorage['aegis.adminToken']` → `Authorization: Bearer` on mutating `/api/*`; settable from Health page / ⌘K. |
| G9 | Page files export `meta` + default → `react-refresh/only-export-components` lint error | request to scaffold: `allowExportNames: ['meta']` in `eslint.config.js`. |
| G10 | `web/index.html` content is scaffold-owned | request: `<html lang="en" class="dark">`, `<meta name="color-scheme" content="dark">`, `<meta name="theme-color" content="#07080A">`, `<link rel="icon" href="/favicon.svg">` (Vite rewrites with base), `<div id="root">`, `<script type="module" src="/src/main.tsx">`, `<body class="bg-[#07080A]">` to avoid a white flash. |
| G11 | `components.json` (scaffold) | request: `style: new-york`, `tailwind.css: src/styles/globals.css`, `baseColor: zinc`, `cssVariables: true`, aliases `@/components`, `@/components/ui`, `@/lib`, `@/lib/utils`, `iconLibrary: lucide`. |
| G12 | SSE through proxies | request to core-gateway: no GZip/buffering on `/api/events` (`Cache-Control: no-cache`, `X-Accel-Buffering: no`); `ui.py` SPA fallback for deep links (`/ui/security/decisions/dec_…`). |

### 4.4 Requests to other owners

- **scaffold:** G9, G10, G11; manifest deps in §7 (esp. the explicit `@radix-ui/*` list and, if Recharts 2.x is pinned with React 19, `react-is@19` as a dependency/override).
- **core-gateway:** G12.
- **dashboard-security / dashboard-governance:** import only the public surfaces in §4.2; don't toast SSE events listed in §2.8 (G4); use `teamColor()` for teams (G6); suggested shortcut map to avoid collisions: `g o` overview, `g l` live, `g y` playground, `g t` threats, `g c` coverage, `g u` audit, `g a` approvals, `g b` budgets, `g r` rules, `g g` org, `g p` policy, `g m` perf, `g h` health (registry warns on duplicates, first wins).
- **audit-metrics:** `StatsResponse.kpis.cost_avoided_usd` and `timeseries` must be populated for the overview to be non-zero; `GET /api/decisions?limit=50` newest first for backfill.

---

## 5. Tasks

Order = build order. **Interfaces first:** after UIS-01 + UIS-02 (~25 min) every binding import in §4.2 resolves and type-checks, so dashboard-security/governance are unblocked; implementations then deepen without signature changes.

### Must

**UIS-01 · Foundations & public-surface skeleton** — must · demo_critical yes · 12 min · deps: scaffold manifests, frozen `page.ts`/`types.ts`
- [ ] `styles/tokens.css`, `styles/effects.css`, `styles/globals.css` (Tailwind v4 `@theme inline`, shadcn vars, decision/role utilities, base layer: body bg/grid/glow, Inter/JetBrains Mono, `font-feature-settings`, tabular-nums, scrollbars, focus ring, reduced motion)
- [ ] `main.tsx`, `vite-env.d.ts`, `App.tsx` (minimal), `public/favicon.svg`
- [ ] `lib/utils.ts`, `lib/format.ts`, `lib/colors.ts`, `lib/icons.ts`, `lib/storage.ts`, `lib/mockMode.ts`, `lib/viewer.ts`, `lib/motion.ts`
- [ ] barrels `components/shell/index.ts`, `components/charts/index.ts` exporting every §4.2 name (thin but working implementations allowed; final props)
- Acceptance: `npm run typecheck` clean for owned files; importing every §4.2 name compiles.

**UIS-02 · shadcn/ui primitives** — must · demo_critical yes · 12 min · deps: UIS-01
- [ ] the 24 primitives + `toggle.tsx` + `sonner.tsx` (themed Toaster, re-export `toast`) in kebab-case files under `components/ui/`
- [ ] dark styling via semantic vars; `tw-animate-css` enter/exit on dialog/sheet/popover/dropdown/tooltip; `Button`/`Badge` variants per §2.3
- Acceptance: each file exports the standard shadcn component names (e.g. `Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose`); typecheck clean.

**UIS-03 · API client** — must · demo_critical yes · 8 min · deps: UIS-01
- [ ] `api.get/post/patch/download/url`, `ApiResult`, `ApiRequestError`, `isApiRequestError`, view-as header, mock fallback rules (§2.5), forced-mock short-circuit, once-per-path `console.info`
- Acceptance: with no backend + mock → `{isMock: true}`; a JSON 403 envelope throws `ApiRequestError` with `type`/`approvalId`; `?mock=1` never touches the network for calls with mocks.

**UIS-04 · SSE hub & hooks** — must · demo_critical yes · 12 min · deps: UIS-03
- [ ] `api/sse.ts`: `SSE_EVENTS`, ref-counted EventSource, status store, backoff + 35 s stale detection, viewer-change reconnect, 200 ms decision batching, mock pump attach
- [ ] `api/hooks.ts`: all §4.2 hooks; `useApi` SWR cache keyed `viewer|path` with in-flight dedupe, keep-previous-data, abort on unmount/path change, `refreshMs`, debounced (≥ 500 ms) `refreshOn`; `useLiveDecisions` shared ring buffer + `/api/decisions?limit=50` backfill + dedupe; `useViewAs` via `useSyncExternalStore`; `usePendingApprovals` from `/api/approvals?status=pending` (`counts.pending`) refreshed on `approval.*` and overridden by fresher `StatsTick.approvals_pending`
- Acceptance: two components subscribing → one EventSource; StrictMode double-mount → still one; switching viewer refetches and reconnects.

**UIS-05 · Shell kit components** — must · demo_critical yes · 12 min · deps: UIS-02
- [ ] `PageHeader, Panel (glass, isMock → MockBadge in header), KpiTile (AnimatedNumber, delta pill, sparkline, tone accent bar, skeleton), ActionBadge, RoleBadge, DestBadge, IdentityChip (member name lookup via useMembers; agent bot avatar), StatusDot, MockBadge, EmptyState, JsonView (collapsible, syntax colours, copy), TimeAgo (shared 5 s ticker, absolute time in title), RoleGate, AnimatedNumber, UsageBar (80/100 markers, state colours, width transition), LiveDot, Kbd, ErrorBoundary`
- Acceptance: a scratch render of each in the overview (temporarily) looks like the prototype equivalents; all accept the §4.2 props.

**UIS-06 · Chart wrappers** — must · demo_critical yes · 10 min · deps: UIS-01
- [ ] `charts/theme.ts` (grid `#1A1E24`, axis `#2A2F37`, tick `#7A808C` 10.5 px tabular, tooltip glass), `ChartTooltip` (title + swatch rows + right-aligned values), `ChartLegend`
- [ ] `AreaTimeseries` (area/bar/line, stacked with 2 px surface gaps via stroke, bars ≤ 24 px with 4 px top radius, `ResponsiveContainer`, reference lines, annotations, animation 640 ms ease-out), `Sparkline`, `BarList` (HTML bars, framer width grow, hover), `Gauge` (SVG ring, framer `pathLength` draw, tone auto from value/max)
- Acceptance: renders with empty data (EmptyState), with 1 point, with 96 buckets; no console warnings about width/height 0.

**UIS-07 · App frame: registry, router, layout, view-as** — must · demo_critical yes · 14 min · deps: UIS-04, UIS-05
- [ ] `lib/registry.ts` (validation, defaults, sort, locks, duplicate warnings), `router.tsx` (basename, `PageFrame` with ErrorBoundary + transition + title), `AppShell` (grid, collapsible sidebar ≤ 1180 px to 64 px icons), `Sidebar` (Brand, org chip "Acme Capital · Production", sections, active state, badges `approvals`/`live`/`feed`, lock icons + tooltip, footer health lines → `/system/health`), `Topbar` (crumbs, ⌘K button, ConnectionPill, VersionPill with flash on change from `/healthz` + `policy.applied`/`feed.updated`, ViewAsSwitcher), `ViewAsSwitcher` (segmented quick picks Owner → u_katarzyna, Admin → u_emily, Member → u_piotr + avatar dropdown listing all members grouped by role with title and RoleBadge), `LockedPage`, `NotFound`, `RouteError`
- Acceptance: every discovered page appears in the right section/order; `nav:false` hidden; `/ui/security/decisions/x` resolves; switching viewer shows toast + RoleBadge change + header on next request.

**UIS-08 · Shell mocks & forced-mock pump** — must · demo_critical no · 8 min · deps: UIS-03
- [ ] `mocks/shell/{rng,org,decisions,stats,budgets,perf,health,posture,pump}.ts` typed with §5.5 types; demo cast & budgets per §3.2; seeded deterministic curves (diurnal, as prototype); masked previews only
- Acceptance: `?mock=1` → whole shell + overview populated, events every ~1–2 s; `?mockRate=20` sustains 20 ev/s.

**UIS-09 · Global event toasts & banners** — must · demo_critical yes · 7 min · deps: UIS-04, UIS-07
- [ ] `EventToasts` + `SystemBanners` per §2.8 (dedupe, max 4, actions navigate via router), killbar initialised from `/api/budgets`, offline banner
- Acceptance: a `policy.applied` payload produces "Policy v{n} applied in {ms} ms" + change summaries; `feed.rejected` shows the persistent banner.

**UIS-10 · Overview core (rows A–C)** — must · demo_critical yes · 18 min · deps: UIS-05, UIS-06, UIS-07, UIS-08
- [ ] `useOverviewData` (stats/budgets/approvals/posture inputs + live overlay §2.2), `lib/posture.ts`
- [ ] `KpiRow` (6 tiles incl. spend vs budget with UsageBar + forecast, cost avoided, posture Gauge), `LiveTicker` (rAF marquee, queue, hover pause, click-through, reduced-motion fallback), `DecisionsChartCard` (stacked bars, toggle, live last bucket), `LiveStreamCard` (AnimatePresence, action flash, View all)
- [ ] `overview.page.tsx` with `meta` (§2.1), header chips, window toggle persisted, staggered entrance (40 ms), count-up from 0 on first load only
- Acceptance: rows A–C fit above the fold at 1536×864; with live/mocked SSE the ticker scrolls, tiles bump on new block/redact, last bar grows.

**UIS-11 · Build & integration gate** — must · demo_critical yes · 6 min · deps: all must tasks (run last, after should/could work)
- [ ] `cd web && npm run build`; if `tsc -b` fails **only** because of other workstreams' files, build with `npx vite build` so `web/dist` exists, and list the offending files/owners in the report
- [ ] check dist served by gateway at `/ui/` (deep-link refresh works), no CDN URLs, fonts bundled
- Acceptance: UIS-V09 passes.

### Should

**UIS-12 · Overview full (rows D–E)** — should · demo_critical yes · 18 min · deps: UIS-10
- [ ] `SpendBurnCard` (cumulative today, 80 %/100 % reference lines, forecast dashed segment, single axis), `TeamSpendCard` (UsageBar per team + state badges + team swatches), `PostureCard` (Gauge + factor list with points/tooltip), `TopControlsCard`, `DataProtectedCard`, `DestinationsCard`, `TopAgentsCard`; "k awaiting you" approvals chip via `usePendingApprovalsDetail`
- Acceptance: disabling a control (policy.applied) lowers the posture score within ~1 s; team bars move on `budget.updated`.

**UIS-13 · Performance page `/system/perf`** — should · demo_critical yes (F10) · 12 min · deps: UIS-06
- [ ] KPI tiles p50/p95/p99 overhead, RPS (1 m), overhead share of upstream ("2.1 ms of 820 ms = 0.26 %"), live p50/p95 line from `stats` ticks (last 2 min), per-control p95 `BarList` sorted with kind tags, upstream by provider/model table, semantic models table (loaded StatusDot, backend, p50), `bench` summary (`JsonView`) when present, "How we measure" note (`Server-Timing` example); refresh 5 s
- Acceptance: renders with real `/api/perf` and with mock; numbers formatted with `fmtMs`.

**UIS-14 · Health page `/system/health`** — should · demo_critical no · 8 min · deps: UIS-05
- [ ] overall status banner, `/healthz` components grid (StatusDot), versions (gateway, policy v, feed #, uptime), SSE status + last event time, feed summary, semantic status, **Verify audit chain** button (`/api/audit/verify` → "Chain OK · N records · head ab12…" / broken at seq), demo-data (mock) toggle
- Acceptance: verify button shows result; mock toggle flips `?mock` behaviour after reload.

**UIS-15 · Command palette & keyboard navigation** — should · demo_critical no · 10 min · deps: UIS-07
- [ ] cmdk dialog (⌘K / Ctrl+K): "Go to" (registry pages with icon, description, shortcut; locked ones disabled with lock), "View as" (all members), "Actions" (verify audit chain, toggle demo data, copy Claude Code env snippet `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`, open playground `/security/playground`); `g <key>` navigation from `meta.shortcut`
- Acceptance: ⌘K → type "appr" → Enter navigates; `g h` opens health.

**UIS-16 · Motion & video polish pass** — should · demo_critical yes · 12 min · deps: UIS-10..13
- [ ] first paint: skeleton shimmer → tiles stagger in < 600 ms; number count-ups; block/redact bump flash; live-dot ping; ticker speed tuned for 1080p capture (~45 px/s); glow/grid subtle at 125 % zoom; reduced-motion path; responsive at 1280 / 1440 / 1920; no horizontal scroll; text contrast ≥ 4.5:1 for body text
- Acceptance: UIS-V10 passes.

### Could

**UIS-17 · Version annotations** — could · 6 min · `/api/policy/history` + `FeedStatus.history` → vertical markers "v15" / "feed #44" on the decisions chart (research 04 §4.6 "see the system adapt").
**UIS-18 · Global kill switch control** — could · 8 min · topbar button (`RoleGate min="admin"`), dialog with scope picker (global / team / agent from `/api/agents`), `POST /api/killswitch` → handle `ApplyResult.status` (`pending_approval` → toast with approval link; 403 → reason).
**UIS-19 · Export management report** — could · 5 min · print stylesheet + "Export report" → `window.print()` (PDF via browser), admin-only "Audit CSV" via `api.download('/api/audit/export?format=csv')`.
**UIS-20 · Admin token support (G8)** — could · 4 min · input on Health page + ⌘K action; client attaches `Authorization` to mutating `/api/*`.
**UIS-21 · Shared Monaco setup (only if dashboard-governance asks)** — could · 8 min · `lib/monaco.ts`: `loader.config({ monaco })` from bundled `monaco-editor`, Vite `?worker` editor worker, `aegis-dark` theme from tokens.

### Verification tasks

| ID | Proves | Command / check | Expected |
|---|---|---|---|
| **UIS-V01** | type & lint hygiene of owned files | `cd web && npm run typecheck 2>&1 \| grep -E 'src/(main\|App\|router\|vite-env)\|src/(lib\|styles\|mocks/shell\|components/(ui\|shell\|charts)\|pages/overview\|pages/system)\|src/api/(client\|sse\|hooks)'` ; `cd web && npx eslint src/main.tsx src/App.tsx src/router.tsx src/lib src/api/client.ts src/api/sse.ts src/api/hooks.ts src/components/ui src/components/shell src/components/charts src/mocks/shell src/pages/overview.page.tsx src/pages/system` | no output from the grep; eslint 0 errors |
| **UIS-V02** | binding public surface exists | `grep -cE 'export (const\|function\|class\|interface\|type) (api\|ApiResult\|ApiRequestError)' web/src/api/client.ts`; `grep -oE '(useApi\|useEvents\|useLiveDecisions\|useViewAs\|usePendingApprovals)\b' web/src/api/hooks.ts \| sort -u \| wc -l` (=5); `for n in PageHeader Panel KpiTile ActionBadge RoleBadge DestBadge IdentityChip StatusDot MockBadge EmptyState JsonView TimeAgo RoleGate; do grep -q "$n" web/src/components/shell/index.ts \|\| echo MISSING $n; done`; same loop for `AreaTimeseries BarList Gauge Sparkline` in charts; `for f in button card badge table tabs dialog sheet dropdown-menu select input textarea label switch slider tooltip popover command separator scroll-area skeleton avatar progress alert toggle-group sonner; do test -f web/src/components/ui/$f.tsx \|\| echo MISSING $f; done`; `grep -E 'export (const\|function) (fmtUsd\|fmtNum\|fmtPct\|fmtMs\|fmtTime\|fmtAgo)' web/src/lib/format.ts \| wc -l` (=6) | no MISSING lines; counts as stated |
| **UIS-V03** | forced-mock UI smoke | `cd web && npx vite --port 0` (note printed URL; stop it afterwards) → open `<url>/ui/?mock=1` | sidebar lists all discovered pages by section; 6 KPI tiles + "demo data" badges; ticker scrolling; new stream row every ~1–2 s; ConnectionPill "Demo data"; browser console has no errors |
| **UIS-V04** | unforced fallback (endpoints 404, no SSE) | `cd web && npm run build && npx vite preview --port 0` → open `/ui/` (no `?mock`) | panels render mock data with MockBadge; ConnectionPill goes connecting → reconnecting → "Offline · retrying"; **no** synthetic ticker events; no unhandled promise rejections |
| **UIS-V05** | live integration with the real gateway, same origin | `AEGIS_UI_DIST=web/dist uv run --frozen python -m aegis serve --port 0` (note port P) → open `http://127.0.0.1:P/ui/`; then `curl -s -XPOST http://127.0.0.1:P/v1/guard -H 'content-type: application/json' -H 'X-Aegis-Agent: research-agent@research' -d '{"interaction":{"kind":"model_call","surface":"model.request","text":"Client PESEL 44051401359"}}'` and a blocked one (fake AWS-key-shaped string generated at runtime); `curl -N "http://127.0.0.1:P/api/events?view_as=u_piotr" \| head -5`; reload `http://127.0.0.1:P/ui/system/health` | ticker + stream show `Redact · DLP-01` then `Block · DLP-02` within 1 s; Blocked tile +1 with bump; no MockBadge on endpoints that exist; deep-link reload works; SSE prints `event:` lines; kill the server afterwards |
| **UIS-V06** | view-as | in the browser: switch Owner → Member (u_piotr); inspect network | every `/api/*` request carries `X-Aegis-View-As: u_piotr`; EventSource URL has `view_as=u_piotr`; toast "Viewing as Piotr Zieliński · Member"; reload keeps viewer; `/ui/?view_as=u_emily` opens as Emily and the param disappears from the URL; temporarily set `minRole:'admin'` on `system/health.page.tsx` → lock icon + LockedPage as u_piotr, unlocked as u_emily (revert after) |
| **UIS-V07** | hot-reload toast (F7) | gateway from V05 with `AEGIS_POLICY` pointing at a temp copy of `config/policy.golden.yaml`; edit a threshold in the copy and save; then introduce a YAML syntax error | within ~1 s toast "Policy v{n+1} applied in … ms" with the change summary, VersionPill flashes; posture refreshes; YAML error → "Policy change rejected — still on v{n+1}" with line:col |
| **UIS-V08** | other SSE events | with approvals/feed/budgets services available: create an approval (`POST /api/approvals` with an `ApprovalDraft`) / `POST /api/killswitch` (as admin) / feed-service tamper; otherwise inject via `?mock=1` pump | approvals badge increments with violet toast + "Review" link; killbar appears; feed rejected banner persists; toasts deduped (≤ 4 visible) |
| **UIS-V09** | build & offline readiness | `cd web && npm run build` (fallback `npx vite build`, see UIS-11); `ls web/dist/index.html web/dist/assets/*.woff2`; `grep -rlE 'fonts.googleapis\|gstatic\|jsdelivr\|unpkg\|cdnjs' web/dist \|\| echo NO_CDN`; `du -sh web/dist` | build succeeds; woff2 fonts present; `NO_CDN`; dist size reported (expect < 4 MB without Monaco chunks) |
| **UIS-V10** | visual/motion/perf QA for the video | screenshots of `/ui/?mock=1` at 1440×900, 1920×1080 with 125 % zoom, 1280×800; emulate `prefers-reduced-motion`; `?mock=1&mockRate=20` for 60 s | rows A–C above the fold at 1536×864; no overflow/horizontal scroll; reduced motion → static ticker, no count-ups; at 20 ev/s UI stays responsive (scrolling smooth, no growing memory: buffer capped at 500) |
| **UIS-V11** | system pages | open `/ui/system/perf` and `/ui/system/health` (mock and live) | p50/p95/p99 tiles, per-control bars, semantic table; Verify chain → "Chain OK · N records" (live) or mock result with badge |

---

## 6. Demo cut

**Must really work live (never faked):**
- Page auto-discovery + sidebar for every sibling page; role locks; error isolation per page.
- View-as switcher: header on every API call, SSE reconnect with `view_as`, persisted, deep-linkable (`?view_as=`) — this is how approvals by role (F4/F5) are shown.
- Live ticker / stream / KPI increments driven by the **real** SSE `decision` events and `/api/stats`; spend vs budget from the **real** `/api/budgets` (gauges move during F6).
- Global toasts for `policy.applied` (with latency + diff summary), `policy.rejected`, `feed.updated/rejected` banner, `approval.created` + approvals badge, kill-switch banner.
- Static build served by the gateway at `/ui/` offline (no CDN).

**May be simplified / derived / mocked convincingly (always with honesty markers):**
- Posture score — client-side formula over real endpoints (explained per factor in tooltips).
- Spend forecast — linear projection; cost avoided — whatever audit-metrics reports.
- Any endpoint not yet implemented by its owner → mock data with a visible "demo data" badge.
- Version annotations, kill-switch control, export report, admin token (could tier).
- Synthetic event pump — only with `?mock=1` (UI dev / backup video), never silently.

**Cut lines (drop in this order if late):** UIS-21 → UIS-19 → UIS-20 → UIS-17 → UIS-18 → UIS-15 → UIS-14 → row E of UIS-12 → row D of UIS-12 → UIS-13 (keep at least the overhead tiles from `/api/perf` on the overview's system status if cut). Never cut UIS-01..UIS-11.

**Video notes:** record at 1920×1080, browser zoom 125 %, dark; clear state first (gateway reset) so the first ticker item is the one on camera; overview is the establishing shot (0:05–0:08 behind the architecture pulse) and the place where the policy toast lands if the governance page isn't on screen.

---

## 7. Dependencies

### 7.1 npm (scaffold puts them in `web/package.json`; implementer installs nothing)

Runtime: `react@^19`, `react-dom@^19`, `react-router-dom@^7`, `tailwindcss@^4` + `@tailwindcss/vite@^4`, `tw-animate-css`, `class-variance-authority`, `clsx`, `tailwind-merge@^3` (v3 for Tailwind 4), `lucide-react` (recent, must export the `icons` map), `recharts` (`^3` preferred; if `^2.15`, add `react-is@^19` for React 19), `framer-motion@^12` (`motion` package acceptable if aliased — import path `framer-motion` assumed), `sonner@^2`, `cmdk@^1`, `date-fns@^4`, `@fontsource-variable/inter`, `@fontsource-variable/jetbrains-mono`, `monaco-editor` + `@monaco-editor/react` (governance; only UIS-21 touches them).
Radix (explicit list for the primitives): `@radix-ui/react-slot`, `-dialog`, `-dropdown-menu`, `-select`, `-switch`, `-slider`, `-tooltip`, `-popover`, `-separator`, `-scroll-area`, `-avatar`, `-progress`, `-tabs`, `-label`, `-toggle`, `-toggle-group`. Recommended for sibling dashboards (primitives can be added by their owners' request): `-checkbox`, `-radio-group`, `-collapsible`, `-accordion`, `-hover-card`.
Dev: `vite@^6||^7`, `@vitejs/plugin-react`, `typescript@^5.6`, `@types/react@^19`, `@types/react-dom@^19`, `@types/node`, `eslint@^9`, `typescript-eslint`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh` (with G9). No test runner needed (verification = typecheck, lint, build, browser checks).

### 7.2 Other workstreams (what is consumed · how the shell degrades)

| Owner | Consumed | Degrade when missing |
|---|---|---|
| scaffold | manifests, `vite.config.ts`, `tsconfig*`, `index.html`, `components.json`, eslint, frozen `page.ts`/`types.ts` | blocker for build; implementer can still write code against CONTRACTS text |
| core-gateway | `/api/events`, `/healthz`, `ui.py` static + SPA fallback | SSE offline pill/banner; health mock; Vite dev server for UI work |
| audit-metrics | `/api/stats`, `/api/perf`, `/api/decisions`, `/api/audit/verify`, `stats` ticks | mocks + MockBadge; ticker relies on SSE only |
| budgets-ledger | `/api/budgets`, `/api/budgets/history`, `killswitch`/`budget.*` events | mocks; killbar from SSE only |
| org-rbac | `/api/members`, `/api/whoami`, `/api/org` | seed-cast mock members; view-as still sends headers |
| approvals-engine | `/api/approvals?status=pending`, `approval.*` events | badge from `StatsTick.approvals_pending`, else mock count |
| policy-engine | `/api/controls`, `/api/coverage`, `/api/policy/history`, `policy.*` events | posture factors fall back to mocks (badge on PostureCard) |
| threat-feed | `/api/feed/status`, `feed.*` events | posture feed factor mock; no banner |
| semantic-models | `/api/semantic/status` | health page shows "unknown" |
| dashboard-security / -governance | their `*.page.tsx` appear automatically | n/a — they depend on us; ErrorBoundary isolates their runtime errors |

### 7.3 Snippet

`config/snippets/dashboard-shell.yaml`: **none** (no controls, no policy keys).

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `npm run build` (`tsc -b`) fails because of type errors in **other** workstreams' pages, blocking `web/dist` | UIS-11 fallback `npx vite build` (no typecheck) so the demo UI ships; report offending files to owners; run V01 early so our own files are clean |
| A sibling page throws at render/runtime and takes down the whole app | per-route `ErrorBoundary` + `RouteError`; registry skips modules without `default`/`meta` with a warning (module-evaluation errors can't be isolated with an eager glob — called out to siblings: no import-time side effects) |
| Mock fallback hides real failures or policy answers | fallback only for unavailable endpoints (G7); every mocked panel shows MockBadge; 4xx / JSON envelopes always throw; synthetic SSE only when forced |
| Contract colours vs prototype (redact/approval swapped, brand violet) confuse the visual language | single source `lib/colors.ts` + CSS vars; brand moved to indigo; badges always label + icon; palette validated (CVD floor ⇒ legends + 2 px gaps mandatory) |
| Event floods during the runaway-agent scene (F6) → janky UI / toast spam | 200 ms batching, capped ring buffer (500) and ticker DOM (≤ 30 items), toast dedupe (2 s) and max 4, `?mockRate=20` stress test (V10) |
| SSE buffered by GZip/proxy → no live updates on stage | G12 request; ConnectionPill makes it visible; `heartbeat` stale detection triggers reconnect; `replay=100` backfills after reconnect |
| Recharts 3 vs 2 API differences / React 19 peer issues | wrappers isolate Recharts; avoid deprecated props (`activeIndex`, legacy `Cell`-heavy patterns); check installed major before writing; `react-is@19` if v2 |
| Tailwind v4 + shadcn var conventions mismatch (utilities not generated) | `@theme inline` mapping written once in UIS-01 and smoke-checked in V03 (`bg-card`, `text-muted-foreground`, `bg-allow/10` visibly applied) |
| StrictMode double effects → duplicate EventSources / pumps | ref-counted hub, idempotent start/stop |
| View-as race (responses for the old viewer land after the switch) | cache key includes viewer; abort in-flight on epoch change |
| lucide `icons` map inflates the bundle (~0.4 MB) | acceptable for a locally served demo; if needed swap to a curated map in `lib/icons.ts` (no API change) |
| Video legibility at 1080p | type scale from prototype (13.5 px body, 28 px KPI values), 125 % zoom target, tabular-nums, contrast checked in V10 |
| 8 GB RAM pressure during verification | Vite/preview/gateway started on port 0 one at a time and killed after each check; build once at the end |
| Time overrun (scope is wide) | strict must → should → could order; cut lines in §6; interfaces frozen in the first ~25 min so siblings never wait |
