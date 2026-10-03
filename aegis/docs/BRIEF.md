# Aegis — AI Control Layer (HackYeah 2026 · Goldman Sachs task)

Shared brief for every planning and implementation agent. Read this first.

## Event constraints
- HackYeah 2026, Kraków. Coding started Sat 3 Oct 11:00. Checkpoint draft due Sat 20:00. **Final submission Sun 4 Oct ~11:00** (plan for 10:00).
- This is a **hackathon demo**: it must **look polished and impressive** and the headline flows must work end-to-end live. Not every edge feature needs to be production-complete — stub or simulate the long tail convincingly, but never fake the core demo flows (redaction, blocking, budgets, approvals, live policy edit).
- Machine: Apple Silicon Mac, **8 GB RAM** (already under memory pressure), macOS 27. No Docker. Keep running processes lean.
- Submission: English, public repo, ≤10-slide PDF, ≤60 s video, ≤500-word description.

## The Goldman Sachs brief (condensed)
Build a lightweight, flexible **AI Control Layer** (gateway / proxy / middleware / SDK wrapper) that intercepts and governs interactions with agentic AI systems (agent↔model, agent↔MCP, agent↔agent, app↔agent).
Formal requirements:
1. **Centralized policy engine** — one config source: controls, sensitivity thresholds (block vs redact, adherence %), allowed models, resource/financial budgets.
2. **Hybrid guardrails** — deterministic (PII/secrets patterns, authn/authz) + semantic (AI-based) controls.
3. **Budget & resource governance** — token spend, compute time, resource access; for commercial APIs AND local models; runaway agent loops.
4. **Historical attack mitigation** — detect/block patterns of known exploits on AI systems (malicious code exec, unsafe deserialization, model-repo supply chain) via **signatures fed from an externally managed system**.
5. **Security reporting & auditing** — real-time metrics (blocked interactions, budget usage) for management; exportable audit logs for security teams; dashboard.
6. **Self-testing suite** — automated positive (allowed) and negative (blocked/redacted) tests incl. budgets and exploit mitigation.
Deliverables: the layer + simple architecture diagram; documented sample policy file (strictness levels, budget rules); simple interactive dashboard; executable test suite.
**Judging:** judges run our test suite; type spontaneous ad-hoc prompts live; **edit config/feeds live** (remove controls, change thresholds) and watch real-time adaptation; may look at performance telemetry; review architecture, dashboards, logs.
Criteria: guardrail robustness & quality 30% · architecture & performance 20% · security reporting 20% · self-testing suite 15% · practical implementability & scalability 15% (rules PDF says tests 20 / implementability 10 — treat both as important). Need ≥50% score to be prize-eligible.
No paid API keys provided → must run fully on local models + OSS; remote providers optional when keys exist.

## Product vision (from the team)
1. **Guard everything**: every model call, tool call, MCP call and third-party HTTP egress passes the policy pipeline → decision: allow / redact / block / require-approval / log.
2. **Local data minimization (headline)**: PII, payment cards, Polish IDs (PESEL/NIP/REGON/IBAN), secrets and **metadata** are stripped/tokenized **locally before anything leaves** for an AI agent, remote model or third-party service; reversible placeholders restored only in responses back to the local user.
3. **Token/cost budgets**: hierarchical (org → team → member/agent → session), local models priced by compute-seconds, loop detection, model downgrade, kill switch.
4. **Organization governance (NEW, important for the demo)**: organizations with **members and roles** (owner / admin / member, plus agents as service identities). **Approval policies** define who can approve what:
   - some approvals can be given by the member themself, some only by admins, some only by owners;
   - **config changes**, e.g. raising a team's daily/monthly budget, disabling a control, adding an allowed model → need admin or owner approval depending on scope/size;
   - **individual agent actions**, e.g. "agent wants to spend $50 on a subscription", "agent wants to read the customers table in the DB", "agent wants to send data to a third-party API" → approval routed to the right role by action type and amount thresholds (e.g. ≤$20 self-approve, ≤$200 admin, >$200 owner; PII-table DB access → admin; production DB write → owner), with expiry, audit trail, optional two-person rule.
   - Demo auth is a **"view as" role switcher** in the dashboard (no real login needed).
5. **Works with local AND remote agents/models** (Ollama locally; Anthropic/OpenAI/OpenRouter/etc. if keys exist) and **integrates with Claude Code** (route its model traffic via `ANTHROPIC_BASE_URL`, govern its tool calls via a fail-closed `PreToolUse` hook, route MCP through our proxy, demo settings profile via `claude --settings` — never install machine-wide managed settings).
6. **Fancy web dashboard**: dark, modern, animated; live decision feed; management + security + org/approvals + policy editor views.

## Fixed technical decisions (do not re-litigate)
- Repo: this folder `aegis/` (own git repo). Name **Aegis** (placeholder brand).
- Backend: **Python 3.13** (uv-managed venv; system Python 3.14 lacks some wheels), **FastAPI + uvicorn + httpx + pydantic v2**, `sse-starlette` for live events, `watchfiles` for hot reload, **SQLite** (stdlib `sqlite3` or SQLModel) for org/members/approvals/budgets/audit index, **hash-chained JSONL** audit log, `prometheus_client`, `google-re2` for user/feed regexes, **Presidio + spaCy small models (en + pl)**, `onnxruntime` + `tokenizers` for small classifiers, **Ollama** (local) for Qwen3Guard-0.6B / a small judge model, `PyNaCl`/ed25519 for feed signing.
- Frontend: **Vite + React + TypeScript + Tailwind + shadcn/ui + Recharts + Monaco editor + framer-motion**; built static and served by the gateway at `/ui` (Vite dev server on 5173 during development).
- Ports: gateway **8787** (API + `/ui`), threat-intel feed service **8790**, mocks **8791–8799**, Ollama 11434.
- Policy: single YAML control catalog with hot reload → validate → self-test → atomic swap → last-known-good; every decision stamped with policy + feed version.
- **Redaction updates (from research 07, overrides above where they conflict):** for NER prefer `bardsai/eu-pii-anonimization-multilang` (Apache-2.0, 24 EU languages incl. Polish, INT8 ONNX ~279 MB, onnxruntime, no torch); Presidio optional; **Polish spaCy models are GPL-3.0 — don't depend on them**. Under PCI, **CVV/track data must be dropped, never tokenized**; card display only first6/last4. Audit stores keyed HMAC fingerprints, never plain hashes of PANs/PESELs. NIP/REGON/ID-card checksums need context words (≈10% random strings pass). Research 07 assumes a Go gateway — reuse its Python prototypes and design, in Python.
- Implementation agents work **in the same working tree** with **strict file ownership** (see CONTRACTS.md); they must not edit files owned by others, must not change dependency manifests (request deps in their report), and must not run git commands.

## Research (read the parts relevant to you)
In `../research/goldman/` (relative to this file's parent repo, i.e. `/Users/nevvdevv/Development/hackathons/_october_2026/hackyeah/research/goldman/`):
- `01-threat-model-controls.md` — OWASP LLM 2026 / Agentic ASI01–10 / MCP Top 10 / Agent Control Standard; 32 controls + MVP bundles with test cases.
- `02-architecture-claude-code.md` — interception points, Claude Code gateway/hooks/MCP/managed settings details, streaming, policy hot reload (note: it proposed Go; we chose Python — reuse the design, not the language).
- `03-building-blocks-models.md` — OSS to reuse, model shortlist with RAM/latency/licences, fail-open/closed design.
- `04-budgets-feeds-reporting.md` — budget ledger, 19 historical attack signatures, signed feed format, metrics/audit/OCSF schemas.
- `05-tests-redteam-demo.md` — test-suite layout, corpora + licences, 4:30 demo script, judge-proofing tactics.
- `06-rules-and-huawei-integration.md` — HackYeah rules (deadline, HackTribe submission fields).
- `07-redaction-engine.md` — redaction engine design (may still be in progress; if missing, rely on 01/02/03).
