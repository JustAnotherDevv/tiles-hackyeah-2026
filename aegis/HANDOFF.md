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
- [23:22] [orchestrator] New orchestrator session resumed; usage 5h window 0%; launching wave 1 resume (B01–B20).
- [23:23] [B02-gateway-proxy] resumed (agent 2): 50/50 existing unit tests pass; checking GW-08..17 vs plan, then remaining tests/verification
- [23:23] [B05-metadata-egress] resumed (agent 2): inspecting on-disk state (exfil/channels/claude_code/fixtures present beyond log)
- [23:23] [B01-gateway-core] resumed (agent 2): 27/27 existing tests pass, GW-V01 boots w/ all routers & 0 plugin errors; routes health/events/guard/playground/ui + CLI already present; next: audit vs plan, missing tests (V03-V05, V10), V11 smoke, ruff
- [23:23] [B08-budgets-ledger] resumed (agent 2): code for BUD-01..15 present & imports OK; writing unit tests BUD-V01..V12 + status file
- [23:24] [B03-policy-engine] resumed (agent 2): store/diff/patch/selftest/governance/views/watcher/schema present+importing; wrote src/aegis/api/routes/policy.py (POL-07). Next: tests, snippets tool (POL-16), export_schema.
- [23:24] [B14-threat-feed] resumed: TI-01..08 present (manager/compile/SIG-01/route/feed_service build+app+CLI); doing TI-09 SIG-02, TI-10 UI, TI-11 tests, TI-12 snippet, then TI-13/14
- [23:24] [B07-semantic-models] resumed (agent 2): engine/controls/route verified complete (SEM-V01 ok); doing SEM-05 snippet, SEM-13 fetch script + data/, tests, verification
- [23:24] [B17-dashboard-security] resumed (agent 2): UIX-01/02/04 + DecisionTrace present; doing drawer/decision page → live → playground → threats/audit/coverage/mcp
- [23:24] [B12-mcp-proxy] resumed (agent 2): code for MCP-01..07 + mock_mcp present & importable; doing snippet, mock verification, unit tests (MCP-09), e2e, status
- [23:25] [B06-injection-defense] resumed (agent 2): normalize/views/signatures+catalog done; writing segments/canary/explain/cascade + INJ-01/02/04 controls, snippet, tests
- [23:25] [B18-dashboard-gov-approvals] resumed: UIG-01/02/11/13 found complete (typecheck clean); doing UIG-06 org+rules pages, then UIG-07 simulator, UIG-10 org mutations
- [23:25] [B15-audit-metrics] resumed: inspected all owned files (AUD-01..16 code present, imports OK); finishing gaps (A-53 /api/selftest, A-54 seq_from, reports_dir, A-10 elision) then tests AUD-V01..V13
- [23:25] [B20-demo-stack] resumed: SDK+mocks/__init__+fakegen present; next mock_llm, exfil_sink, mock_saas, run_stack, preflight/reset, tests
- [23:25] [B19-dashboard-gov-policy] resumed: policy/* infra + mocks + toaster exist; writing budgets/ components + budgets.page, then policy rail components + policy.page
- [23:25] [B11-action-guards] resumed (agent 2): helpers (classify/argpath/rx/money/sql/shell/fs/net/catalog/explain/drafts/params/base) verified working; writing 9 controls + taint.py, snippet, tests
- [23:26] [B09-org-rbac] DONE ORG-01..14 (ORG-15 could skipped). Verified V01/V02/V12 ok, pytest org_rbac 89 pass ~9s, V13 test_integration (real create_app) pass, V14 selftest GOV rows pass/gate 0; added test_integration.py+test_keys.py; status docs/status/B09-org-rbac.md
- [23:26] [B02-gateway-proxy] GW-13 (budget-remaining fallback, Ollama up/down system toasts), GW-17 fresh_segments; tests openai/ollama/passthrough/telemetry + GW-V12 bench (p50 0.66 ms, p95 1.09 ms; 1 MB body p50 3.2 ms); 67/67 pass; V13 in-process w/ real app OK
- [23:27] [B05-metadata-egress] META-08 done (media/{jpeg,png,pdf,office}.py, blobs.py, metadata.py facade+CLI; DLP-03 media wired), META-05 tests (test_channels) pass; next META-06 /egress forwarder+route
- [23:27] [B01-gateway-core] tests added: test_pipeline (33, GW-V05), test_runtime (4, GW-V04), test_guard_playground (11), test_events_live (slow SSE) -> 76 pass in 5s; GW-V11 live smoke OK (33 controls, 23 routers, 0 fallbacks); ruff clean
- [23:27] [B02-gateway-proxy] DONE (except GW-16 could, GW-V14 manual): 67/67 tests ~6 s, ruff clean, V12 p50 0.66/p95 1.09 ms, V13 in-process real stack PASS; status docs/status/B02-gateway-proxy.md (integration_todos: mock_llm missing, B15 scrubber redacts 127.0.0.1 dest host)
- [23:27] [B14-threat-feed] TI-09 SIG-02 (aegis.feed.gate + samples + control, 13/13 samples ok), TI-13 SIG-03, TI-12 snippet (V11 ok) done; next tests (TI-11) then UI (TI-10)
- [23:28] [B01-gateway-core] DONE: GW-01..07, GW-11 complete; V01/V02/V03/V04/V05/V10/V11/V15 pass (76 tests); status in docs/status/B01-gateway-core.md; no deps needed; note healthz feed seed->degraded
- [23:28] [B07-semantic-models] FIX (orchestrator/B09): engine now honours env AEGIS_SEMANTIC=off / AEGIS_TEST_MODE=1 even when Settings(...) is built directly, and any pytest process defaults to test_mode (no background model warm-up; models load only via explicit warmup() or AEGIS_SEMANTIC=on|auto). Verified create_app: no onnxruntime/tokenizers import.
- [23:28] [B21-test-suite-harness] started: gateway boots in-process (1.3 s, 35 controls); landing tests/lib (servers, stack, fakes, client, cases, expect, matrix, report, plugin) first
- [23:28] [B23-demo-agents] started: SDK surface present; writing demo/agents/_common.py + trading_copilot.py + runaway.py (DEMO-06) first, then catalog/chaos, warmup/ambient, scenes
- [23:29] [B10-approvals-engine] DONE must+should (APR-01..13, 17); added test_gov05/api/privacy/integration/background; 141 passed incl. real-app F4+F5 e2e; ruff clean; could APR-14/15/16 not started; status docs/status/B10-approvals-engine.md
- [23:29] [B24-redteam-eval-perf] started: porting corpora (EVAL-01) then adapter/harness/eval/bench
- [23:29] [B13-claude-code] resumed: Addendum applied (deny prefix '[Aegis] <ID>: ', A-23 pending text, 600 s completion, tool_error, meta.cwd/client, X-Aegis-Decision-Id headers); GOV-06 control in integrations/claude_code/gov06.py + handler GOV-06 path; tests green; next: snippet, workspace, replay, run/demo scripts
- [23:29] [B22-test-suite-functional] started: B21 libs not yet present -> local fixtures (TODO(integration)); TEST-09/10/11 first
- [23:30] [B04-redaction-engine] resumed: RED-01..08 code verified working (F1 round trip ok); fixed A-42 fp purpose=audit, A-38 no own NER session, A-40 DLP-08 +mcp.call, placeholder numbering by first appearance; RED-09 snippet + RED-10 tests (98 pass, ruff clean). next: bench/metrics, status file
- [23:30] [B12-mcp-proxy] snippet config/snippets/mcp-proxy.yaml + tests/unit/mcp_proxy (FakeRuntime, 47 tests: F9 poison/rugpull/approve RBAC, F4 hold→approve, unknown server, smuggling, DLP write-back, hot reload, admin API, mock 9 servers) all pass in 2.2s; next: e2e script, ruff, status
- [23:31] [B04-redaction-engine] DONE: RED-01..18 done; V01-V11,V14 pass (104 tests, ruff clean), V03 P=R=1.0 leak 0 (reports/dlp-metrics.* written); V12/V15/V16 not run; V13 16KB p95 33.8ms > 15ms target under load. Status: docs/status/B04-redaction-engine.md
- [23:31] [B14-threat-feed] TI-11 tests: 71 pass (tests/unit/threat_feed: matchers/signing/service/manager/sig01/02/03); ruff check+format clean on owned paths. Next TI-10 UI, TI-14 demo CLI
- [23:32] [B08-budgets-ledger] DONE: 75 unit tests (V01-V09,V11,V12 pass; p95 0.35ms); fixed EXE-04 hook+MCP dedupe; F6 found stalling at 86% (soft downgrade) -> INTEGRATOR: add on_soft: warn to agent:chaos-agent@platform in config/policy.yaml (snippet fixed). V10/V13 live not run. Status: docs/status/B08-budgets-ledger.md
- [23:33] [B17-dashboard-security] UIX-03 drawer+decision page, UIX-05 live page, UIX-06 playground landed (typecheck clean); next threats/audit/coverage/mcp
- [23:33] [B16-dashboard-shell] resumed: UIS-07 app frame (AppShell/router PageFrame/LockedPage/NotFound/RouteError/SystemBanners/CommandPalette + GovernanceToaster mount per A-55), UIS-10/12 overview (components/shell/overview/*), UIS-13/14 system perf+health pages, posture per A-51 (/api/stats/posture authoritative). Next: lint, build, browser smoke.
- [23:34] [B06-injection-defense] INJ-01..INJ-04(task) done: segments/canary/explain/cascade/exemplars + controls inj01/inj02/inj04 written; test_normalize/signatures/inj01 green; next INJ-02/04 tests, snippet harness, corpus
- [23:34] [B25-docs-submission] started: reading CONTRACTS/plan 20/staging submission; DEMO-08 README+JUDGES first, then DEMO-09 submission kit
- [23:34] [B11-action-guards] ACT-01..14 controls implemented (all 9 real, + actions/taint.py, actions/commands.py), snippet config/snippets/action-guards.yaml, harness+test_scenarios 36/36 pass; next: snippet/corpus/adversarial tests, status file
- [23:43] [B05-metadata-egress] META-06 done: egress/{hostmap,forwarder}.py + POST /egress real route (403/402/429/502, approval envelope, complete once, response hop, X-Aegis-*); real-stack probe: DLP-01/DLP-04 block exfil.test, ACT-03 approval on CRM PII. META-12 perf (bisect overlaps, learned cache). 141 unit tests pass, ruff clean
- [23:45] [B13-claude-code] CC-08 workspace+reset.sh(--clean), CC-09 replay.py+11 fixtures, CC-14 snippet, GOV-06 tests, CC-V05 in-process real-app test: all 10 replay scenes match (EXE-01/EXE-02/GOV-03/INJ-01/GOV-06 deny/block, DLP note); next run.sh/demo.sh/check.sh/docs
- [23:46] [B25-docs-submission] DEMO-08 README.md + docs/JUDGES.md, DEMO-09 docs/demo-script.md + docs/submission/{README,HACKTRIBE(454 words incl. placeholders),VIDEO_60S}.md written; next DEMO-14 architecture/policy docs, DEMO-15 deck+build.py
- [23:46] [B05-metadata-egress] FINISHED: META-01..13 + 15 done (14/16 could not started); 142 unit tests pass, ruff clean, selftest DLP-03/04/06 pass; status docs/status/B05-metadata-egress.md (integration todos: policy.yaml legacy DLP-03 params/snippet merge, G1 header/body mutations on model path)
- [23:46] [B07-semantic-models] DONE: SEM-01..16 (SEM-17 partial). snippet config/snippets/semantic-models.yaml, scripts/fetch_models.sh (--verify ok), data/ Modelfiles+licences, 119 hermetic tests green + ruff clean, live V03 pass (1 model at a time, unloaded), degraded drill V06 pass, in-process /v1/guard V10 pass (off mode). Not run: V08 (needs snippet merge by policy-engine), V12 judge live (RAM). Status: docs/status/B07-semantic-models.md
- [23:46] [B03-policy-engine] orchestrator fix: config/policy.yaml (+golden, byte-identical) chaos-agent day limit now on_soft: warn (F6); validates 0/0, gate self-test 82/82, applies as owner. docs/seed-fixes/policy.yaml NOT updated (not owned) - same delta needed there. Also landed src/aegis/policy/snippets.py (POL-16 check/merge) + routes/policy.py.
- [23:48] [B05-metadata-egress] correction: unit test count is 127 (not 142), all passing
- [23:49] [B14-threat-feed] TI-10 feed editor UI done (feed_service/ui/{index.html,app.css,app.js}; + GET /api/demo/echoleak); V13 checked in browser on throwaway keys: 21 rows, TI-022 draft, enable+publish toast serial #2, Try-it EchoLeak BLOCK, tamper menu, no console errors. Next TI-14 demo CLI + status file
- [23:50] [B15-audit-metrics] done: AUD-01..16 + A-53 /api/selftest* + A-54 seq_from + A-10 elision + AUD-20-lite batching (record p50 0.3ms); tests/unit/audit_metrics 39 pass/1 bench skip, ruff clean; in-process create_app smoke OK (PESEL redact → decision+audit_seq, verify OK). Not done: AUD-17/18 (could), AUD-19 skipped (A-50). Status: docs/status/B15-audit-metrics.md
- [23:51] [B23-demo-agents] DEMO-06 done + live-verified on a private stack: trading_copilot pii-draft (7 redactions, scan 0, CVV dropped, rehydrated) + subscribe (ACT-01 spend-admin -> u_emily -> sub_ active); runaway F6 (EXE-04 ladder, BUD-01 budget_raise approval -> policy v+1 -> continues -> 429 killed). FOUND: chaos limit needs on_soft: warn else 80% downgrade->aegis-judge (Ollama) and the $0.50 wall is never reached. next DEMO-10 catalog/chaos
- [23:52] [B12-mcp-proxy] DONE: 50 unit tests pass (incl. real-app F9 + F4 hold→approve), e2e 17/17 (python -m mocks.mock_mcp.e2e), selftest 82/82, ruff clean; status docs/status/B12-mcp-proxy.md; todos: poisoned-stdio into config/policy.yaml (B03), EXE-02 vs mcp upstream URL (B11), run_stack starts mock_mcp + /api/mcp/reset preflight
- [23:53] [B20-demo-stack] DONE DEMO-01..05,07 (DEMO-19 could: not started). mock_llm/exfil_sink/mock_saas + run_stack + preflight + reset; 41 unit tests pass, V01-V06 pass, V07 partial (read-only preflight vs another agent's stack: READY degraded), V16 integration. Makefile lines in docs/status/B20-demo-stack.md integration_todos
- [23:54] [B19-dashboard-gov-policy] DONE: UIG-03/04/05/08/09/12/15 + kill-switch half of UIG-10 (budgets.page, policy.page, budgets/*, policy rail comps). typecheck clean, eslint 0 errors, V02 OK 5/5, V05 grep empty, Monaco+worker smoke OK in dev. UIG-14 skipped. Live V07-V09 + B16 npm run build pending → docs/status/B19-dashboard-gov-policy.md
- [23:54] [B03-policy-engine] orchestrator fix (B12): mcp.servers.poisoned-stdio added to config/policy.yaml (+golden byte-identical) from snippets/mcp-proxy.yaml; validates 0/0, gate self-test 82/82, governed apply ok. Next: finish unit tests + status.
- [23:54] [B17-dashboard-security] UIX-07 threats, UIX-08 audit(+ChainBlocks), UIX-09 coverage(+UIX-12 perf tab), UIX-10/11 MCP(+diff) landed; typecheck clean, eslint 0 errors; next node lib tests + status
- [23:55] [B06-injection-defense] INJ-05..INJ-11 done; snippet config/snippets/injection-defense.yaml (ok 4); tests/unit/injection_defense 108 passed incl. e2e /v1/guard; next lint + INJ-12/15 + status file
- [23:56] [B22-test-suite-functional] TEST-09 test_approvals_rbac.py (16: 14 pass, 2 xfail product gaps) + TEST-10 test_budgets_loops.py (9: 8 pass, 1 xfail BUD-01 soft downgrade) landed; local stack (tests.lib.servers + real mocks.mock_llm); next TEST-11 hot reload
- [23:56] [B21-test-suite-harness] TEST-01..08 landed: tests/conftest.py (contract fixtures + aegis_stack/gw/make_stack), tests/lib/* (stack on port 0, fakes, client, cases/macros/runner/expect, matrix/report/plugin, policy_sandbox, privacy), 263 cases in tests/cases/*.yaml; hermetic run ~38 s: 222 pass/13 other/18 xfail/7 fail (product gaps listed in status). next: feed fake + inline tests + unit tests
- [23:57] [B18-dashboard-gov-approvals] DONE: UIG-06 org+rules pages, UIG-07 route simulator, UIG-10 org mutations (governed role change → owner approval), UIG-11 store org routes, UIG-16 test_api_contract.py (5 passed live in-process). V01 clean, V02 OK 5/5, V04 mock walkthrough ok (Piotr locked/Emily approve/2p 1/2→2/2). V06/V07 live UI not run. Status: docs/status/B18-dashboard-gov-approvals.md
- [23:57] [B13-claude-code] DONE: CC-01..15,17,18 (CC-16 skipped: A-23 never ask). 89 unit tests pass; ruff clean; real-gateway replay 11/11 (HTTP + bash hook); CC-V11 approval flip verified; DLP-08 rehydration verified. Live claude -p (CC-V07..V10,V12,V13) left for integrator; status docs/status/B13-claude-code.md
- [23:57] [B25-docs-submission] DEMO-14 part: docs/architecture.md, docs/assets/architecture.{svg,png} (rsvg render checked), docs/policy-reference.md, docs/samples/policy-{strict-bank,budgets,approvals,local-only}.yaml (validate_text 0 errors, python -m aegis selftest all PASS); next docs/api.md, deck+build.py
- [23:57] [B23-demo-agents] DEMO-10 done: demo/agents/catalog.py (40 steps, 9 families, 4 approval kinds) + chaos_agent.py; live sweep --fast --no-config 35/35 (32 ok, 3 approx: pii-remote/md-exfil no control id on model-proxy redact, email-ext routed admin not self), config steps OK, exfil 0, pending cleaned. next DEMO-11 warmup/ambient
- [23:58] [B11-action-guards] DONE: ACT-01..16,19 done (17/18 partial, 20/21 not started); EXE-02 now exempts configured MCP upstreams + ignores interaction.url on mcp.* (B12 request, test added); pytest tests/unit/action_guards 165 pass/1 skip; ruff clean; aegis selftest 82/82. Status: docs/status/B11-action-guards.md
- [23:58] [B22-test-suite-functional] TEST-11 test_hot_reload.py 12 cases (11 pass, C5 xfail heuristic score 0); next TEST-12 hooks
- [23:59] [B14-threat-feed] DONE: TI-01..17 (TI-18 skipped). 71 unit tests pass, ruff clean; in-process F8 via real gateway: EchoLeak allow -> publish TI-022 -> BLOCK SIG-01 (serial 2, ~1.3s), unsigned tamper rejected, stays #2. Demo CLI: python -m aegis.feed.demo echoleak|check. Private key only in feed_service/state (gitignored). Status: docs/status/B14-threat-feed.md; integrator: merge snippet, run V14/V15 on fixed ports
- [23:59] [B06-injection-defense] DONE: INJ-01..12,15 (13/14 skipped, could). 112 tests pass (incl. e2e /v1/guard), ruff clean, policy selftest 82/82. Status: docs/status/B06-injection-defense.md. Integrator: merge snippet, render meta.inj
- [00:00] [B22-test-suite-functional] musts DONE: TEST-09/10/11/12 (test_hooks.py 11/11 pass). next TEST-14 MCP (fakes/mcp.py), TEST-15, TEST-16, TEST-19
- [00:01] [B23-demo-agents] DEMO-11 warmup.py done: --fast live = 59 interactions/5 s, all 5 colours, MCP inventory 9 servers, approvals $12 u_agnieszka / $50 u_emily+redeem / $480 denied u_katarzyna / team:platform raise u_marek, pending 0. next ambient.py, then DEMO-12 scenes
- [00:02] [B16-dashboard-shell] DONE: UIS-01..16 + 18/20 done (17 not started, 19 partial, 21 n/a). Final npm run build PASS (tsc clean, NO_CDN, dist 7.2MB), eslint 0 errors, pytest tests/unit/dashboard_shell 57 passed, smoke at 1536x864 mock + live (8787). GovernanceToaster mounted in AppShell; shell still toasts policy/approval/killswitch (shared sonner ids) — see docs/status/B16-dashboard-shell.md contract_deviations.
- [00:03] [B22-test-suite-functional] TEST-14 done: tests/lib/fakes/mcp.py (fallback fake, AEGIS_TEST_FAKE_MCP=1 forces it) + test_mcp.py 5/5 pass on real mock_mcp and on the fake
- [00:03] [B17-dashboard-security] DONE: UIX-01..15 done (+UIX-18 ChainBlocks); 7 pages under /security/*; tsc 0 errors, eslint 0 errors, node lib tests 10/10, mock scenarios checked in browser (5188). Not done: UIX-16/17, sig sparklines. Status: docs/status/B17-dashboard-security.md (integration_todos: confirm presets live, B16 HMR registry cycle)
- [00:04] [B22-test-suite-functional] TEST-15 test_audit_privacy.py 6/6 pass (chain verify, exports admin-only, 0 raw PESEL/PAN/AWS/email hits in data dir+exports+decisions, byte-flip detected); next TEST-16 errors
- [00:04] [B03-policy-engine] DONE musts+POL-12/13/14/16. tests/unit/policy_engine 38 passed, ruff clean, V02/V04/V09/V10 ok. Snippet merge: 'uv run --frozen python -m aegis.policy.snippets merge' (rehearsed: 16 snippets, 395 changes, 0 errors, merged policy 183/183 self-tests) - NOT run on live policy (integrator). Fixed self-test headers extra + profile-switch gate. Bugs for others: injection/canary.py:55 IndexError (INJ-04 degrades). Status: docs/status/B03-policy-engine.md
