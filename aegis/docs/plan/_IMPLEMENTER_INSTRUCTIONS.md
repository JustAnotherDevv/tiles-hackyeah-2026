# Instructions for implementation agents (read fully before coding)

You are one of ~25 implementers building **Aegis** in parallel in ONE shared working tree at
`aegis/` (the Aegis folder of the monorepo). Final submission is Sun ~10:00 — this is a **hackathon demo**: it must look polished and the headline flows must really work end-to-end; the long tail may be simplified or convincingly stubbed (never fake the core demo flows: redaction, blocking, budgets, approvals, live policy edit, feed update).

## Read first
1. `docs/BRIEF.md`, `docs/CONTRACTS.md` (incl. the latest **Addendum** — binding), `docs/MASTER_PLAN.md`.
2. Your bundle entry in `docs/plan/BUNDLES.json` (owned paths, task IDs, plan files, brief).
3. The plan file(s) for your workstream(s) in `docs/plan/` and the matching task IDs in `docs/TASKS.md`.
4. Reusable, tested code in `aegis/staging/` referenced by your plan (move/adapt it into your owned paths; keep staging untouched).

## Hard rules (parallel safety)
- **Edit ONLY files under your bundle's `owned_paths`.** Never edit files owned by other bundles, shared manifests (`pyproject.toml`, `uv.lock`, `web/package.json`, `web/package-lock.json`, root `Makefile`), `docs/CONTRACTS.md`, `docs/TASKS.md`, or `staging/`.
- Integrate via the auto-discovery mechanisms in CONTRACTS (routers in `src/aegis/api/routes/`, controls, detectors, dashboard pages via page meta) — never by editing a shared registry.
- If you need something from another bundle that isn't there yet, code against the CONTRACTS interface and add a small local stub/fallback (clearly marked `# TODO(integration)`), don't edit their files.
- If you need a new dependency, don't install it into the project; note it in your status file (`deps_needed`). For quick experiments use `uv run --with <pkg>` only.
- **No git commands.** No `rm -rf` outside your owned paths. No sudo.
- Machine has 8 GB RAM: don't leave servers running; use unique ports from CONTRACTS when you must start something for a test, and stop it afterwards. Don't load ML models unless your bundle owns the model runtime (use the deterministic/mock mode).
- Python: `uv run ...` inside the project venv (Python 3.13). Web: `npm run ...` in `web/` (don't `npm install` new packages).

## Work order
1. Implement **must** tasks first, then should, then could, keeping the code runnable after each task.
2. Run your **verification tasks** (`<PREFIX>-Vxx`) — unit tests under your owned test paths, quick scripts, `uv run python -c "import ..."`, `npm run build` (if you own web code, ensure the app still builds; if a failure is caused by another bundle's file, note it instead of fixing it).
3. Make it look and feel great where users see it (dashboard pages, CLI output, demo scripts).

## Handoff log (shared, append-only)
`HANDOFF.md` at the repo root is the single entry point other agents use to resume work. **Never edit it with an editor.** Append one line when you start, at each major milestone, and when you finish, using a shell append only:
`printf '%s\n' "- [$(date +%H:%M)] [<bundle-id>] <what you did / state / next step>" >> HANDOFF.md`
Keep lines short and factual (done task IDs, verification results, blockers) so an agent with no context can continue without redoing your work.

## Report
Write `docs/status/<bundle-id>.md` (create the folder if needed; this file is yours) with:
- tasks done / partial / not started (by ID), verification results (commands + pass/fail),
- files created, how to run/demo your part,
- `deps_needed`, `contract_deviations`, `integration_todos` (exact file/line + what the integrator must do).
Your final reply: ≤150 words summarizing the same.
