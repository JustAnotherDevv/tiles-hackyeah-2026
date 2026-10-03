# B21-test-suite-harness — status

Owner workstream: test-suite (plan `docs/plan/18-test-suite.md`). Wave 2, started fresh 23:27, done ~00:15.

## Tasks

| ID | State | Notes |
|---|---|---|
| TEST-01 harness core + contract fixtures | done | `tests/conftest.py` (CONTRACTS §7.3 `aegis_env`, `app`, `client`, `rt`, `mock_llm_url`, `policy_patch` + `aegis_stack`/`gw` (module), `make_stack`, `live`; nothing autouse), `tests/lib/servers.py` (ThreadedUvicorn port 0, SubprocessServer, atexit kill), `tests/lib/stack.py` (HermeticStack / LiveStack, `AEGIS_TEST_GATEWAY=subprocess`, `AEGIS_TEST_OVERRIDES`), `tests/fixtures/policy_overrides.yaml` |
| TEST-02 fakes | done | `tests/lib/fakes/llm.py` (Anthropic+OpenAI JSON/SSE, all §5.6 triggers, exact chars/4 usage, `/_mock/requests`), `fakes/sink.py`, `tests/lib/identities.py` |
| TEST-03 client libs | done | `tests/lib/client.py` (Gateway: guard/anthropic/openai/ollama/hook/egress/api/decision/policy/controls/approvals/approve/deny/cancel/budgets/feed_status/wait_version), `mcp_client.py` (JSON + SSE replies, Mcp-Session-Id), `sse.py` (bounded replay reader) |
| TEST-04 schema/loader/macros/expect | done | `tests/lib/cases.py` (pydantic `extra=forbid`, `file:line` errors, defaults, `_` files skipped), `macros.py` (gen:* incl. CRC-valid github_pat, b64/b64url/hex/tags/zw/repeat, nestable), `runner.py` (all 10 vias), `expect.py` (pass/pass_other/fail/disabled/not_implemented/skip, k-of-n), `privacy.py`, `policy_sandbox.py`, `tests/test_cases_schema.py` |
| TEST-05 seed case files | done | `tests/lib/seed_import.py` (157 staging examples + 54 routing tests, translation table §2.6), curated into `tests/cases/{gov,act,dlp,inj,exe,mcp,bud,sig,cus,hooks,approvals_routing}.yaml` = **263 cases** (+ `_harness.yaml`, `README.md`, `tests/fixtures/hooks/*.json`). Staging-only semantics → `tier: stretch` + `note` (never dropped). `errors.yaml` not created (not in my owned paths; B22's test_errors covers errors) |
| TEST-06 data-driven runner | done | `tests/e2e/test_cases.py` (per-case session, approvals cancelled after each case, stretch → xfail, DISABLED → skip, live → dry-run guard) |
| TEST-07 matrix + reports | done | `tests/lib/catalog.py` (37 controls), `matrix.py`, `report.py` (rich console, own junit writer, `results.json` `aegis.selftest/1`, `matrix.md`, offline dark `selftest.html` with filter JS, heatmap, perf, evidence), `plugin.py` (`aegis` marker capture, e2e auto-marker, audit_privacy last, hermetic_only skip in live, report writing in terminal summary) |
| TEST-08 coverage gate + secrets check | done | `tests/test_coverage.py` (cases + AST scan of `@pytest.mark.aegis` + golden inline tests; `AEGIS_ALLOW_UNTESTED`), `tests/test_no_committed_secrets.py` |
| TEST-13 feed suite | done | `tests/lib/fakes/feed.py` (ed25519 PyNaCl, re-signed seed bundle, publish/tamper/serve_serial/wrong_key), `tests/e2e/test_feed.py` E0–E5 all pass (activation recorded as `perf.feed_activation_ms`). E6 live variant not done |
| TEST-17 inline tests | done | `tests/e2e/test_inline_tests.py`: policy `/api/policy/validate` self-test results + 160+ feed signature vectors via `/v1/guard` (attributed by `Finding.detector`) — 165/165 pass |
| TEST-18 live mode | done | `LiveStack` (`AEGIS_LIVE_URL`, `AEGIS_LIVE_MOCK_LLM/MCP/SINK/FEED`, `AEGIS_LIVE_MUTATE`), dry-run guard cases, hermetic_only skipping, DISABLED/NOT_IMPLEMENTED from `/api/controls`, policy restore on stop |
| TEST-20 harness unit tests | done | `tests/unit/test_suite/test_harness_lib.py` (12 tests, ~4 s) |
| TEST-21 corpora rates (could) | done (light) | `tests/fixtures/corpora/*.jsonl` + `LICENSES.md`, `tests/e2e/test_corpora.py` (detection/FPR + Wilson CI into `results.json.perf.corpora`, obfuscation heatmap cells). PII fixture sampling (`tests/fixtures/pii/`) and `transforms.py` not done |

## Verification

| ID | Command | Result |
|---|---|---|
| TEST-V01 | `uv run --frozen pytest tests/unit/test_suite -q` | 12 passed, 4.2 s |
| TEST-V02 | `pytest tests/test_cases_schema.py tests/test_coverage.py tests/test_no_committed_secrets.py` | 5 passed; coverage table printed; 0 UNTESTED |
| TEST-V03 | e2e runs bind only 127.0.0.1:0; gateway/fakes threads stopped per module | verified by design + smoke (no 8787/879x binds; temp live gateway killed) |
| TEST-V04 | `make test-e2e` (`/usr/bin/time -l`) | **33.6 s wall, max RSS 267 MB**; 480 matrix entries: 440 pass · 15 pass_other · 22 xfail · **3 fail** (product gaps below) · 0 UNTESTED. Full `make test`: 105.8 s wall (incl. all workstreams' unit tests), max RSS 359 MB, 1910 passed; failures = the 3 product gaps + 2 other-bundle unit tests (`tests/unit/approvals_engine/test_integration.py::test_f5_budget_raise_end_to_end`, `tests/unit/audit_metrics/test_index_api.py::test_decisions_list_detail_and_audit_link`) |
| TEST-V05 | results.json schema + junit parse; selftest.html has no external URLs | ok |
| TEST-V06 | `AEGIS_TEST_OVERRIDES=<controls[id=DLP-02].enabled: false>` | DLP-02 row `DISABLED`, attack 0/6 (not counted as PASS) |
| TEST-V07 | judge add-a-line / typo | `expct:` → `tests/cases/dlp.yaml:<line>: <id>: extra field 'expct'` (unit-tested) |
| TEST-V08 | live mode vs a temp gateway on a free port | 85 entries: 76 pass, 1 pass_other, 2 xfail, 6 skip (hermetic-only feed), 0 fail; mode=live header |
| TEST-V12 | `pytest tests/e2e/test_feed.py` | 6/6 pass (update → block, tamper/rollback/wrong key rejected, last-good kept, withdraw unblocks) |
| TEST-V16 | `ruff check` + `ruff format --check` on owned paths | clean |
| TEST-V18 | integrated triage | partially: every seeded case triaged (contract fixes in YAML with `note:`; staging-only → stretch); 3 genuine product FAILs remain (below) |

## How to run / demo

- `make test` / `make test-e2e` → console matrix + `reports/{junit.xml,results.json,matrix.md,selftest.html}`.
- `make test-live` (with `make up` running) → same cases against the current policy (dry-run).
- Judge story: `tests/cases/README.md` ("add a line"). Open `reports/selftest.html` offline for the Proof beat.
- Other suites use: `aegis_stack` / `gw` fixtures, `make_stack(feed=True, mcp=True, overrides={...})`,
  `@pytest.mark.aegis(suite=..., control=..., polarity=..., expect=...)`, `tests.lib.policy_sandbox.PolicySandbox(gw)`,
  `tests.lib.privacy.register/scan_paths`, `tests.lib.sse.read_events`, `tests.lib.mcp_client.McpClient`.

## Product gaps found (core FAILs — do not fake green; owners please fix)

1. `CUS01-CODENAME-PL-NO-DIACRITICS` (semantic-models/B07): CUS-01 keyword leg misses "projekt sokol" (no diacritics) for the "Sokół" codename.
2. `DLP04-DNS-LABEL-EXFIL` (metadata-egress/B05): base64url PESEL in a DNS label of an egress URL is not blocked (only DLP-03 header strip → redact).
3. `INJ02-MENTION-NOT-USE` (threat-feed/B14): SIG-01 `AEGIS-TI-019` blocks the benign "write a pytest asserting we block 'ignore previous instructions'" (mention vs use).
4. Crash (no test failure, fail_mode absorbs it): `src/aegis/injection/canary.py:55` `extract_urls` → `IndexError: no such group` on `m.span(1)` for some `model.response` texts with URLs (injection-defense/B06; seen in `tests/e2e/test_corpora.py -s`, agentic_tools rows).

## deps_needed
none (pytest, httpx, asgi-lifespan, uvicorn, fastapi, pydantic, pyyaml, ruamel.yaml, pynacl, rich all present).

## contract_deviations
- Kill switch / proxy-block semantics follow Addendum A-07 (synthetic 200, 429 killed) in expectations.
- Benign `expect: allow` also accepts a final `redact` whose only non-allow enforce decision is **DLP-03** (metadata/header stripping, no entity redactions) — documented in `tests/lib/expect.py` (`TRANSPARENT`).
- Seeded cases corrected to contract semantics with `note:` (SF-04 external send → ACT-03 approval; DLP-02 AWS docs keys = log; ACT-04 force push → approval; MCP unknown server = block).
- Approval-routing cases (`approvals_routing.yaml`, via simulate) have `control: null` and land in the "Approvals & RBAC" suite row.
- `errors.yaml` not created (not in B21 owned paths).

## integration_todos
- Root `Makefile` already has the plan 18 §2.10 recipes (test, test-unit, test-e2e, test-sem, test-live) — no change needed.
- `config/snippets/test-suite.yaml` (8 cross-control golden tests) → policy-engine/integrator merges into top-level `tests:` of `config/policy.yaml` (+ golden).
- Fix the 3 FAILs + canary crash above (owners B07, B05, B14, B06), then re-run `make test` and commit a sample `reports/matrix.md` for the README (TEST-V18).
- `.gitignore`: keep `reports/` ignored except the A-54 evidence files.
- Partial runs (`pytest tests/e2e/<one file>`) also write `reports/*` (by design, so a judge running one suite gets a report); run `make test-e2e` last before committing evidence.
