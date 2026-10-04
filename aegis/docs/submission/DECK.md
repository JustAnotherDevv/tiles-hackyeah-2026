# Pitch deck: Aegis (10 slides, English, PDF)

> **Limits:** ≤ 10 slides, English, PDF. Phase-1 judges read it **without us**, so every slide stands alone;
> speaker notes are for the finalist pitch (one presenter).
> **Source of the PDF:** `deck/deck.html` (10 print-ready 1920×1080 slides, dashboard design tokens, system
> fonts, no CDN) → `uv run --frozen python docs/submission/build.py collect render --pdf` →
> `out/Aegis_HackYeah2026_GS_AIControlLayer.pdf`. Edit copy in **both** this file and `deck.html`.
> **Numbers:** `{{TBD: …}}` placeholders are filled from `numbers.json` (collected from `reports/`);
> unresolved ones render as a visible `[TBD: …]`. Never ship a number that wasn't measured; a target must
> say "target".
> **Screenshots:** slots load `docs/assets/screens/<name>.png` when present (capture after `make demo`
> warm-up: `build.py --screens --url http://127.0.0.1:8787`, or by hand at 1920×1080), else a labelled frame.

## Criteria → slide map

| Criterion | Weight | Primary | Supporting |
|---|---|---|---|
| Guardrail robustness & quality | 30 | 4 (local redaction), 5 (hybrid guardrails + OWASP) | 2, 7, 9 |
| Architecture & performance | 20 | 3 (architecture), 9 (overhead) | 7 |
| Security reporting & auditing | 20 | 8 (dashboard + audit) | 6, 9 |
| Self-testing suite | 15–20 | 9 (test matrix) | 7 (rules carry their own tests) |
| Practical implementability & scalability | 10–15 | 10 (production path) | 3, 6 |

## Slide 1: Cover

**Aegis** · *Local-first guardrails for every agent call* · Redact locally · Govern centrally · Prove
continuously · Goldman Sachs · AI Control Layer · HackYeah 2026 · team `[NAME — EMAIL]` · `[PUBLIC REPO URL]`.

*Notes (10 s):* "Aegis is a control layer on every call an AI agent makes. It redacts customer data locally
before anything leaves, governs spend and actions by role, and proves it with tests and an audit trail."

## Slide 2: Agents leak, loop and overreach

- **Leak:** prompts, files and tool results carry PESELs, IBANs, card numbers and secrets to remote models
  and third-party MCP servers.
- **Get hijacked:** a poisoned README, web page or MCP tool description redirects the agent (ASI01).
- **Loop:** one runaway agent burns tokens or GPU time (LLM06:2026 Unbounded Consumption).
- **Overreach:** agents buy, write to production or email externally with no human approval (LLM03:2026 Excessive Agency).
- **Can't prove it:** no per-decision audit trail, no spend view.
- Real incidents: EchoLeak (CVE-2025-32711), postmark-mcp BCC backdoor, LiteLLM 1.82.7–1.82.8 PyPI
  compromise, MCP tool poisoning.

*Notes (25 s):* "Each agent call is a data-egress event, an execution event and a spend event at once. These
are real: EchoLeak exfiltrated data through a markdown image; an MCP server quietly BCC'd every email."

> OWASP 2026 IDs: verify against the official list before export (research 01 §11); keep the year suffix.

## Slide 3: One policy decision point for every hop

- Surfaces: `/v1/messages`, `/v1/chat/completions`, `/ollama/*`, `/mcp/{server}`, `/egress`,
  `/v1/hooks/claude-code`, `/v1/guard`.
- Pipeline: identify → normalize → deterministic → semantic → combine → budgets → approvals → redact/rehydrate → audit.
- Decisions `allow · log · redact · require_approval · block` = ACS `allow · modify · deny · ask`.
- Control plane: one YAML file (hot reload) + an external **signed** feed + SQLite + hash-chained audit.
- Claude Code with a demo settings profile (`make claude`): model, tools and MCP through Aegis, nothing machine-wide.
- Visual: `docs/assets/architecture.svg`.

*Notes (30 s):* "A single gateway on localhost. Claude Code points its model traffic at us, its tool calls go
through a fail-closed hook, its MCP servers through our proxy. Every hop runs the same pipeline,
deterministic first, AI second."

## Slide 4: The remote model never sees the customer

- Detected **on the device**: PII, cards, Polish IDs (PESEL, NIP, REGON, IBAN), secrets, metadata.
- **Validators, not bare regex:** Luhn, PESEL/NIP checksums, IBAN mod-97, context words.
- **Destination-aware:** raw to local Ollama, tokenized to a remote model, tokenized or blocked to a third party.
- Reversible placeholders (`[PESEL_1]`), stable per session, restored only for the local user.
- **PCI:** CVV dropped, never vaulted; PAN shown as first 6 / last 4; audit stores keyed HMACs.
- Measured on our redaction fixture set ({{TBD: dlp.cases}} cases): leak rate on validated types
  {{TBD: dlp.leak_rate_validated}}, precision {{TBD: dlp.precision}}, recall {{TBD: dlp.recall}}, p95 {{TBD: dlp.latency_p95_ms}} ms.
- Visual: Wire view screenshot (`screens/wire.png`).

*Notes (35 s):* "This is the headline: data minimization before egress, on the laptop. Validators keep
precision high, NER catches names, placeholders keep the model useful, real values return only locally."

## Slide 5: Deterministic first, AI second, every hop

- Deterministic (µs–ms): Unicode normalization (zero-width, tag characters, homoglyphs, base64), secrets,
  command guard, SSRF guard, MCP poisoning scan + rug-pull pinning, exfil-link stripping, signed signatures.
- Semantic (local models, escalation only): injection classifier, Qwen3Guard, multilingual NER. Per-control
  `fail_mode`; model down → deterministic-only + `degraded` flag, never silent pass-through.
- Screens untrusted content too: tool results, MCP descriptions, fetched pages.
- Red-team eval (balanced, {{TBD: eval.mode}}): detection {{TBD: eval.detection_rate}} {{TBD: eval.detection_ci}}, held-out public sets
  {{TBD: eval.heldout_detection}}, at {{TBD: eval.fpr}} false positives; deterministic only {{TBD: eval.det_detection_rate}} at {{TBD: eval.det_fpr}}.
- OWASP coverage (live from the catalog): LLM {{TBD: coverage.llm}} · ASI {{TBD: coverage.asi}} · MCP {{TBD: coverage.mcp}}.

*Notes (30 s):* "Judges will attack the gaps: a tool result, an MCP description, a base64 payload. We
normalize first, screen every hop, and put an independent control on the exfiltration leg."

## Slide 6: Spend and actions follow your org chart

- Budgets org → team → agent → session: tokens, USD, **local compute-seconds**; soft limit → downgrade; hard → 402.
- Runaway agents: repeat/cycle detection → tool error → block → kill switch (429 `killed`).
- Roles: owner · admin · member · agents as service identities (never approvers).
- Routing: ≤ $20 sponsor · ≤ $200 admin · > $200 owner · > $1,000 owner + admin · > $5,000 blocked ·
  PII table → admin · prod write → owner · budget 2× → owner.
- Grants bound to exact parameters, single-use, expiring, audited.
- Visual: approvals inbox as u_piotr ("needs admin") (`screens/approvals.png`).

*Notes (30 s):* "Every risky agent action and every config change is routed to the right role. An admin can
approve a $50 subscription; doubling the team budget needs the owner."

## Slide 7: Edit it live and it stays safe

- One YAML file: controls, mode, action, threshold, adherence %, models, budgets, approval rules, 4 profiles.
- Save → validate → **self-test gate** → atomic swap → version stamped on every decision; bad YAML →
  rejected, last-good keeps serving. Reload p95 {{TBD: policy.reload_ms}} ms.
- External threat feed (:8790): Ed25519-signed, monotonic serial, anti-rollback, inline test vectors;
  tampered bundle → rejected.
- Visual: threshold 0.80 → 0.50 → toast → verdict flips; feed serial N → N+1 (`screens/policy.png`).

*Notes (30 s):* "The brief says judges will edit config and feeds live, so we built for it."

## Slide 8: Every decision explained, chained and exportable

- Management: spend vs budget by team, blocked interactions, cost avoided.
- Security: live decision stream with control, score vs threshold, redacted evidence, policy and feed version.
- Performance: per-control p50/p95, gateway overhead vs upstream, `Server-Timing` on every reply.
- Audit: append-only, hash-chained, redacted at write time; export JSONL / CSV / **OCSF**; Prometheus `/metrics`.
- Visual: overview + live feed (`screens/overview.png`, `screens/live.png`).

*Notes (25 s):* "Management sees money, security sees every decision and why, and the audit log exports
straight into a SIEM."

## Slide 9: One command proves every control

- `make test`: {{TBD: tests.total}} cases · {{TBD: tests.failed}} failed · {{TBD: tests.duration_s}} s; no model needed;
  semantic cases skipped with a reason when models are absent.
- Per-control matrix: must-block / must-allow / must-redact; asserts *which* control decided; UNTESTED fails the run.
- False-positive wall: "kill switch", "execute the order", "egzekucja zlecenia" must pass.
- `make bench`: deterministic overhead p50 / p95 {{TBD: perf.overhead_p50_ms}} / {{TBD: perf.overhead_p95_ms}} ms;
  throughput {{TBD: perf.rps}} rps; overhead share {{TBD: perf.overhead_share_pct}} of upstream time.
- Visual: `make test` matrix (`screens/tests.png`).

*Notes (30 s):* "Judges will run our suite: one command, no model, per-control results. Jailbreak corpora
are reported as rates, not as a fake 100 %."

## Slide 10: Ready for a regulated bank

- Data plane **local** (sidecar per developer / agent host); control plane **central** (policy via GitOps
  with the same self-test gate, signed feed, approvals, audit to the SIEM).
- Scale path (designed): stateless workers, Postgres, Redis/Lua for atomic multi-level budget reservation;
  can sit behind agentgateway as its guard webhook.
- Standards: OWASP ACS dispositions, OWASP LLM 2026 / ASI / MCP tags, OCSF, OpenTelemetry GenAI.
- Supports evidence for GDPR minimisation/pseudonymisation, PCI DSS v4.0.1, EU AI Act logging & oversight,
  DORA third-party controls (supports, does not certify).
- Try to break it: Playground · `make test` · edit `config/policy.yaml` · `[PUBLIC REPO URL]`.

*Notes (30 s):* "Redaction has to be local, so the data plane is a sidecar; policy, feed, approvals and
audit are central. Please try to break it."

## Requirement coverage

| Brief requirement | Slides |
|---|---|
| 1. Centralized policy engine | 3, 7 |
| 2. Hybrid guardrails | 4, 5, 6 |
| 3. Budget & resource governance | 6 |
| 4. Historical attack mitigation via external feed | 2, 7 |
| 5. Security reporting & auditing | 8 |
| 6. Self-testing suite | 9 |
| Deliverables: diagram · sample policy · dashboard · test suite | 3 · 7 · 8 · 9 |
