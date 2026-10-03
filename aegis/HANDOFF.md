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

## Snapshot (orchestrator-maintained) — last update Sat 22:35
| Phase | Status |
|---|---|
| 0 Research (7 reports) | ✅ done |
| 1 Staging artifacts (10 packages) | ✅ done, all tested |
| 2 Contracts (`docs/CONTRACTS.md`) | ✅ done (Addendum pending from synthesizer) |
| 3 Workstream plans | ✅ 20/20 done (`docs/plan/01…20-*.md`) |
| 4 Synthesis (Addendum, MASTER_PLAN, TASKS, BUNDLES.json, seed fixes) | 🟡 running: synth-A (Addendum + docs/seed-fixes/), synth-B (MASTER_PLAN, TASKS, BUNDLES.json, DEPENDENCIES.json) |
| 5 Scaffold (pyproject/uv venv, package skeleton, web app, Makefile, first commit) | 🟡 running in parallel with synthesis |
| 6 Build fleet (~25 bundles, ≤20 concurrent agents) | ⏳ after 5 |
| 7 Integration & verification (build, tests, demo flows, commit) | ⏳ |
| 8 Submission (numbers, deck PDF, video, HackTribe) | ⏳ |

Known issues to resolve in synthesis (flagged by planners):
- Two-person rule can't complete with one owner → define as owner + admin (or add a 2nd owner to the seed).
- Seed tool allowlists block the $12/$480 spend demo flows before ACT routing; DLP-01 blocks all external emails before ACT-03 → fix ordering/policy.
- Single NER instance (semantic-models hosts it, redaction borrows) — never load twice (+673 MB).
- Budget/kill-switch stop codes for Claude Code: 429 + `retry-after` + `x-should-retry:false` (never 403); policy blocks as synthetic 200.
- Policy self-test must ignore live budget counters / kill switch (otherwise every edit is rejected).

## How to continue (for a fresh agent)
1. Read this file, then `docs/BRIEF.md`, then `docs/MASTER_PLAN.md` (if it exists) and `docs/plan/BUNDLES.json`.
2. Check the latest **Progress log** lines and `docs/status/*.md` to see what's done; check `git log` once the scaffold commit exists.
3. Continue the first phase that isn't ✅:
   - **Phase 3**: write the missing plan(s) following `docs/plan/_PLANNER_INSTRUCTIONS.md`.
   - **Phase 4**: synthesize per the "Synthesis" brief in the Progress log / MASTER_PLAN header.
   - **Phase 6**: for each bundle in `BUNDLES.json` without a `docs/status/<id>.md` marked complete, run one implementer following `docs/plan/_IMPLEMENTER_INSTRUCTIONS.md` (strict file ownership, no manifest edits, no git).
   - **Phase 7**: integrate — `uv run` the gateway, `npm run build` in `web/`, `make test`, fix cross-bundle issues, commit.
4. Never redo finished work: trust `docs/status/*` + Progress log + git; re-verify only what you touch.

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
