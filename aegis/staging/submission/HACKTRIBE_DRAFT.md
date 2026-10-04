# HackTribe submission draft: Aegis (Goldman Sachs · AI Control Layer)

> **Use:** tonight's checkpoint (Sat 3 Oct, **20:00**) needs §1 + §3 pasted into a draft project.
> The final submission (Sun 4 Oct, **11:00 CEST** hard deadline; aim for 10:00) uses §1 + §2 + §4.
> Paste only what sits **inside** the `text` blocks. Everything outside them is notes for the team.

---

## 0. Before you paste (2 minutes)

- **Category:** Goldman Sachs: *AI Control Layer*.
- **Team block:** HackTribe requires the **first name, surname and email of every member** inside the description (FAQ › Uploading Q8). Replace every `[NAME SURNAME n]` / `[EMAIL n]`. Delete unused lines; the team can have 1 to 6 members.
- **Discord:** every member needs a Discord account before upload (FAQ › Uploading Q1).
- **Word budget:** the full description body is **471 words** (`wc -w`). With 6 real members at about 4 words each ("Jan Kowalski – jan@x.pl"), the total is about **496 words**, still under 500. **Re-run `wc -w` after any edit.**
- **Assumed names.** These match the research docs. If the repo ends up different, search and replace them in all five submission files:

| Assumed in these docs | Meaning | Confirm with |
|---|---|---|
| `make run` | start gateway, feed service, mocks and dashboard | repo Makefile |
| `make test` | hermetic self-test suite (deterministic; semantic cases auto-skip if Ollama is down) | tests track |
| `make test-live` / `make bench` | suite against the running policy / performance run | tests track |
| `policies/catalog.yaml` | the single policy file judges edit | policy track |
| `http://127.0.0.1:8787/ui` | dashboard (gateway on 8787; feed service on 8790; mocks on 8791–8799) | BRIEF |

---

## 1. Project title (≤ 5 words, English)

| # | Title | Word count | Notes |
|---|---|---|---|
| **1 (recommended)** | **Aegis: Local-First AI Guardrails** | 4 (5 even if "Local-First" counts as two) | Leads with the differentiator. Every entry in this category is some kind of "AI control layer", so this one stands out in the list. |
| 2 | Aegis: AI Control Layer | 4 | The safest option. It mirrors the category name exactly but is less memorable. |
| 3 | Aegis: Govern Every Agent Call | 5 | Use this if the pitch ends up leaning on governance and approvals more than on redaction. |

```text
Aegis: Local-First AI Guardrails
```

---

## 2. Full description (final submission): ≤ 500 words including the team

```text
Problem. Banks want coding and business agents, but every agent call can leak customer data to a remote model, run a poisoned tool, burn budget in a loop, or take an action nobody approved. Controls today are scattered or missing.

Solution. Aegis is one lightweight gateway on every hop: agent↔model (Anthropic, OpenAI-compatible and Ollama APIs), agent↔MCP tools, agent↔third-party HTTP, and Claude Code's own tool calls. Each request passes one policy pipeline and gets a decision aligned with the OWASP Agent Control Standard v0.1.0: allow, redact, block, require approval or log.

Local-first redaction (headline). PII, payment cards, Polish IDs (PESEL, NIP, REGON, IBAN), secrets and metadata (paths, hostnames, headers) are detected on the device and replaced with reversible placeholders before anything leaves. Checksum validators keep false positives low; a multilingual NER model catches names and addresses. Real values are restored only for the local user. CVVs are dropped, never stored.

Goldman requirements:
1. Centralized policy: one YAML catalog (controls, block/redact thresholds, adherence %, allowed models, budgets), hot-reloaded with validation, self-test, atomic swap and last-known-good fallback.
2. Hybrid guardrails: deterministic detectors first (validators, secret patterns, command and SSRF guards, MCP tool pinning), then local AI (injection classifier, Qwen3Guard, NER).
3. Budgets: org → team → agent → session limits on tokens, USD and local compute-seconds; loop detection; downgrade to a local model; kill switch.
4. Historical attacks: an external threat-intel service publishes Ed25519-signed signature bundles (malicious pickles, Ollama and Langflow RCE, MCP tool poisoning, EchoLeak-style exfiltration) that the gateway verifies and hot-swaps.
5. Reporting: live management, security and performance dashboard; Prometheus metrics; hash-chained audit log with JSONL, CSV and OCSF export.
6. Self-testing: one command runs allowed and blocked cases for every control, including budgets, approvals and exploit replays.

Organization governance. Owners, admins, members, and agents as service identities. Approval policies route actions by type and amount: a $15 agent purchase is self-approved, $50 goes to an admin, $500 to an owner; reading a PII table needs an admin, writing to production an owner. Config changes, such as raising a budget or disabling a control, need approval too. Approvals are bound to exact parameters, expire, and are audited.

OWASP. Every control carries OWASP LLM Top 10 2026, Agentic ASI01–ASI10 and MCP Top 10 IDs; the coverage view updates live when a control is switched off.

Claude Code. Model traffic goes through ANTHROPIC_BASE_URL, tool calls through a fail-closed PreToolUse hook, MCP servers through our proxy, all from one `claude --settings` profile with no machine-wide changes.

Tech. Python 3.13, FastAPI, SQLite, RE2, ONNX Runtime, Ollama; React/TypeScript dashboard. Runs fully offline on an 8 GB laptop; remote models optional.

How judges test it. Run `make run`, open http://127.0.0.1:8787/ui, then `make test`. Type anything into the Playground, edit `policies/catalog.yaml` and watch the next decision change within a second, or publish a feed signature and replay the exploit.

Team:
[NAME SURNAME 1] – [EMAIL 1]
[NAME SURNAME 2] – [EMAIL 2]
[NAME SURNAME 3] – [EMAIL 3]
[NAME SURNAME 4] – [EMAIL 4]
```

### Claims to verify against the running build before the final paste

Each sentence above is a promise that judges can test. Strike or soften any claim that isn't true by Sunday 10:00.

| Claim in the text | Must be true | If it isn't, replace it with |
|---|---|---|
| "Anthropic, OpenAI-compatible and Ollama APIs" | All three ingress adapters work | Name only the adapters that work |
| "agent↔third-party HTTP" | Egress HTTP proxy, or tool-argument scanning on HTTP tools | "HTTP tool calls" |
| "multilingual NER model" | `bardsai/eu-pii-anonimization-multilang` ONNX loaded (otherwise deterministic only) | Delete that sentence |
| "Qwen3Guard" / "injection classifier" | Each model is actually called in the semantic tier | Name the model that is actually used |
| "Ed25519-signed … hot-swaps" | Feed service signs, gateway verifies, tamper is rejected | "versioned signature bundles" |
| "OCSF export" | The export endpoint returns OCSF-shaped JSON | "JSONL and CSV export" |
| "approvals … expire" | Approval TTL is enforced | Drop "expire" |
| "within a second" | Measured reload propagation p95 < 1 s | The measured number |
| "MCP tool pinning" | Rug-pull hash check works on `tools/list` | "MCP tool-description scanning" |
| OWASP IDs | Check the 2026 LLM Top 10 names against the official PDF (research 01 §11: only "Excessive Agency is #3" is confirmed first-hand) | Keep the year suffix (`LLM01:2026`) everywhere |

---

## 3. Checkpoint version (tonight, 20:00): about 150 words

The body is 122 words; with 4 members the total is about 140.

```text
Aegis is a local-first AI control layer. One lightweight gateway sits between agents and everything they touch (remote and local models, MCP tools, third-party APIs, Claude Code's tool calls) and allows, redacts, blocks or holds each request for approval.

Headline: customer data never leaves in clear text. PII, payment cards, Polish IDs, secrets and metadata become reversible placeholders on the device before egress and are restored only for the local user.

Plus: hybrid deterministic and local-AI guardrails mapped to OWASP; hierarchical budgets with loop detection; org roles with approval routing; a signed threat feed of historical AI exploits; a live dashboard with hash-chained audit export; and a one-command self-test suite. Runs offline on Ollama.

Status: gateway, redaction engine and dashboard in progress.

Team:
[NAME SURNAME 1] – [EMAIL 1]
[NAME SURNAME 2] – [EMAIL 2]
[NAME SURNAME 3] – [EMAIL 3]
[NAME SURNAME 4] – [EMAIL 4]
```

**The checkpoint form also needs ≥ 1 image and a PDF.** If neither exists yet:
- **Image:** a screenshot of the architecture diagram, rendered from `ARCHITECTURE_DIAGRAM.md` (mermaid.live → PNG).
- **PDF:** a one-page export of the title slide from `PITCH_DECK.md`.

Drafts stay editable until the deadline (FAQ › Tasks Q10).

---

## 4. Other HackTribe fields (final submission)

### Image gallery (≥ 1 required; upload 4 or 5)

Capture at 1920×1080, dark theme, browser zoom 110–125%, with real demo data in view and no empty states.

| # | Screenshot | Caption to use |
|---|---|---|
| 1 | Dashboard live feed during the demo: mixed allow, redact and block rows plus the KPI tiles | "Live decision feed: every model, tool and MCP call, with the control that fired" |
| 2 | **Wire view**: original prompt on the left, what the remote model received (placeholders) on the right | "Local-first redaction: the remote model only ever sees placeholders" |
| 3 | Approvals inbox in "view as admin", with a pending $50 purchase and a budget-raise request marked "requires owner" | "Org approvals routed by role, action type and amount" |
| 4 | Policy editor (Monaco) with the "Policy vN applied in 0.xx s" toast and the diff | "Edit the policy live: validated, self-tested and swapped in under a second" |
| 5 | Terminal showing the `make test` matrix (per-control pass counts) | "One-command self-test: allowed and blocked cases for every control" |

### Presentation
The PDF from `PITCH_DECK.md`, 10 slides, English.

### Video URL
The ≤ 60 s English cut from `VIDEO_60S.md`, uploaded to YouTube as **Unlisted** (not Private). Before pasting the link, check that it plays in a logged-out browser.

### Repository URL
```text
[PUBLIC REPO URL]
```
Before pasting: the repo is **public**; the README has a one-command start; `reports/` holds the committed results of the final `make test` run; and there are no secrets in history (run `gitleaks detect` once).

### How to open the project (paste into "opening instructions")
```text
Requirements: macOS or Linux, Python 3.13 via uv, optional Ollama for semantic controls (Node 20+ only to rebuild the dashboard).
1. git clone [PUBLIC REPO URL] && cd aegis
2. make setup && make run        # gateway :8787, threat feed :8790, mocks :8791-8799
3. Open http://127.0.0.1:8787/ui (use the "view as" switcher: owner / admin / member)
4. make test                     # deterministic suite, no model needed; semantic cases run if Ollama is up
5. Try to break it: Playground tab, or edit policies/catalog.yaml and resend; see JUDGES.md for 10 one-click attacks.
Optional Claude Code: claude --settings demo/claude-settings.json  (routes model, tools and MCP through Aegis)
```

### Demo link
Leave empty unless a hosted read-only dashboard exists. Never expose the gateway publicly with real keys.
