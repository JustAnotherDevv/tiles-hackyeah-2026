# HackTribe submission: Aegis (Goldman Sachs · AI Control Layer)

> Paste only what sits **inside** the `text` blocks. Everything outside them is notes for the team.
> `docs/submission/build.py --check` counts words inside the marked description block
> (title ≤ 5 words, description ≤ 500 words **including the team lines**).
> `{{TBD: …}}` placeholders are replaced by `build.py render` from `docs/submission/numbers.json`
> (collected from `reports/`); the rendered copy is `docs/submission/out/HACKTRIBE.md`. Paste from `out/`.

## 0. Before you paste

- **Category:** Goldman Sachs: *AI Control Layer*.
- **Team block:** the repo copy names the team by GitHub handle only (`JustAnotherDevv`) so the public repo
  holds no personal data.
- **ACTION FOR YOU (not in the repo):** HackTribe itself requires the **first name, surname and email of every
  member** inside the description. When you paste into HackTribe, replace the `Team:` line with your real
  `First Surname — email` (1–6 members, one per line). Do **not** commit those details back here. Every member
  needs a Discord account before upload. The 500-word limit includes those lines.
- Re-run `uv run --frozen python docs/submission/build.py --check` after any edit.
- Tick the claims table in §2 against the running build; strike any claim that is not true on Sunday.

## 1. Title (≤ 5 words)

<!-- title:start -->
```text
Aegis: Local-First AI Guardrails
```
<!-- title:end -->

Alternates: "Aegis: AI Control Layer" (safest, mirrors the category) · "Aegis: Govern Every Agent Call".

## 2. Description (final submission, ≤ 500 words incl. team)

<!-- description:start -->
```text
Problem. Every agent call can leak customer data to a remote model, run a poisoned tool, burn budget in a loop, or take an action nobody approved.

Solution. Aegis is one lightweight local gateway on every hop: agent to model (Anthropic, OpenAI-compatible and Ollama APIs), agent to MCP tools, agent to third-party HTTP, and Claude Code's own tool calls. Each request passes one policy pipeline and ends in allow, redact, block, require approval or log.

Local-first redaction (headline). PII, payment cards, Polish IDs (PESEL, NIP, REGON, IBAN), secrets and metadata are detected on the device and replaced with reversible placeholders before anything leaves. Checksum validators keep false positives low; a multilingual NER model catches names. Real values are restored only for the local user. CVVs are dropped, never stored.

Goldman Sachs requirements:
1. Centralized policy: one YAML file (controls, block/redact thresholds, adherence %, allowed models, budgets, approval rules, four strictness profiles), hot-reloaded with validation, a self-test gate, atomic swap and last-known-good fallback.
2. Hybrid guardrails: deterministic detectors first (validators, secret patterns, command and SSRF guards, MCP tool pinning), then small local models (injection classifier, Qwen3Guard, NER).
3. Budgets: org, team, agent and session limits on tokens, USD and local compute-seconds; loop detection; downgrade to a local model; kill switch.
4. Historical attacks: a separate threat-intel service publishes Ed25519-signed signature bundles (malicious pickles, compromised packages, MCP tool poisoning, EchoLeak-style exfiltration) that the gateway verifies and hot-swaps; tampered or rolled-back bundles are refused.
5. Reporting: live management, security and performance dashboard; Prometheus metrics; hash-chained audit log with JSONL, CSV and OCSF export.
6. Self-testing: one command runs allowed and blocked cases for every control, including budgets, approvals and exploit replays.

Organization governance. Owners, admins, members, and agents as service identities. Approval rules route actions by type and amount: an agent's $12 purchase is confirmed by its sponsor, a $50 subscription goes to an admin, $480 to the owner, above $1,000 to the owner plus a second admin. Reading a PII table needs an admin, a production write the owner. Budget raises and disabling controls are governed too. Approvals are bound to exact parameters, expire and are audited.

Claude Code. Model traffic via ANTHROPIC_BASE_URL, tool calls via a fail-closed PreToolUse hook, MCP servers via our proxy, all from one demo settings profile with no machine-wide changes.

Tech. Python 3.13, FastAPI, SQLite, RE2, ONNX Runtime, Ollama; React dashboard. Runs offline on an 8 GB laptop; all models optional.

Measured on 1,234 labelled prompts (make eval): with the optional local models {{TBD: eval.detection_rate}} attack detection ({{TBD: eval.heldout_detection}} held-out) at {{TBD: eval.fpr}} false positives; deterministic only (default) {{TBD: eval.det_detection_rate}} at {{TBD: eval.det_fpr}}. make test: 2,006 tests pass. Overhead p50 {{TBD: perf.overhead_p50_ms}} ms.

How judges test it. Code: https://github.com/JustAnotherDevv/tiles-hackyeah-2026/tree/main/aegis. In aegis/: make setup, make up, open http://127.0.0.1:8787/ui, then make test. Try the Playground, edit config/policy.yaml and watch the next decision change, or publish a feed signature and replay the exploit. Guide: aegis/docs/JUDGES.md.

Team: JustAnotherDevv
```
<!-- description:end -->

### Claims to verify against the running build before the final paste

| Claim in the text | Must be true | Verified (initials, time) | If not, replace with |
|---|---|---|---|
| "Anthropic, OpenAI-compatible and Ollama APIs" | `/v1/messages`, `/v1/chat/completions`, `/ollama/*` proxies work | [ ] | name only the working adapters |
| "agent to third-party HTTP" | `POST /egress` works with `AEGIS_HOST_MAP` | [ ] | "HTTP tool calls" |
| "a multilingual NER model catches names" | DLP-07 runs the ONNX NER (`/healthz` semantic not degraded) | [ ] | delete the sentence |
| "injection classifier, Qwen3Guard, NER" | each model is called by the semantic tier | [ ] | name what is actually used |
| "Ed25519-signed … tampered or rolled-back bundles are refused" | Publish + Tamper demo works (F8) | [ ] | "versioned signature bundles" |
| "OCSF export" | `GET /api/audit/export?format=ocsf` returns OCSF JSON | [ ] | "JSONL and CSV export" |
| "$12 … $50 … $480 … above $1,000" | F4 routing works for all four (chaos agent / `make test`) | [ ] | keep only the verified amounts |
| "Approvals … expire" | TTL enforced (`approvals.defaults.ttl_s`) | [ ] | drop "expire" |
| "downgrade to a local model" | BUD-01 soft limit downgrades (F6) | [ ] | drop the phrase |
| "make up" | `scripts/run_stack.py` starts gateway, feed and mocks | [ ] | "make gateway" |

## 3. Checkpoint text (~150 words; Saturday checkpoint)

<!-- checkpoint:start -->
```text
Aegis is a local-first AI control layer. One lightweight gateway sits between agents and everything they touch (remote and local models, MCP tools, third-party APIs, Claude Code's tool calls) and allows, redacts, blocks or holds each request for approval.

Headline: customer data never leaves in clear text. PII, payment cards, Polish IDs, secrets and metadata become reversible placeholders on the device before egress and are restored only for the local user.

Plus: hybrid deterministic and local-AI guardrails mapped to OWASP; hierarchical budgets with loop detection; org roles with approval routing; a signed threat feed of historical AI exploits; a live dashboard with hash-chained audit export; and a one-command self-test suite. Runs offline on Ollama.

Team: JustAnotherDevv
```
<!-- checkpoint:end -->

## 4. Other fields

### Image gallery (≥ 1 required; upload 4–5)

Capture at 1920×1080, dark theme, zoom 110–125 %, real demo data in view (after `make demo` warm-up), no
empty states. Files go to `docs/assets/screens/`. The architecture image is ready now:
`docs/assets/architecture.svg` (export a PNG with `rsvg-convert -w 1920 docs/assets/architecture.svg -o docs/assets/architecture.png`).

| # | Screenshot | Caption |
|---|---|---|
| 1 | Overview / Live feed with mixed allow, redact, block rows and KPI tiles | "Live decision feed: every model, tool and MCP call, with the control that fired" |
| 2 | Decision drawer **Wire** tab: original vs what the remote model received | "Local-first redaction: the remote model only ever sees placeholders" |
| 3 | Approvals inbox as u_piotr (Approve locked, "needs admin") with the $50 MarketPulse card | "Org approvals routed by role, action type and amount" |
| 4 | Policy page with the "Policy vN applied" toast and the diff | "Edit the policy live: validated, self-tested and swapped in about a second" |
| 5 | Terminal with the `make test` per-control matrix | "One-command self-test: allowed and blocked cases for every control" |

### Presentation

`docs/submission/out/Aegis_HackYeah2026_GS_AIControlLayer.pdf` (10 slides, English), built by
`uv run --frozen python docs/submission/build.py collect render --pdf`. Source: [DECK.md](DECK.md),
`deck/deck.html`.

### Video URL

The ≤ 60 s cut from [VIDEO_60S.md](VIDEO_60S.md), YouTube **Unlisted**; check it plays in a logged-out window.

### Repository URL

```text
https://github.com/JustAnotherDevv/tiles-hackyeah-2026
```

Monorepo: Aegis lives in the `aegis/` folder (direct link:
https://github.com/JustAnotherDevv/tiles-hackyeah-2026/tree/main/aegis); the repo root is the separate
HarmonyOS submission. If HackTribe accepts a folder link, paste the direct link instead.

Before pasting: repo public; README one-command start works from a clean clone; `reports/` holds the final
`make test` results; no secrets in history (run `gitleaks detect` once; see HANDOFF known issues).

### Opening instructions (paste)

<!-- opening:start -->
```text
Requirements: macOS or Linux, uv (installs Python 3.13), Node 20.19+ or 22.12+ to build the dashboard. Models are optional: without them the demo runs deterministic-only (the default); make models + Ollama add the semantic controls.
1. git clone https://github.com/JustAnotherDevv/tiles-hackyeah-2026 && cd tiles-hackyeah-2026/aegis
2. make setup && make web && make up     # gateway :8787, threat feed :8790, mocks :8791-8794
3. Open http://127.0.0.1:8787/ui and use the view-as switcher (owner u_katarzyna / admin u_emily / member u_piotr)
4. make test                             # deterministic suite, no model needed (2,006 tests + 1,045-case control matrix)
5. Try to break it: Playground page; edit config/policy.yaml and resend; publish a signature in the feed editor at http://127.0.0.1:8790. Full guide: aegis/docs/JUDGES.md
Optional: make claude (Claude Code routed through Aegis with a demo settings profile; nothing machine-wide)
```
<!-- opening:end -->

### Demo link

Leave empty (no hosted instance; never expose the gateway publicly).
