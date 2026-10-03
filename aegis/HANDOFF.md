# Aegis — HANDOFF (start here)

> Single entry point for ANY agent (Claude Code, Codex, other) picking up this project.
> The **Snapshot** and **How to continue** sections are maintained by the orchestrator.
> Everyone else may only **append** to the **Progress log** at the bottom, using a shell append
> (`printf '%s\n' "- [HH:MM] [who] message" >> HANDOFF.md`) — never rewrite this file with an editor,
> because many agents work in parallel.

## What we are building
**Aegis** — a local-first **AI Control Layer** for the HackYeah 2026 **Goldman Sachs** task ("AI Control Layer").
A gateway (Python 3.13 / FastAPI, port 8787) between agents/apps (incl. **Claude Code**, local Ollama agents) and
models / MCP servers / third-party APIs that: redacts PII, payment cards, Polish IDs, secrets and metadata **locally
before anything leaves** (reversible placeholders, restored only toward the local user); blocks prompt injection,
dangerous commands and exfiltration (hybrid rules + small local models); enforces token/cost **budgets**; routes risky
actions to **org approvals** (owner / admin / member roles, e.g. "$50 subscription → admin", "raise budget >2× → owner");
pins MCP tools; consumes a **signed threat-signature feed** (port 8790); logs everything to a hash-chained audit log; and
shows it all in a polished **React dashboard** at `/ui` with a live policy editor that judges can edit while it runs.
Requirements & product vision: `docs/BRIEF.md`.

## Deadlines
- Submission on **HackTribe** (team leader, Discord login) — plan to be uploaded by **Sun 4 Oct 10:00**; hard deadline **Sun 11:00** (some docs say 23:00 — treat 11:00 as real). Jury from 11:00, finalists 15:00, pitches 16:00.
- Submission fields: English title ≤5 words, ≤500-word description (+ every member's name/email), ≥1 image, ≤10-slide English PDF, optional ≤60 s video, repo link, judge instructions. Drafts: `staging/submission/`.

## Where everything is
| What | Path |
|---|---|
| Requirements, fixed tech decisions | `docs/BRIEF.md` |
| **Binding contract** (repo tree, ownership map, types, API, schemas, ports, parallel rules) + Addendum | `docs/CONTRACTS.md` |
| 20 workstream plans (tasks, subtasks, verification) | `docs/plan/NN-<slug>.md` |
| Planner / implementer instructions | `docs/plan/_PLANNER_INSTRUCTIONS.md`, `docs/plan/_IMPLEMENTER_INSTRUCTIONS.md` |
| Master plan, all tasks with checkboxes, build bundles | `docs/MASTER_PLAN.md`, `docs/TASKS.md`, `docs/plan/BUNDLES.json` *(created by the synthesizer)* |
| Per-bundle implementation status | `docs/status/<bundle-id>.md` |
| Pre-built, tested code & data to reuse | `staging/` — `models/` (ONNX + Ollama wrappers, RESULTS.md), `pii/` (detectors, vault, rehydrator, 626 fixtures), `corpora/` (1194 eval cases), `feed-seed/` (20 signed signatures + engine), `seed/` (org, policy.yaml 37 controls, approvals.yaml 65 rules, SCENARIOS.md), `design/` (hi-fi prototype + DESIGN_TOKENS.md), `submission/` (HackTribe text, deck, video, runbook, diagrams), `spikes/claude-code` + `spikes/mcp` + `spikes/streaming` (verified working code + FINDINGS) |
| Research (7 reports) | `/Users/nevvdevv/Development/hackathons/_october_2026/hackyeah/research/goldman/01…07` |
| Downloaded models (gitignored) | `models/`; Ollama aliases `aegis-guard` (Qwen3Guard-0.6B), `aegis-judge` (Qwen3.5-0.8B), plus `qwen3:0.6b` |

## Snapshot (orchestrator-maintained) — last update Sat 23:20 (ALL AGENTS STOPPED by user request)
| Phase | Status |
|---|---|
| 0 Research (7 reports) | ✅ done |
| 1 Staging artifacts (10 packages) | ✅ done, all tested |
| 2 Contracts (`docs/CONTRACTS.md`) | ✅ done |
| 3 Workstream plans | ✅ 20/20 done (`docs/plan/01…20-*.md`) |
| 4 Synthesis | ✅ **Addendum A** (A-01…A-58, at the END of `docs/CONTRACTS.md`, from ~line 3491; overrides earlier text) + seed fixes SF-01…SF-27 in `docs/seed-fixes/`; `docs/MASTER_PLAN.md`, `docs/TASKS.md` (365 tasks + 269 verifications + INT-01..16 / KI-01..05), `docs/plan/BUNDLES.json` (25 bundles), `docs/plan/DEPENDENCIES.json` |
| 5 Scaffold | ✅ commit `d02636d` — `make setup`, `make gateway`, `make web`, `make test` |
| 6 Build fleet | 🟡 **PARTIAL.** Wave 1 (B01–B20) ran ~20 min (22:55–23:17) and was stopped mid-task. ~565 files written, all uncommitted work is saved in WIP commit (see Progress log). **No bundle finished; no `docs/status/*.md` written yet.** Wave 2 (B21–B25) not started. |
| 7 Integration & verification | ⏳ not started |
| 8 Submission | ⏳ not started (drafts in `staging/submission/`) |

**Health at stop (23:17):** `uv run --frozen python -c "import aegis, aegis.app"` ✅ · `python -m compileall src` ✅ · `cd web && npm run build` ✅ (bundle 1.07 MB, fine). Unit tests not run.

### Bundle state at stop (resume each from here — don't redo)
| Bundle | Files | Done (from logs) | Was doing when stopped → next |
|---|---|---|---|
| B01-gateway-core | 25 | GW-01..06 importable: settings, log, core.{crypto,paths,errors,deps,runtime,nulls,bus,db,sessions,discovery,pipeline}, `app.create_app` (+`route_table`); gateway boots with Null fallbacks. NOTE FastAPI 0.142: use `aegis.app.route_table(app)` | bus/events tests → routes health/events/guard/playground/ui, CLI, tests; apply Addendum A-01/06/07/08 |
| B02-gateway-proxy | 28 | GW-08/09/10: core/timing, proxy/{router,upstream,blocking,sse,streaming,jpath,flow}, adapters anthropic/openai/ollama, routes proxy_anthropic/openai/ollama, `config/snippets/core-gateway.yaml`; Addendum applied | main proxy test GW-V08/V09 → remaining tests, GW-16 optional |
| B03-policy-engine | 19 | POL-02: `config/policy.yaml` (+golden) from seed-fixes, 39 controls, 82 inline tests, validates clean; `config/profiles/{permissive,balanced,strict,paranoid}.yaml` | → POL-01/05 store + routes, hot reload, self-test gate, governed apply |
| B04-redaction-engine | 38 | engine skeleton + detectors ported (details not logged) | smoke test → verify RED tasks vs plan 03, tests |
| B05-metadata-egress | 29 | META-01/02 done, META-03 control written; Addendum adopted | DLP-06 tests → META-04..08, `/egress` |
| B06-injection-defense | 12 | INJ skeleton (aegis.injection.normalize + control stubs) | mid-edit → INJ tasks per plan 05 |
| B07-semantic-models | 16 | SEM-02/06/07/08/09: heuristic, resilience, ONNX/embeddings (shared XLM-R vocab), Ollama guard, engine w/ cache+breakers; live p50: horizon 13 ms, minilm 1.4 ms, ner 5.7 ms, guard 227 ms | CUS-01 → INJ-03/CUS-01 controls, snippet, tests |
| B08-budgets-ledger | 23 | BUD-02..09: pricing.yaml, ledger reserve/settle, SQLite write-behind + demo seed, BUD-01/02/EXE-04 controls (kill=429 per A-07), `/api/budgets*`, `/api/killswitch` | route file → snippet + unit tests |
| B09-org-rbac | 25 | ORG-01 interfaces (aegis.org.service, aegis.org.seed, routes/org.py, GOV-01/02); `config/org.seed.yaml` from seed-fixes | reading Addendum → ORG-02.. + tests |
| B10-approvals-engine | 22 | full ApprovalService, GOV-05, `api/routes/approvals.py` | unit tests (conftest fakes) → snippet + tests |
| B11-action-guards | 24 | ACT-01: `aegis.actions.classify`, 9 controls (GOV-03/04, ACT-01..04, EXE-01..03) with stub evaluate | controls (shell analysis, taint helpers) → ACT-02..07 |
| B12-mcp-proxy | 33 | MCP-01..07 surfaces importable (aegis.mcp.*, controls MCP-01..04, routes mcp.py/mcp_admin.py) | MCP-04 control → mock_mcp servers + tests |
| B13-claude-code | 21 | CC-01: route `POST /v1/hooks/claude-code` (+status), integrations/claude_code/*, `scripts/aegis-hook` fail-closed | apply Addendum (deny prefix `[Aegis] <ID>: `, 600 s completion, meta.cwd, GOV-06 real control, response headers) → profile.py, tests |
| B14-threat-feed | 50 | TI-01..04: matchers (87/87 vectors), feed_service/signatures (21, TI-022 draft), keygen → `config/feeds/feed_pubkey.b64` + seed bundle; private key only in `feed_service/state/` (must stay gitignored) | feed_service/build.py → FeedManager TI-06, SIG-01, routes |
| B15-audit-metrics | 20 | AUD skeleton (not logged in detail) | reading Addendum → AUD tasks per plan 14 |
| B16-dashboard-shell | 68 | UIS-01..06 public surface STABLE (`@/api/client`, `@/api/sse`, `@/api/hooks`, `@/components/shell`, `@/components/charts`, `@/lib/colors`, Button/Badge variants). Shell toasts SSE events (pages must not) | charts BarList/Gauge → app frame + overview page |
| B17-dashboard-security | 37 | UIX-01 foundations (types, libs, atoms, mocks) | UIX-03 decision trace drawer → rest of plan 16 |
| B18-dashboard-gov-approvals | 28 | UIG-01: components/governance/*, mocks/governance/* (govStore API for B19), 3 page stubs | UIG-02 approvals inbox → rest |
| B19-dashboard-gov-policy | 19 | budgets page + policy editor in progress | policy page state hook (UIG-04) → rest |
| B20-demo-stack | 8 | DEMO-01 SDK surface (`aegis.sdk` AegisClient/AegisAdmin, mocks/__init__ helpers) | mock_llm → rest of plan 20 |
| B21–B25 (wave 2) | 0 | not started | start after wave 1 |

### Known issues (still open)
- BEFORE FIRST PUSH: `staging/pii/fixtures` (in commit d02636d) contains realistic fake keys (sk_live_, ghp_, sk-ant-) → GitHub push protection will block. Integrator: drop secret-shaped fixtures from history and generate them at runtime (plan 19 approach). Also confirm `feed_service/state/` (feed private key) is gitignored.
- Each workstream ships a policy snippet under `config/snippets/` — the integrator must merge them into `config/policy.yaml` (see MASTER_PLAN critical path / INT tasks).
- Two-person = owner + a different admin (A-xx); kill switch = 429 "killed" (never 403); budget stop = 402; policy block on model proxies = synthetic 200 (A-07).

## How to continue — with parallel agents (for a fresh orchestrator)
1. Read this file → `docs/BRIEF.md` → `docs/MASTER_PLAN.md` → `docs/plan/BUNDLES.json` → `docs/plan/_IMPLEMENTER_INSTRUCTIONS.md`. Check `git log` and the Progress log tail.
2. **Resume wave 1:** spawn one implementer agent per bundle B01–B20 in parallel (max ~20 concurrent). Use this prompt (replace `<ID>`):
   > Read `/Users/nevvdevv/Development/hackathons/_october_2026/hackyeah/aegis/docs/plan/_IMPLEMENTER_INSTRUCTIONS.md` and follow it exactly. Your bundle: **<ID>** (entry in `docs/plan/BUNDLES.json`). A previous agent already worked on this bundle and was stopped mid-task — read the "Bundle state at stop" row for <ID> in `HANDOFF.md`, the `[<ID>]` lines in its Progress log, and inspect your owned paths before writing anything. Do NOT redo finished work; finish partial files, then remaining tasks in priority order, run your verification tasks, write `docs/status/<ID>.md`, and append progress lines to HANDOFF.md (shell append only). Addendum A at the end of `docs/CONTRACTS.md` overrides earlier text; corrected seeds are in `docs/seed-fixes/`.
3. **Wave 2:** when slots free, run B21-test-suite-harness, B23-demo-agents, B24-redteam-eval-perf, B22-test-suite-functional, B25-docs-submission with the same prompt (they start fresh).
4. **Integration (Phase 7)** — one integrator (or a few with disjoint areas): merge `config/snippets/*` into `config/policy.yaml`, start the stack (`make gateway`, feed, mocks), `make test`, fix cross-bundle breakages, run the demo scenes from `docs/MASTER_PLAN.md`, tick `docs/TASKS.md`, commit. Then **Phase 8**: fill real numbers (`make eval`, `make bench`), deck PDF, 60 s video, HackTribe upload by Sun 10:00.
5. Never redo finished work: trust git + `docs/status/*` + Progress log; re-verify only what you touch.
6. Watch the usage budget (no extra-usage credits): pause all agents at ≥93% of the 5-hour window.

## Rules everyone follows
- Ownership: edit only your owned paths (CONTRACTS ownership map / BUNDLES.json). Shared manifests (`pyproject.toml`, `uv.lock`, `web/package.json`, root `Makefile`), `docs/CONTRACTS.md`, `docs/TASKS.md` and `staging/` are read-only for implementers.
- No git commands except the integrator / orchestrator. No sudo. No machine-wide Claude Code settings (use `claude --settings <file>` profiles only). No working exploit payloads in tests (harmless stand-ins only).
- Machine: Apple Silicon, **8 GB RAM**, ~20 GB disk free. Don't leave servers running; load ML models only if you own the model runtime. Ports: gateway 8787, feed 8790, mocks 8791–8799, Ollama 11434.
- **Usage budget:** the user does NOT want to spend extra-usage credits. If the 5-hour plan window is ≥93% or any extra-usage spend appears, stop all agents and pause until reset.

## Related (not Aegis)
- Parent folder `hackyeah/` = separate **Huawei HarmonyOS** project skeleton (own git repo; DevEco Studio 6.1.1 installed; region switch: `hackyeah/scripts/set-deveco-region-cn.sh` after DevEco first-run). Possible Huawei entry: "Aegis Pocket" approvals companion app (separate project, later).
- Task notes for all HackYeah tasks: `hackyeah/TASKS.md`; idea mockups: `hackyeah/mockups/ideas.html`.

## Decision log
- Sat 17:00 Stack: Python 3.13 FastAPI gateway + React/Vite/Tailwind/shadcn dashboard (not Go) — one backend language for parallel agents, best ML/PII ecosystem.
- Sat 17:00 Standalone repo `aegis/` (outer repo ignores it); org/roles/approvals added as a core feature.
- Sat 17:30 NER: bardsai eu-pii ONNX (Apache-2.0); Polish spaCy models avoided (GPL). CVV/track data dropped, never tokenized.
- Sat 17:50 Planning via direct parallel agents (workflow tool capped at 6 concurrent; Agent tool cap 20).
- Sat 18:20 Paused at 98% of the 5-hour window (no credits used); resumed 22:31 after reset.

## Progress log (append-only)
- [17:39] [architect] docs/CONTRACTS.md written.
- [18:20] [orchestrator] 19/20 plans written; paused for usage window.
- [22:35] [orchestrator] Resumed: finishing plan 19, starting synthesis.
- [22:36] [plan-19] redteam-eval-perf plan written: 16 tasks (7 must) + 12 verifications; corpora→tests/corpora, make eval (≤4 min, Wilson CIs per profile/lang, heatmap) + make bench (spawned gateway, det vs semantic overhead p50/p95 per control) → reports/bench.json for /api/perf; 7 contract gaps
- [22:51] [scaffold] skeleton committed d02636d; run: make setup | make gateway (uv run --frozen python -m aegis serve, :8787 /healthz /ui) | make web | make test | make help; dropped deps: none (presidio/spacy intentionally omitted - plans don't use them); notes: frozen files verbatim from CONTRACTS, shadcn radix-nova primitives in web/src/components/ui, core-gateway + dashboard-shell files are scaffold seeds safe to replace
- [22:54] [synth-B] MASTER_PLAN, TASKS (365 tasks + 269 verifications + INT-01..16/KI-01..05), BUNDLES (25 bundles: 20 wave 1, 5 wave 2; owned_paths disjoint, validated) written; deps union in docs/plan/DEPENDENCIES.json
- [22:55] [B01-gateway-core] started: reading CONTRACTS/plan 01, will land GW-01 public surfaces first
- [22:55] [B02-gateway-proxy] started: reading CONTRACTS/plan 01; core/timing.py first, then GW-08 router/upstream/anthropic adapter
- [22:55] [B03-policy-engine] started: reading CONTRACTS/plan 02; POL-01 skeleton + POL-02 policy.yaml first
- [22:55] [B04-redaction-engine] started: reading CONTRACTS/plan 03; RED-01 skeleton (engine create + DLP CONTROLS stubs) first
- [22:55] [B05-metadata-egress] started: reading CONTRACTS/plan 04; META-01 skeleton first
- [22:55] [B06-injection-defense] started: reading CONTRACTS/plan 05; INJ-01 skeleton (aegis.injection.normalize + control stubs) first
- [22:55] [B07-semantic-models] started: reading CONTRACTS/plan 06; SEM-01 public surface (aegis.semantic.engine:create) first
- [22:55] [B08-budgets-ledger] started: reading CONTRACTS/plan 07; BUD-01 skeleton (ledger create, controls stubs, router) first
- [22:56] [B09-org-rbac] started: reading CONTRACTS/plan 08; ORG-01 skeleton (aegis.org.service:create, aegis.org.seed:main) first
- [22:56] [B10-approvals-engine] started: reading CONTRACTS/plan 09; APR-01 skeleton (aegis.approvals.service:create) first
- [22:56] [B11-action-guards] started: reading CONTRACTS/plan 10; ACT-01 public surfaces (actions/base, params, runtime, controls stubs) first
- [22:56] [B12-mcp-proxy] started: reading CONTRACTS/plan 11; MCP-01 stubs first, then jsonrpc/detect port
- [22:56] [B13-claude-code] started: reading CONTRACTS/plan 12; CC-01 skeleton (route POST /v1/hooks/claude-code + integrations/claude_code pkg) first
- [22:56] [B14-threat-feed] started: reading CONTRACTS/plan 13; TI-01 stubs (feed manager, SIG controls, /api/feed route) first
- [22:56] [B15-audit-metrics] started: reading CONTRACTS/plan 14; AUD-01 skeleton (audit.log/metrics.prom create + 4 routers) first
- [22:56] [B16-dashboard-shell] started: reading CONTRACTS/plan 15; UIS-01 foundations + UIS-02 primitives first (frozen names for B17-B19)
- [22:56] [B17-dashboard-security] started: reading CONTRACTS/plan 16; UIX-01 foundations (types, libs, atoms) + mocks first
- [22:56] [B18-dashboard-gov-approvals] started: reading CONTRACTS/plan 17; UIG-01 foundation (governance lib, gov-api, hooks, shared components, mocks) first
- [22:56] [orchestrator] Build wave 1 launched: B01–B19 running; B20 + B21–B25 queued (20-agent cap).
- [22:56] [B19-dashboard-gov-policy] started: reading CONTRACTS/plan 17; UIG-03 budgets page + UIG-04 policy editor first
- [22:57] [B14-threat-feed] TI-01 stubs landed: aegis.feed.manager:create (disabled), aegis.feed.matchers (compile_signature/match), SIG-01/02/03 CONTROLS (None), routes /api/feed/{status,signatures,refresh}; next TI-02 matcher port
- [22:58] [B05-metadata-egress] interfaces up: controls DLP-03/04/06 (stub None), route POST /egress (501 stub), aegis.egress.{params,policyview,compat}; implementing META-02..08 next
- [22:59] [B07-semantic-models] SEM-01 interfaces up: aegis.semantic.engine:create (stub, degraded), CONTROLS INJ-03/CUS-01 (stubs), GET /api/semantic/status; filling in heuristic+engine next
- [22:59] [B08-budgets-ledger] BUD-01 skeleton landed: aegis.budgets.ledger:create, aegis.budgets.tokens.estimate_tokens, BUD-01/BUD-02/EXE-04 CONTROLS stubs, route budgets.py; next BUD-02..05 ledger core
- [23:04] [B02-gateway-proxy] interfaces landed: core/timing.py (Stopwatch, add_timing, timed, server_timing_header), proxy/{router,upstream,blocking,sse,streaming,jpath}.py, adapters anthropic/openai/ollama (ADAPTERS); next: proxy/flow.py + proxy_* routes
- [23:06] [B01-gateway-core] GW-01..06 importable: aegis.settings (Settings.env/public_url), aegis.log, core.{crypto(hmac_hex),paths,errors(api_error,AegisHTTPError,wire_error,block_status,verdict_error),deps(get_rt,viewer,require_role),runtime(get_runtime,Runtime,SERVICE_TABLE),nulls,bus,db,sessions(resolve_session_id,session_hint_from_body),discovery,pipeline(new_context/evaluate/complete/record_only/wire/attach_*)}, app.create_app(+route_table). Gateway boots with Null fallbacks. NOTE FastAPI 0.142: app.routes holds _IncludedRouter -> use aegis.app.route_table(app). next: routes health/events/guard/playground/ui + CLI + tests
- [23:08] [synth-A] Addendum A written: 204 gaps resolved (A-01..A-58, SF-01..SF-27 in CONTRACTS.md); seed fixes in docs/seed-fixes/
- [23:09] [B18-dashboard-gov-approvals] UIG-01 interfaces up: components/governance/{lib/eligibility,lib/format-gov,lib/line-diff,gov-api,hooks,ApproverBadge,LockedAction,TwoPersonProgress,ExpiryCountdown,RequesterLine,MemberAvatar,PersonaSwitcher}.ts(x), mocks/governance/{fixtures,store,approvals,org,rules}.ts (store API for B19: govStore.createApproval/registerExecutor/bumpPolicyVersion/route/ext), 3 page stubs; typecheck clean. next UIG-02 approvals inbox
- [23:09] [orchestrator] synth-A done (Addendum A, seed fixes); notified B01/B02/B05/B07/B08/B14 to re-read A-01/06/07/08; launched B20.
- [23:09] [B20-demo-stack] started: reading CONTRACTS/plan 20; DEMO-01 interfaces (mocks/__init__, sdk signatures) first
- [23:09] [B11-action-guards] ACT-01 surfaces landed: aegis.actions.classify (classify/ensure_classified), 9 controls (GOV-03/04, ACT-01..04, EXE-01..03) import with stub evaluate; filling ACT-02..07 next
- [23:09] [B13-claude-code] CC-01 skeleton landed: route POST /v1/hooks/claude-code (+GET .../status), integrations/claude_code/{schema,mapping,respond,handler,pending,guards,selfcheck}; scripts/aegis-hook (CC-02) fail-closed works by hand; next: profile.py, tests
- [23:10] [B03-policy-engine] POL-02 landed: config/policy.yaml (+golden, byte-identical) from docs/seed-fixes/policy.yaml (approvals block byte-identical), 39 controls (37 catalog incl GOV-06 + A2A-01/02 reserved), 82 inline tests, validates 0 errors/0 warnings vs frozen PolicyDoc; config/profiles/{permissive,balanced,strict,paranoid}.yaml (profile-varied knobs unpinned in policy.yaml). Next: store/routes (POL-01/05).
- [23:10] [B09-org-rbac] ORG-01 interfaces importable (aegis.org.service:create, aegis.org.seed:main, routes/org.py, GOV-01/02 CONTROLS); config/org.seed.yaml copied from docs/seed-fixes
- [23:11] [B05-metadata-egress] adopted Addendum A (A-01 ctx.policy, A-13 egress raw/tool_args, A-16 no agent profile, A-41 MAC_ADDRESS, A-42, SF-06 test, A-30 header/raw self-tests); META-01/02 done, META-03 control written, testing next
- [23:11] [B14-threat-feed] TI-02/03/04 done: aegis.feed.matchers ported (87/87 vectors), feed_service/signatures (21, TI-022 draft, acme-capital host), lists, keygen -> config/feeds/feed_pubkey.b64 + seed_bundle.json(.sig) (key b147d42c; private key only in feed_service/state). Next: FeedManager (TI-06), SIG-01, routes
- [23:12] [B10-approvals-engine] public surfaces landed: aegis.approvals.service:create (full ApprovalService), controls/config/gov05_config.py (GOV-05), api/routes/approvals.py; next: snippet + unit tests
- [23:13] [B02-gateway-proxy] GW-08/09/10 code landed (Addendum A-06/07/08/13/16/40 applied): proxy/flow.py ModelCall (+ModelCallResult, handle_model_request, apply_body_mutations) for playground reuse; routes proxy_anthropic (/v1/messages, count_tokens redacted fwd), proxy_openai (+/v1/models), proxy_ollama; snippet config/snippets/core-gateway.yaml; next: tests
- [23:14] [B12-mcp-proxy] MCP-01..07 public surfaces importable (aegis.mcp.{jsonrpc,detect,pins,interactions,proxy,service,client,stdio,claude_config}, controls MCP-01..04, routes mcp.py/mcp_admin.py); next: mock_mcp + tests
- [23:14] [B16-dashboard-shell] UIS-01..06 public surface STABLE (typecheck clean): @/api/client (api.get/post/patch/download/url, ApiRequestError.type/approvalId), @/api/sse (SSE_EVENTS, eventHub, handler(name,data,meta{replay})), @/api/hooks (useApi data:T|undefined, useEvents, useLiveDecisions, useViewAs, usePendingApprovals(+Detail), useStatsTick, useVersions, useWhoAmI, useMembers, getMember), @/components/shell (+AnimatedNumber UsageBar LiveDot Kbd ErrorBoundary Segmented Avatar AgentAvatar), @/components/charts (+ChartLegend ChartTooltip chartTheme), @/lib/colors (+TEAM_PALETTE teamColor SEVERITY_COLORS BUDGET_STATE_COLORS STATUS_TONE), ui Button variant success|danger|danger-ghost, Badge tone=<action|role>. Siblings: don't toast SSE events (shell does). Next: app frame + overview.
- [23:14] [B07-semantic-models] SEM-02/06/07/08/09 core done: heuristic, resilience, onnx/embeddings (shared XLM-R vocab verified), ollama guard (A-44 scores 1.0/0.5/0.0), engine w/ cache+breakers; live: horizon p50 13ms, minilm 1.4ms, ner 5.7ms, guard 227ms. Next: INJ-03/CUS-01 controls + snippet + tests
- [23:16] [B20-demo-stack] DEMO-01 SDK surface importable: aegis.sdk {AegisClient(guard/chat/messages/ollama_chat/mcp_call/mcp_list/egress/complete/wait_for_approval), AegisAdmin, DEMO_AGENTS/DEMO_MEMBERS, typed errors, GuardResult/ChatResult/McpResult/EgressResult}; mocks/__init__ helpers (PORTS, RequestLog, run_cli, serve_many). next: mock_llm
- [23:16] [B08-budgets-ledger] BUD-02..09 code landed (pricing.yaml, ledger reserve/settle/AND, SQLite write-behind + demo seed, BUD-01/BUD-02/EXE-04 controls per Addendum A-07 kill=429, /api/budgets* + /api/killswitch); next: snippet + unit tests
- [23:19] [orchestrator] ALL AGENTS STOPPED (user request). Wave 1 partial (~565 files), health: import ok, compileall ok, web build ok. Committed as WIP. Resume per 'How to continue — with parallel agents'.
- [23:20] [orchestrator] WIP commit 7da66a9 (tree clean). Huawei side handoff: ../HUAWEI_HANDOFF.md.
