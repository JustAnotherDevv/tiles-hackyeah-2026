# B08-budgets-ledger — status

Owner paths: `src/aegis/budgets/`, `src/aegis/controls/budget/`, `config/pricing.yaml`,
`src/aegis/api/routes/budgets.py`, `config/snippets/budgets-ledger.yaml`, `tests/unit/budgets_ledger/`.

Work was done in two sessions. Agent 1 wrote the code for BUD-01..15 and the snippet. Agent 2 (this
session) wrote the whole unit-test suite, ran the verification tasks, fixed one EXE-04 dedupe gap
and one F6 policy problem (see below), and wrote this report.

## Tasks

| ID | State | Notes |
|---|---|---|
| BUD-01 skeleton | done | `aegis.budgets.ledger:create`, `tokens.estimate_tokens`, `CONTROLS` in the 3 control modules, route |
| BUD-02 pricing/windows | done | `config/pricing.yaml`, `pricing.py`, `windows.py` (Europe/Warsaw, UTC fallback, DST-safe) |
| BUD-03 limit index | done | `limits.py`: most-specific resolution, `match_agents`, per-instance vs aggregated counters |
| BUD-04 ledger core | done | atomic reserve/check/settle/release/commit, AND chain, TTL sweep, thresholds, coalesced `budget.updated` |
| BUD-05 persistence + demo | done | SQLite write-behind (`budget_usage`, `budget_samples`), demo seed from `config/org.seed.yaml` |
| BUD-06 BUD-01 control | done | clamp, soft downgrade, 402, `budget_raise` draft + patch, dry-run/selftest, on_complete pricing |
| BUD-07 kill switch | done | `killswitch.py`, policy-swap diff → SSE `killswitch` + audit + gauge, runtime kills |
| BUD-08 EXE-04 | done | ladder tool_error → 429 cooldown → kill (429 `killed`, A-07), detectors, rate, step cap, dedupe |
| BUD-09 API core | done | `/api/budgets`, `/raise`, `/reset` (admin), `/api/killswitch` |
| BUD-10 snippet | done | `config/snippets/budgets-ledger.yaml` validates with `PolicyDoc`; chaos entry now `on_soft: warn` (see F6) |
| BUD-11 history/forecast | done | samples ≤ 1 per 5 s, synthetic demo ramp, `/history` + `forecast` |
| BUD-12 BUD-02 control | done | local slots + 429, `num_predict`/`num_ctx` clamps, model-size check on `model.admin` |
| BUD-13 extra endpoints | done | `/raise/preview`, `/enforcement`, `/pricing`, `/usage` (admin), `/sessions` |
| BUD-14 burn rate | done (code), not unit-tested | `loops.BurnRate`, EXE-04 step 5 |
| BUD-15 pricing hot reload | done (code), not unit-tested | `Ledger._pricing_watch` (off in test mode) |
| BUD-16..18 (could) | partial | cost-avoided counter + `/sessions` exist; LOOP-003/007 not built |

## Verification

All commands were run with `AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off` from the repo root.

| ID | Command | Result |
|---|---|---|
| V01 | `uv run --frozen python -c "…estimate_tokens…"` | `100 100 ['EXE-04']`: pass |
| V02 | `pytest tests/unit/budgets_ledger/test_tokens_pricing.py` | pass (Sonnet $0.0105, Haiku cache $0.0033, judge $0.002, prefix strip, `*`, web.fetch_url) |
| V03 | `pytest …/test_windows_limits.py` | pass (Warsaw 22:00Z, month/week, DST 2026-10-25, member override, match_agents) |
| V04 | `pytest …/test_ledger.py` | pass (AND names `team:research`, release, overshoot log, TTL, thresholds once, coalescer) |
| V05 | `pytest …/test_ledger.py -k concurrency` | pass (exactly 10 of 200) |
| V06 | `pytest …/test_store.py` | pass (restart restores, seed 38.40 / 1088.40, history ≥ 2 points, samples ≤ 1 per 5 s) |
| V07 | `pytest …/test_bud01.py` | pass (16 tests, including the new F6 regression `test_f6_runaway_reaches_budget_raise`) |
| V08 | `pytest …/test_exe04.py …/test_killswitch.py` | pass. Kill is **429** `killed` + 3600 for every client (A-07 overrides the plan's 403) |
| V09 | `pytest …/test_api.py` | pass (in-process FastAPI + fake rt). The killswitch patch is `append`/`remove` (A-33 grammar) |
| V10 | F6 curl script (lead, live stack) | **not run** (needs `make up`). An in-process simulation with live `config/policy.yaml` was run: see F6 below |
| V11 | `ruff check` + `ruff format --check` on owned paths; full suite | clean; **75 passed in ~5 s** |
| V12 | `pytest …/test_ledger.py -k perf -s` | p95 0.35 ms, median 0.14 ms (target < 1 ms) |
| V13 | Claude Code stop (manual) | not run |
| BUD-12 | `pytest …/test_bud02.py` | pass |

## Fixes in this session

1. **EXE-04 dedupe at evaluate time** (`loops.LoopRegistry.seen_elsewhere`, `exe04_loops.py` step 7).
   A hook + MCP-proxy sighting of one call, confirmed by the other source within `dedupe_s`, no
   longer trips `exact_repeat` early.
2. **F6 runaway stalled at 86 %.** An in-process run of the runaway flow with the live
   `config/policy.yaml` showed the problem. Requests 1–6 were allowed. From request 7 on, every
   request was **downgraded to `aegis-judge`** (default `on_soft: downgrade`). The cost then stopped
   growing at about $0.38, so the $0.50 `budget_raise` approval never appeared. With `on_soft: warn`
   on the chaos entry, requests 7 and 8 are logged and request 9 returns `require_approval`. Fixed in
   our snippet, but **the live policy also needs it** (see integration_todos).

## Files created this session
`tests/unit/budgets_ledger/{conftest.py,test_tokens_pricing.py,test_windows_limits.py,test_ledger.py,test_store.py,test_bud01.py,test_bud02.py,test_exe04.py,test_killswitch.py,test_api.py}`
(the empty `.gitkeep` in that folder can be removed). Edited: `src/aegis/budgets/loops.py`,
`src/aegis/controls/budget/exe04_loops.py`, `config/snippets/budgets-ledger.yaml` (+ ruff format of owned files).

## How to run / demo
- Tests: `AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off uv run --frozen pytest tests/unit/budgets_ledger -q`
- Live F6 (after `make up`): the BUD-V10 script in `docs/plan/07-budgets-ledger.md` §5.
- Demo levers: `POST /api/budgets/reset {}` (admin) re-seeds the demo state. `POST /api/budgets/usage` (admin) fast-forwards spend.

## deps_needed
None. `watchfiles` is optional and only used for the pricing hot reload.

## contract_deviations
- None new. Already aligned with Addendum A: kill = 429 (A-07), `x-aegis-budget-remaining` in
  `Decision.meta.response_headers` (A-01), and `BudgetStatus.soft_pct` is an extra field (A-36).

## integration_todos
1. **policy-engine (`config/policy.yaml` line ~170, and `docs/seed-fixes/policy.yaml` line 122):** add
   `on_soft: warn` to the `agent:chaos-agent@platform` limit. Without it, F6 never reaches the
   budget_raise approval because the soft downgrade to the local model takes over. Demo-critical.
2. policy-engine: the `budget_raise` executor must apply `payload["patch"]` with `source="approval"` (A-25).
3. demo-mocks-docs: `runaway.py` should use a fixed `X-Aegis-Session` and vary prompts by step, so
   EXE-04 `model_repeat` (5) doesn't fire before BUD-01.
4. Lead: run BUD-V10 (live curl script) and, optionally, BUD-V13.
