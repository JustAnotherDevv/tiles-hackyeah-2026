# B22-test-suite-functional — status

Functional e2e suites (plan 18 §2.7 A–J, half B). The suites are black-box tests against a hermetic gateway: real `create_app` + uvicorn on an ephemeral port, plus the real `mocks.mock_llm`, `mocks.mock_mcp` and `mocks.exfil_sink` apps in threads. They use no fixed ports, load no models, and run with `AEGIS_SEMANTIC=off`.

Every test carries `@pytest.mark.aegis(suite=…, control=…, polarity=…)`, so B21's matrix plugin counts it.

## Tasks

| ID | State | File(s) | Result (integrated tree, 00:16) |
|---|---|---|---|
| TEST-09 approvals & RBAC (must) | done (A1–A12 incl. A11 expiry) | `tests/e2e/test_approvals_rbac.py` | 16 cases: 15 pass, 1 xfail (product gap, below) |
| TEST-10 budgets / loops / rate / kill (must) | done (B1–B9) | `tests/e2e/test_budgets_loops.py` | 9/9 pass |
| TEST-11 hot reload (must) | done (C1–C12) | `tests/e2e/test_hot_reload.py` | 12 cases: 11 pass, C5 xfail ("heuristic score 0", as the plan allows) |
| TEST-12 Claude Code hooks (must) | done | `tests/e2e/test_hooks.py` | 11/11 pass (includes `scripts/aegis-hook` end to end + fail-closed exit 2 / PostToolUse exit 0) |
| TEST-14 MCP integrity (should) | done (F1–F5; F6 not done) | `tests/e2e/test_mcp.py`, `tests/lib/fakes/mcp.py` | 5/5 on real mock_mcp; 5/5 on the fallback fake (`AEGIS_TEST_FAKE_MCP=1`) |
| TEST-15 audit & privacy (should) | done (G1–G4) | `tests/e2e/test_audit_privacy.py` | 6/6: chain verify, exports admin-only, 0 raw PESEL/PAN/AWS/email hits, byte flip detected |
| TEST-16 error paths (should) | done | `tests/cases/errors.yaml` (7 cases), `tests/e2e/test_errors.py` | 10/10; YAML: 6 pass via B21 runner, the MCP case skips without an MCP upstream |
| TEST-19 streaming & egress (should) | done | `tests/e2e/test_streaming_egress.py` | 6/6: SSE well-formed with no key, MD beacon stripped + sink 0, canary, OpenAI usage, `/egress` 403 DLP-04 + benign 200 / sink 1 |
| TEST-22 semantic (could) | done (skip path verified; on-path not run, no models allowed) | `tests/e2e/test_semantic.py`, `tests/fixtures/corpora/semantic_gate.jsonl` (24 rows EN/PL) | skips with reason when off |
| TEST-23 real file-watch reload (could) | done (`slow`) | `tests/e2e/test_reload_watch.py` | 3/3 + guard latency smoke (feeds `perf.guard_p50/p95_ms`) |
| TEST-24 dashboard route | **skipped**: Addendum A-53 gives `/api/selftest` to audit-metrics, not test-suite | — | — |

## Verification

- **TEST-V09, V10, V11, V13, V14, V15 combined:**
  ```
  AEGIS_SEMANTIC=off AEGIS_TEST_MODE=1 uv run --frozen pytest tests/e2e/test_approvals_rbac.py tests/e2e/test_budgets_loops.py tests/e2e/test_hot_reload.py tests/e2e/test_hooks.py tests/e2e/test_mcp.py tests/e2e/test_errors.py tests/e2e/test_streaming_egress.py tests/e2e/test_semantic.py tests/e2e/test_reload_watch.py tests/e2e/test_audit_privacy.py
  ```
  Result: 79 matrix cases, 76 pass, 2 xfail, 1 skip, 0 fail. Wall time 44 s, max RSS 267 MB.
- `perf.reload_ms` is written to `tests.lib.matrix.RESULTS.perf` (TEST-V11, under 1000 ms).
- **V15:** `test_semantic.py` reports SKIPPED "semantic: AEGIS_SEMANTIC=off", never PASS.
- **V17:** not applicable (TEST-24 skipped).
- `uv run --frozen ruff check` + `ruff format` on all owned files: clean.
- `tests/cases/errors.yaml` passes B21's `tests/test_cases_schema.py`.

## How to run

```
uv run --frozen pytest tests/e2e/test_approvals_rbac.py -q        # one suite (each ≤ 15 s)
AEGIS_TEST_FAKE_MCP=1 uv run --frozen pytest tests/e2e/test_mcp.py # force the fallback fake MCP
AEGIS_SEMANTIC=on uv run --frozen pytest tests/e2e/test_semantic.py # make test-sem path (models needed)
uv run --frozen pytest -m "not slow" tests/e2e                     # skips test_reload_watch / A11
```

## Product gaps found (owners, not edited by me)

1. **Viewer impersonation fallback (org-rbac B09 / core `deps.viewer`).** `X-Aegis-View-As: research-agent@research` (an unknown member id) silently resolves to the default viewer `u_katarzyna` (owner), and the vote is recorded as the owner's. Test: `test_a3_agents_never_vote` (xfail). Engine eligibility is correct: `can_approve(agent)` returns False.
2. **INJ-04 crash (injection-defense B06).** `src/aegis/injection/canary.py:53 extract_urls` → `m.span(1)` raises `IndexError: no such group`. INJ-04 then degrades to allow on model responses (logged at ERROR on every response hop).
3. **INJ-02 heuristic (B06/B07)** gives no score in `(0, 0.99)` for mild prompts with semantic off, so C5 xfails.
4. **Transient regression, gone at 00:14:** two extra `session:*` limit entries appeared in `config/policy.yaml` at 00:08. While they were there, `/api/budgets/raise` 60→75 also emitted spurious `budget.remove(session:*)` changes, so the request routed to `raise-other` (owner) and the F5 flow broke. If duplicate-scope limits come back, the raise patch / diff selector (`budgets.limits[scope=…,window=…]`) is ambiguous (B03/B08). `test_a9_budget_raise_governed` catches it.

## Fixed by others during the run

- BUD-01 soft downgrade was not applied while the chaos limit had `on_soft: warn`. My override now sets `on_soft: downgrade` on the limit entry itself.

## deps_needed

None.

## contract_deviations

None. Tests follow the contract and Addendum A:
- A-07 (429 `killed`, 402 + `x-should-retry: false`, synthetic 200 for proxy blocks)
- A-18 (401 `unauthenticated`)
- A-20 (two-person = owner + admin)
- A-23 (deny + link, never `ask`)

Two tolerances:
- A double vote by the same approver may answer either a 4xx or an idempotent 200, as long as the request still shows one distinct voter and stays pending.
- `/api/budgets` rounds `used` to 4 decimals. B1 therefore checks the API value to 1e-4 and the ledger to 1e-6 when it can reach it.

## integration_todos

- Every owned e2e module embeds a compact `LocalStack` (marked `# TODO(integration)`). The integrator can swap it for B21's `tests.lib.stack.HermeticStack` / `gw` fixture. It only needs `tests/lib/servers.py`, which B21 already ships.
- The stack copies `config/policy.golden.yaml` (falling back to `config/policy.yaml`) into a temp dir and applies these overrides:
  - `hold_s` all 0
  - `redeem_window_s` 0.001
  - rate limits 100k/min
  - mock provider URLs pointed at the test doubles
- `tests/lib/fakes/mcp.py` is ready for B21's `stack.py` to import lazily: `create_app()` serves the same `/mcp/<name>`, `/_mock/rugpull/flip`, `/_mock/reset` and `/_mock/requests` surface as `mocks.mock_mcp`.
- Register the `aegis` marker. B21's `conftest` already does this; without it pytest warns with `PytestUnknownMarkWarning` only.
