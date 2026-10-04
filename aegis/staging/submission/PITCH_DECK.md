# Pitch deck: Aegis (10 slides, English, PDF)

> **Limits:** HackTribe allows at most 10 slides, in English, as a PDF (FAQ › Uploading Q8; GS rules pt 5e). Phase 1 judges read the deck **without us in the room**, so every slide has to make sense with no narration. The speaker notes are for the finalist pitch (Sun 16:00, one presenter).
> **Look:** dark background matching the dashboard (`#0B0F17`-ish), one accent colour for "allow" (green), one for "redact" (amber) and one for "block" (red), used the same way on every slide. Use one idea per slide, a headline of at most 8 words, and real screenshots over illustrations. Use 16:9 at 1920×1080.
> **Placeholders** in `[BRACKETS]` must be filled from real runs (`make test`, `make bench`) before export. **Never ship a number that wasn't measured.** If a measurement is missing, show the target and label it "target".

---

## Criteria → slide map

Weights come from the GS CRITERIA brief §8 (30/20/20/15/15). The RULES PDF says tests 20 / implementability 10, so treat both as heavy.

| Criterion | Weight | Primary slides | Supporting slides |
|---|---|---|---|
| Guardrail robustness & quality | 30 | 4 (local redaction), 5 (hybrid guardrails + OWASP) | 2, 7, 9 |
| Architecture & performance | 20 | 3 (architecture), 9 (perf numbers) | 7 |
| Security reporting & auditing | 20 | 8 (dashboard + audit) | 6, 9 |
| Self-testing suite | 15–20 | 9 (test matrix) | 7 (rules carry their own tests) |
| Practical implementability & scalability | 10–15 | 10 (production path + compliance) | 3, 6 |

Every one of the brief's six formal requirements appears on at least one slide. The checklist at the bottom of this file maps them.

---

## Slide 1: Cover

**Title on slide:** Aegis
**Subtitle:** Local-first guardrails for every agent call

**Copy:**
- Redact locally · Govern centrally · Prove continuously
- Goldman Sachs · AI Control Layer · HackYeah 2026
- [TEAM NAME] · [Member 1] · [Member 2] · [Member 3] · [Member 4]
- QR code → [PUBLIC REPO URL]

**Visual:** A full-bleed dashboard screenshot (live feed) at 30% opacity behind the title. Small shield logomark.

**Speaker notes (10 s):** "We're [team]. Aegis is a control layer that sits on every call an AI agent makes. It redacts customer data locally before anything leaves, it governs spend and actions by role, and it proves all of it with tests and an audit trail."

---

## Slide 2: The problem

**Title on slide:** Agents leak, loop and overreach

**Copy:**
- **Leak:** prompts, files and tool results carry PESELs, IBANs, card numbers and secrets straight to remote models and third-party MCP servers.
- **Get hijacked:** a poisoned README, web page or MCP tool description can redirect the agent (OWASP ASI01 Agent Goal Hijack).
- **Loop:** one runaway agent burns tokens or local GPU time. Framework step limits are per framework, not per organization (LLM06:2026 Unbounded Consumption).
- **Overreach:** agents buy, write to production or email externally with no human approval (LLM03:2026 Excessive Agency).
- **Can't prove it:** security teams get no per-decision audit trail; management gets no spend view.

**Visual:** Four icons in a row (leak / hijack / loop / overreach), each with one real 2025–26 incident in small type:
- EchoLeak (CVE-2025-32711, zero-click Copilot exfiltration)
- postmark-mcp 1.0.16 (BCC'd all mail)
- LiteLLM 1.82.7–1.82.8 PyPI backdoor
- MCP tool poisoning (Invariant Labs, 2025)

**Speaker notes (25 s):** "A bank wants agents, but each agent call is a data-egress event, an execution event and a spend event at the same time. These are not hypothetical. EchoLeak exfiltrated data through a markdown image. An npm MCP server quietly BCC'd every email. LiteLLM, itself a gateway, was backdoored. Today the controls live inside each framework, if they exist at all."

---

## Slide 3: Architecture (one control layer, every hop)

**Title on slide:** One policy decision point for every hop

**Copy:**
- **Interception:** agent↔model (Anthropic `/v1/messages`, OpenAI-compatible, Ollama), agent↔MCP (proxy), agent↔HTTP (egress), and Claude Code tool calls (`PreToolUse` hook).
- **Pipeline:** identify → normalize → deterministic detectors → local AI detectors → policy → budget → approval → vault → upstream.
- **Decisions:** `allow · redact · block · require_approval · log` = OWASP Agent Control Standard v0.1.0 `allow · modify · deny · ask`.
- **Control plane:** one YAML catalog (hot reload) + an external **signed** threat feed + SQLite (org, approvals, budgets) + hash-chained audit.
- **Claude Code in one flag:** `claude --settings demo/claude-settings.json`. Model traffic, tools and MCP all go through Aegis, with no machine-wide install.

**Visual:** The simplified diagram from `ARCHITECTURE_DIAGRAM.md` §3: clients on the left, the Aegis box with the pipeline strip in the middle, T0/T1/T2 destinations on the right, a dashed "local machine trust boundary" round Aegis and T0, and the control plane underneath.

**Speaker notes (30 s):** "Aegis is a single gateway on localhost. Claude Code points its model traffic at us with `ANTHROPIC_BASE_URL`. Its tool calls go through a fail-closed `PreToolUse` hook, and its MCP servers through our proxy. Every hop runs the same pipeline, deterministic first and AI second, and ends in one of the standard dispositions from the OWASP Agent Control Standard. The policy and the threat feed are two separate control planes, and both are hot-reloaded."

---

## Slide 4: Headline: redact locally, before anything leaves

**Title on slide:** The remote model never sees the customer

**Copy:**
- Detected **on the device**: PII, PANs, Polish IDs (PESEL, NIP, REGON, IBAN), secrets, and metadata such as `/Users/<name>` paths, hostnames and `X-Forwarded-For`.
- **Validators, not bare regex:** Luhn + IIN, PESEL/NIP checksums, IBAN mod-97, context words. Order numbers don't trip the card rule.
- **Destination-aware:** the same prompt is allowed raw to local Ollama (T0), tokenized to a remote model (T1), and tokenized or blocked to a third party (T2).
- **Reversible placeholders** (`[PL_PESEL_1]`), stable per session, restored only for the local user and only for vault-issued tokens.
- **PCI handling:** CVV dropped, never vaulted. Display limited to first 6 / last 4. Audit stores HMAC fingerprints, never raw values.

**Visual:** A side-by-side **wire view** screenshot.
- Left, "What you typed": *"Draft a reply to Jan Kowalski, PESEL 44051401359, IBAN PL61 1090 1014 0000 0712 1981 2874, card 4111 1111 1111 1111"*.
- Right, "What the remote model received": `[PERSON_1] … [PL_PESEL_1] … [IBAN_1] … [PAN_1]`.
- Bottom strip: per-entity precision/recall and leak rate from the redaction fixture set: **leak rate [0.00]% on validated types**, **precision [x] / recall [y]**.

**Speaker notes (35 s):** "This is the headline. Data minimization happens before egress, on the laptop. We use checksum validators, not bare regex, so precision stays high, and NER catches names and addresses, Polish included. Placeholders stay stable for the whole session, so the model can still reason, and the real values come back only for the local user. Card verification codes are never stored at all. On our fixture set the leak rate for validated types is [0]%."

---

## Slide 5: Hybrid guardrails mapped to OWASP 2026

**Title on slide:** Deterministic first, AI second, every hop

**Copy:**
- **Tier D (µs to ms):** Unicode normalization (zero-width, tag characters, homoglyphs, base64), secrets patterns, command guard (`curl | sh`, reverse shells), SSRF guard (`169.254.169.254`), MCP tool-description scan + rug-pull pinning, exfil-link stripping.
- **Tier S (local models, escalation only):** prompt-injection classifier, Qwen3Guard content safety, multilingual NER. Each has a **per-control `fail_mode`**; model down = deterministic-only + `degraded` flag, never silent pass-through.
- **Screens untrusted content too:** tool results, MCP descriptions and fetched docs, not just the user prompt.
- **Coverage (live, from the catalog):** OWASP **LLM Top 10 2026** [x/10] · **Agentic ASI01–10** [x/10] · **MCP Top 10** [x/10].

**Visual:**
- Left: a cascade funnel (Tier D → Tier S → policy), with latency labels.
- Right: a coverage heatmap screenshot from the dashboard (OWASP IDs × controls), with one column greyed out to show "control disabled".

**Speaker notes (30 s):** "Most teams only screen the user prompt. Judges will attack the gaps: a tool result, an MCP description, a base64 payload. We normalize first, then screen every hop, and we put an independent control on the exfiltration leg, so a missed injection still can't leak data. Authorization never depends on the model's judgement. That's the OWASP 2026 guidance for Excessive Agency."

---

## Slide 6: Budgets and org approvals

**Title on slide:** Spend and actions follow your org chart

**Copy:**
- **Hierarchical budgets:** org → team → agent → session. Every level must pass. Dimensions: tokens, USD, **local compute-seconds** (Ollama gets a shadow price).
- **Runaway agents:** exact-repeat and cycle detection, then a graduated response: tool error → block → kill switch. Soft limit → downgrade to a local model.
- **Roles:** owner · admin · member · agent (service identity).
- **Approval policies** by action type and amount:

| Action | Approver |
|---|---|
| Agent purchase ≤ $20 | self |
| ≤ $200 | admin |
| > $200 | owner |
| Read PII table | admin |
| Production DB write | owner |
| Raise team budget / disable a control | admin or owner, by scope |

- Approvals are bound to exact parameters, expire, support an optional **two-person rule**, and are audited.

**Visual:** Approvals inbox screenshot with the "view as" switcher open (member / admin / owner). One request shows "Requires owner" with the approve button disabled for the admin.

**Speaker notes (30 s):** "Budgets are hierarchical and include local GPU time, because on an 8 GB laptop compute is the scarce resource. The new part is governance. Every risky agent action and every config change is routed to the right role by type and amount. An admin can approve a $50 subscription, but raising the team's monthly budget needs the owner. Each approval is tied to the exact parameters, so the agent can't swap the amount afterwards."

---

## Slide 7: Policy as code and a signed threat feed

**Title on slide:** Edit it live and it stays safe

**Copy:**
- **One YAML catalog:** controls, `mode` (enforce/monitor/off), `action`, `threshold`, `adherence_pct`, allowed models, budgets, approval rules, and strictness profiles (permissive / balanced / strict / paranoid).
- **Reload pipeline:** file save → schema validate → RE2 compile → **self-test gate (each rule's own `tests:`)** → atomic swap → `policy_version` stamped on every decision. Bad YAML is rejected and the last-known-good version keeps serving.
- **External threat feed** (separate service on :8790): an Ed25519-signed, monotonically versioned bundle; anti-rollback; inline test vectors. Seeds include malicious pickle, nullifAI, Probllama, Langflow RCE, the mcp-remote OAuth injection, MCP tool poisoning, EchoLeak and compromised packages.
- **Measured:** reload propagation p95 **[x] ms** · feed activation **[x] s** · tampered bundle → rejected.

**Visual:** A three-frame strip.
1. A Monaco editor with `threshold: 0.90 → 0.50`.
2. The toast "Policy v15 applied in [0.21] s".
3. The same prompt now **blocked**, with the control ID.

A small "feed v1 → v2, signature verified" badge sits underneath.

**Speaker notes (30 s):** "The brief says judges will edit config and feeds live, so we built for that. Every edit is validated and self-tested before it goes live. If it fails, the old policy keeps running and you see exactly why. The threat feed comes from a separate service and is signed. The gateway only holds the public key, so a tampered or rolled-back feed is refused."

---

## Slide 8: Security reporting and audit

**Title on slide:** Every decision explained, chained and exportable

**Copy:**
- **Management view:** spend vs budget by team, blocked interactions, cost avoided, local vs cloud share, burn forecast.
- **Security view:** live decision stream (control, rule, score vs threshold, redacted evidence, policy and feed version), signature hits, approvals queue, kill switch.
- **Performance view:** per-control p50/p95 latency and gateway overhead vs upstream.
- **Audit:** append-only JSONL, **hash-chained** (`verify` → "chain OK, [N] records"), redacted at write time. Export as JSONL, CSV or **OCSF** (Detection Finding 2004, API Activity 6003) for a SIEM. Prometheus `/metrics`.
- **Explainable responses:** `X-Aegis-Decision`, `X-Aegis-Trace-Id`, `X-Policy-Version` and `Server-Timing` headers on every reply.

**Visual:** A three-panel collage of the Management / Security / Performance tabs. Callout on an audit record JSON with `prev_hash` / `hash` highlighted.

**Speaker notes (25 s):** "Management sees money. Security sees every decision and why it was made, down to the control, the score and the policy version. The audit log is hash-chained and redacted at write time, so it never becomes a second copy of the customer data, and it exports as OCSF so it drops straight into a SIEM."

---

## Slide 9: Proof: tests and performance

**Title on slide:** One command proves every control

**Copy:**
- `make test`: **[N] cases · [N] pass · [x] xfail (stretch) · 0 fail · [x] s**. Runs with no model needed; semantic cases run when Ollama is up and are skipped (never silently passed) when it's down.
- **Per-control matrix:** must-block / must-allow / must-redact / error-path. Each assertion checks *which* control fired, not just "something blocked".
- **Coverage gate:** any control without both an allowed and a blocked case shows **UNTESTED** and fails the run. Rules and feed signatures carry their own `tests:`, so a judge's new rule gets tested automatically.
- **False-positive wall:** finance-jargon and Polish benign sets ("kill switch", "execute the order", "egzekucja zlecenia") must pass.
- **Performance** (8 GB M-series, `make bench`):

| Metric | Value |
|---|---|
| Deterministic overhead p50 / p95 | **[x] / [x] ms** |
| Redaction (new content) p95 | **[x] ms** |
| Throughput | **[x] rps** |
| Semantic escalations | **[x]%** of traffic |

**Visual:** The `make test` console matrix (green, with yellow xfails) as the main image, plus a small stacked bar: "Aegis overhead [2] ms of [820] ms model time = [0.24]%".

**Speaker notes (30 s):** "Judges will run our suite, so it's one command, it runs without a model, and it reports per control. We're honest about the hard cases: jailbreak corpora are reported as detection and false-positive rates, not as fake 100%. Overhead is a sliver of model latency. You can see it live in the `Server-Timing` header."

---

## Slide 10: From laptop to bank

**Title on slide:** Ready for a regulated bank

**Copy:**
- **Deploy shape:** the data plane runs **local** (per-developer sidecar or per-agent host), because redaction has to happen before egress. The control plane runs **central**: policy via GitOps, the signed feed, approvals, and audit to the SIEM.
- **Scale path:** stateless workers; Postgres for org and approvals; Redis/Lua for atomic multi-level budget reservation; OTLP to a collector. Can sit **behind agentgateway** (Linux Foundation, AAIF) as its guard webhook, while masking stays inline in Aegis.
- **Standards:** OWASP Agent Control Standard dispositions; OWASP LLM 2026 / ASI / MCP tags; OCSF audit; OpenTelemetry GenAI conventions.
- **Compliance support:** GDPR data minimization and pseudonymisation (Arts 5, 25, 32); PCI DSS v4.0.1 (no stored CVV, masked PAN, keyed hashes); EU AI Act logging and human oversight (Arts 12, 14, 26); DORA ICT third-party register and exit strategy (local fallback, kill switch).
- **Try to break it:** Playground · `make test` · edit `policies/catalog.yaml` · [PUBLIC REPO URL]

**Visual:** Left: a "laptop → central control plane" deployment sketch (three laptops with an Aegis sidecar → policy/feed/approvals/SIEM). Right: four compliance badges as text chips (not logos). QR code bottom-right.

**Speaker notes (30 s):** "This isn't just a demo shape. Redaction has to be local, so the data plane is a sidecar on each machine, while policy, the feed, approvals and audit are central. For scale, Aegis can sit behind an open-source gateway like agentgateway. For a bank, it gives evidence for GDPR minimization, PCI handling of card data, AI Act logging and oversight, and DORA third-party controls. It supports compliance; it doesn't certify it. Please try to break it."

---

## Requirement coverage checklist (GS brief §3 → slides)

| Brief requirement | Slide(s) |
|---|---|
| 1. Centralized policy engine (thresholds, adherence %, allowed models, budgets) | 3, 7 |
| 2. Hybrid guardrails (deterministic + semantic, authn/authz) | 4, 5, 6 |
| 3. Budget & resource governance (commercial + local, loops) | 6 |
| 4. Historical attack mitigation via external feed | 2, 7 |
| 5. Security reporting & auditing (metrics, export, dashboard) | 8 |
| 6. Self-testing suite (positive + negative, budgets, exploits) | 9 |
| Deliverables: diagram · sample policy file · dashboard · test suite | 3 · 7 · 8 · 9 |

## Numbers to fill before export (owner: whoever runs the final `make test` / `make bench`)

- [ ] Slide 4: leak rate, precision/recall from the redaction fixtures
- [ ] Slide 5: OWASP coverage counts (from the dashboard coverage tab, *not* from research 01's plan)
- [ ] Slide 7: reload p95, feed activation time
- [ ] Slide 8: audit record count from `verify`
- [ ] Slide 9: test totals, overhead p50/p95, redaction p95, rps, escalation %
- [ ] Cover and slide 10: team names, repo URL, QR code

## Export

Build in Google Slides / Keynote / Figma → **Export PDF** → check that the page count is ≤ 10, that fonts are embedded and that it's readable on a phone. File name: `Aegis_HackYeah2026_GS_AIControlLayer.pdf`. Upload the PDF (optionally also the PPTX).
