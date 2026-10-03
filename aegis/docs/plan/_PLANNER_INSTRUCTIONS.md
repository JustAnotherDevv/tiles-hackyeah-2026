# Instructions for workstream planners (read fully before starting)

You are one of 20 planners working in parallel on **Aegis**, an AI Control Layer for the Goldman Sachs task at HackYeah 2026 (final submission Sun ~10:00; it must look polished and the headline flows must really work; the long tail may be simplified). Project root: `/Users/nevvdevv/Development/hackathons/_october_2026/hackyeah/aegis`.

## Read first
1. `docs/BRIEF.md` — requirements, product vision (incl. org roles & approvals), fixed tech decisions.
2. `docs/CONTRACTS.md` — **binding**: repo tree, ownership map (your owned paths), core types, plug-in auto-discovery, policy schema, HTTP API + JSON shapes, SQLite schema, SSE events, ports, parallel-work rules. It is long: read its overview and the sections relevant to your workstream carefully.
3. Your research references in `/Users/nevvdevv/Development/hackathons/_october_2026/hackyeah/research/goldman/`.
4. **Pre-built, tested artifacts in `aegis/staging/` — REUSE them** (read the README / FINDINGS / RESULTS relevant to you):
   - `staging/models/` — benchmarked ONNX + Ollama wrappers (`pi_classifier.py`, `ner_pii.py`, `embedder.py`, `ollama_guard.py` with the corrected Qwen3Guard prompt, `ollama_judge.py`), `RESULTS.md` with thresholds; models already downloaded to `aegis/models/`; Ollama aliases `aegis-guard`, `aegis-judge`.
   - `staging/pii/` — deterministic detectors + validators + normalization with offset mapping + placeholder vault + streaming rehydrator + ≥400 labelled fixtures + precision/recall tests (may still be finishing).
   - `staging/corpora/` — 1194 labelled eval cases (EN/PL, finance false-positive set, agentic/tool attacks, obfuscation matrix) + `obfuscate.py`, licences.
   - `staging/feed-seed/` — 20 validated threat signatures + 1 pending demo signature, `feedlib.py` matcher engine, schema, ed25519 sign/verify/scan scripts.
   - `staging/seed/` — `org.seed.yaml` (Acme Capital: teams, members, roles, agents, budgets), `policy.yaml` (37 controls, strict/balanced/permissive, 157 inline examples), `approvals.yaml` (65 approval rules), `SCENARIOS.md` (12 demo scenarios).
   - `staging/design/` — hi-fi HTML dashboard prototype + `DESIGN_TOKENS.md` (may still be finishing).
   - `staging/submission/` — HackTribe text, 10-slide deck outline, 60 s video script, 4:30 demo runbook, architecture diagrams.
   - `staging/spikes/claude-code/FINDINGS.md` — empirically verified Claude Code gateway/hook/budget behaviour + working proxy and hook code.
   - `staging/spikes/mcp/` — working `aegis_mcp` governance proxy package (16/16 checks, verified with Claude Code) + FINDINGS.md.
   - `staging/spikes/streaming/` — SSE parsers/transformers + rehydration (may still be finishing).
   Where staging and CONTRACTS.md disagree on shapes, CONTRACTS wins — plan the adaptation explicitly.

## Write your plan
To `docs/plan/<NN>-<slug>.md` (given in your prompt). Contents:
1. **Goal & demo value** — what judges/the demo will see; which judging criteria it serves.
2. **Design** — modules/files *within your owned paths only* (from the CONTRACTS ownership map), key classes/functions, data flow, config keys read, events emitted, endpoints served.
3. **Reuse map** — exactly which staging files move/adapt into which owned paths.
4. **Interfaces** — consumed and provided, matching CONTRACTS exactly. If something you need is missing, add a clearly marked **"Contract gaps"** section proposing an addendum (don't invent conflicting shapes).
5. **Tasks** — stable IDs with your given prefix (`<PREFIX>-01`, …). Each: title, subtasks (checkbox list), priority (must/should/could), `demo_critical` yes/no, estimate (minutes), dependencies (other task IDs or contract items), and **VERIFICATION tasks** (concrete commands, tests or manual checks that prove it works — IDs `<PREFIX>-V01`, …).
6. **Demo cut** — the minimum that must really work live vs what may be simulated/stubbed convincingly.
7. **Dependencies** — Python/npm packages (versions if important). Implementers may NOT edit manifests, so list everything.
8. **Risks & mitigations.**

Size the work for ONE strong implementer agent working ~60–120 minutes, ordered so it degrades gracefully (must → should → could).

## Rules
- Do NOT write implementation code and do NOT edit any file except your own plan file.
- Do not run long processes; reading/inspecting files and quick commands are fine.
- Your final reply: a summary of ≤150 words (task count, must-count, key reuse, contract gaps).
