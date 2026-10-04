# HackTribe — Goldman Sachs (AI Control Layer): Aegis + Tiles

Title (≤ 5 words):

```text
Aegis + Tiles: Governed AI
```

Description (≤ 500 words incl. team; replace the Team line with real names + emails on HackTribe only):

```text
Problem. AI agents now call models, tools and MCP servers, touch customer data and spend money. One injected email can become a payment; one prompt can send a client list to a remote model.

What we built. One governance layer for agentic AI, from the trading desk to the phone in your pocket.

Aegis (enterprise). A local-first gateway on every hop: agent to model (Anthropic, OpenAI-compatible, Ollama), agent to MCP tools, agent to HTTP, agent to agent, and Claude Code's own tool calls. Every request runs one policy pipeline and ends in allow, redact, block, require approval or log.
- Centralized policy: one YAML file, hot-reloaded after validation and a self-test, with last-known-good fallback.
- Local-first redaction: PII, cards, PESEL, NIP, IBAN and secrets become reversible placeholders before anything leaves the machine.
- Hybrid guardrails: deterministic detectors first, optional small local models second.
- Budgets per org, team, agent and session, with loop detection and a kill switch.
- Approvals routed by role and amount ($50 to an admin, $480 to the owner, a second approver above $1,000), bound to the exact parameters, never self-approved by an agent.
- Signed threat-intel feed of historical AI exploits, hash-chained audit log, live dashboard.

OWASP. Every risk in the OWASP Top 10 for Agentic Applications (ASI01–ASI10) has an enforcing control and a passing attack test: goal hijack, tool misuse, identity abuse, supply chain, code execution, memory poisoning, inter-agent messages, cascading failures, human-trust exploitation, rogue agents. OWASP LLM Top 10: 9 of 10.

Tiles (the human end of the loop). A HarmonyOS app that applies the same pattern to people. The phone rebuilds itself for a senior, a child or a low-vision user; an on-device assistant generates new UI; a caregiver approves every change; Guardian explains why a call looks like a scam. A caregiver approving an AI change is the consumer version of a risk officer approving an agent's trade. Tiles' assistant already emits structured JSON designed to come from an LLM routed through Aegis; wiring that up is our next step.

Results. End-to-end attack matrix of 1,172 cases with 0 failures; independent black-box check of the ASI controls (52 of 53 probes behaved as expected); deterministic detection 66.6 % at 0.4 % false positives, 92.4 % with the optional local models; p50 overhead 2.4 ms. Runs offline on an 8 GB laptop.

Try it. https://github.com/JustAnotherDevv/tiles-hackyeah-2026. In aegis/: make setup, make up, open http://127.0.0.1:8787/ui, then make test. Judges' guide: aegis/docs/JUDGES.md.

Team: JustAnotherDevv
```

## Problem / Solution fields

### Goldman Sachs (AI Control Layer)

Problem:

```text
AI agents now act, not just answer: they call models, tools and MCP servers, read customer data and spend money. Each hop can leak PII to a remote model, run a poisoned tool, loop through a budget or take an action nobody approved. Firms have no single place to set the rules, enforce them and prove what happened.
```

Solution:

```text
Aegis is a local-first gateway on every agent hop (model, MCP tool, HTTP, agent-to-agent, Claude Code tool calls). One hot-reloaded YAML policy decides allow, redact, block, approve or log. Sensitive data is redacted on the device before it leaves, risky actions go to the right human by role and amount, budgets and a kill switch stop runaways, and every decision lands in a hash-chained audit log. It covers all ten OWASP agentic risks (ASI01–ASI10). Tiles, our HarmonyOS app, brings the same human-in-the-loop pattern to everyday people.
```

### Huawei (Imagine What's Next)

Problem:

```text
Phones are designed for one kind of user. A 78-year-old misses small buttons, a child needs limits and a parent in the loop, a low-vision user needs everything spoken, and scammers target the most vulnerable. Accessibility settings exist, but people rarely find them and nobody tunes them over time.
```

Solution:

```text
Tiles is a native HarmonyOS app that reshapes the phone around the person. The home is a grid of big, live, colorful tiles that rebuilds itself for a senior, a child, a low-vision user or an everyday user. Ask in plain words and an on-device assistant generates a new tile that ArkUI renders natively. Tiles learns from use (missed taps, unused apps) and proposes changes that a caregiver approves from their own phone. Guardian flags scam calls on the device and turns them into one calm instruction. Aegis, our local-first guardrail layer, is designed to keep future AI features safe on the device.
```
