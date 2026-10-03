# B20-demo-stack: status

Bundle: mock LLM, exfil sink, mock SaaS, `aegis.sdk`, `scripts/run_stack.py`, preflight, and reset. The plan is `docs/plan/20-demo-mocks-docs.md`, implementer A's half.

## Tasks

| ID | State | Notes |
|---|---|---|
| DEMO-01 | done | `mocks/__init__.py` provides PORTS, PORT_ENV, `host_map`, `mock_data_dir`, RequestLog, `safe_headers`, `masked_preview`, `run_cli` and `serve_many`. It was written by the previous agent and kept. Each mock has `create_app()` and `GET /_mock/health` → `{service}`. The snippet, the test `conftest.py` and the run_stack `--check` / `--dry-run` flags are in place. |
| DEMO-02 | done | `mocks/mock_llm/`: `app.py`, `script.py` (triggers), `anthropic_wire.py` (JSON + SSE), `openai_wire.py` (JSON + chunks, `include_usage`, `[DONE]`), `fakegen.py` (from the previous agent) and `__main__.py`. Supported triggers: EMIT_SECRET (the key is split across exactly 3 deltas), EMIT_PII, EMIT_MD_EXFIL, EMIT_CANARY, EMIT_ECHOLEAK_PROXY, TOOL_USE, LONG, SLOW and ERROR. Usage is `ceil(chars/4)`, and output tokens are capped by `max_tokens`. Inspection endpoints: `/_mock/requests` (GET/DELETE), `/_mock/scan`, `/_mock/reset`, `/v1/models`, `/v1/messages/count_tokens`. Planner mode (DEMO-17) is not built. |
| DEMO-03 | done | `mocks/exfil_sink/` has a catch-all recorder, CORS on `/_mock/hits`, a 1×1 PNG for image paths and a `/_mock/ui` counter page (`ui.html`). `mocks/mock_saas/` has subscriptions with a catalog price check (400 "price mismatch", 404 for unknown plans), charges, `/_mock/charges`, plans from the seed (including a100-cluster-week at $1,500), seeded CRM contacts (checksum-valid PESEL and IBAN), a webhook endpoint, paste, request log and reset. |
| DEMO-04 | done | `src/aegis/sdk/` (client, admin, mcp, results, cast) was written by the previous agent. I verified it with the new `test_sdk.py`. |
| DEMO-05 | done | `scripts/run_stack.py` runs the steps in this order: keygen `--if-missing`, mocks (one process, via the `_mocks` subcommand), mock_mcp, feed, gateway. It covers health waits, prefixed logs teed to `data/logs/`, pidfiles in `data/run/`, a status table with RSS, a RAM and `web/dist` check, an Ollama hint, and port identification (ours / stale / staging spike / foreign via lsof, never killed). Flags: `--kill-stale`, `--port-offset`, `--auto-ports`, `--restart`, `--watch`, `--demo` / `--lean` / `--warmup` / `--ambient` (warm-up and ambient scripts are skipped when absent) and `--check` / `--dry-run`. Shutdown sends SIGTERM in reverse order with a 5 s grace period, then SIGKILL. |
| DEMO-07 | done | `demo/preflight.py` gives READY, READY (degraded: …) or NOT READY, with exit code 0, 1 or 2. Options: `--json`, `--quick`, `--no-warm`, `--unload-others`, `--reset`. It checks the gateway and its components, the 4 mocks, the attacker counter, policy, org cast, kill switches, pending approvals, the chaos budget, MCP pins, the feed (with a warning if TI-022 is already published), two smoke guard probes (PII → redact, a runtime-generated AWS key → block), `/ui`, RAM, Ollama models (warm-up with `keep_alive` 60m), and the Claude CLI and settings. `demo/scenarios/reset.py` resets the mocks, cancels pending approvals, resets budgets, releases kill switches, hard-resets the feed and refreshes it, and resets MCP pins. Options: `--stop-ambient` and `--policy-golden` (rolls back to the first policy version). Each step degrades to `skip` instead of failing. |
| DEMO-19 (could) | not started | `--auto-ports` only exports `AEGIS_MOCK_*_PORT`, which relies on policy-engine env expansion (A-35). There is no policy patch fallback. |

## Verification

All commands run from the repo root.

| ID | Command | Result |
|---|---|---|
| V01 | `uv run --frozen python -c "import aegis.sdk as s, mocks.mock_llm.app, mocks.exfil_sink.app, mocks.mock_saas.app; print(s.AegisClient, s.DEMO_AGENTS['chaos-agent@platform'][:16])"` and `ruff check` on all owned paths | PASS (prints `aegis_demo_chaos`; ruff clean) |
| V02 | `AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off uv run --frozen pytest tests/unit/demo_mocks_docs/test_mock_llm.py -q` | PASS (12 tests) |
| V03 | `pytest tests/unit/demo_mocks_docs/test_exfil_sink.py tests/unit/demo_mocks_docs/test_mock_saas.py -q` | PASS (7 tests) |
| V04 | `pytest tests/unit/demo_mocks_docs/test_sdk.py -q` (MockTransport covers: guard body and headers, synthetic block, pending approval, 402/429/429-killed/Anthropic 403 errors, egress approval fields, wait `/wait`, legacy MCP over JSON and SSE with session reuse and an isError control id, admin view-as) | PASS (13 tests) |
| V05 | `pytest tests/unit/demo_mocks_docs/test_run_stack.py -q` and `uv run --frozen python scripts/run_stack.py --dry-run --port-offset 100` | PASS. The dry run prints mocks 8891/8893/8894, mcp 8892, feed 8890, gateway 8887 and a matching `AEGIS_HOST_MAP`. |
| V06 | `python -m mocks.mock_llm --port 0 --port-file F` with curl SSE `[[EMIT_SECRET]]` | PASS. The SSE is well-formed, the key is split over 3 deltas, and the process exits 0 on SIGTERM. The `_mocks` combined process was also tested on 3 ephemeral ports: all healthy, clean exit. |
| (extra) | `pytest tests/unit/demo_mocks_docs -q` | PASS: 41 tests, about 10 s |
| V07 | Integration window only | PARTIAL. I did not start the stack. Another agent's stack was already running on 8787/8791–8794. `run_stack.py --check` identified all 5 as "Aegis service already running" and killed nothing. A read-only `preflight.py --quick --no-warm` against it gave `READY (degraded: gateway, components, threat feed, RAM)`: the feed service :8790 was down, Ollama was down from the gateway's view, 1.1 GB RAM was free, and both smoke probes passed. I did not run `--reset`, so their state was not touched. |
| V16 | Integration window only | NOT RUN. The probe that detects the staging spike (GET `/admin/reset` → 405) is implemented but untested against the real spike. |

## Files created or changed (all within owned paths)

- `mocks/mock_llm/{__init__,__main__,app,script,anthropic_wire,openai_wire}.py` (`fakegen.py` was kept as found)
- `mocks/exfil_sink/{__init__,__main__,app}.py`, `mocks/exfil_sink/ui.html`
- `mocks/mock_saas/{__init__,__main__,app,fakedata}.py`
- `scripts/run_stack.py`, `demo/preflight.py`, `demo/scenarios/reset.py`
- `config/snippets/demo-mocks-docs.yaml`: two demo invariant tests. Everything else the demo needs is already in `docs/seed-fixes/policy.yaml` and is listed there as comments.
- `tests/unit/demo_mocks_docs/{__init__,conftest,test_mock_llm,test_exfil_sink,test_mock_saas,test_sdk,test_run_stack,test_preflight_reset}.py`
- Kept unchanged: `mocks/__init__.py`, `src/aegis/sdk/*` (previous agent)

## How to run

- Whole stack: `uv run --frozen python scripts/run_stack.py --lean` (or `--demo`). Check first with `--check`; preview with `--dry-run`.
- A single mock: `uv run --frozen python -m mocks.mock_llm [--port 0 --port-file F]`, and the same for `exfil_sink` and `mock_saas`.
- Between judges: `uv run --frozen python demo/preflight.py --reset`. Quick check: `demo/preflight.py --quick`.
- Attacker counter page: `http://127.0.0.1:8793/_mock/ui`. Proof of what left the gateway: `GET :8791/_mock/requests` and `POST :8791/_mock/scan {values:[...]}`.

## deps_needed

None. Everything used is already in the manifests: fastapi, uvicorn, httpx, rich, psutil, pyyaml.

## contract_deviations

- mock_saas returns **404** "unknown plan" when the vendor/plan pair is not in the catalog. A-56 only specifies 400 "price mismatch" for a wrong amount.
- mock_llm caps output at `max_tokens` (`stop_reason: max_tokens` / `finish_reason: length`). This keeps the A-5 runaway math realistic: `[[LONG:20000]]` with `max_tokens: 4096` reaches the $0.50 wall in about 7–8 calls.
- The echo includes the raw trigger text, for example `[[EMIT_SECRET]]`. Triggers are parsed only from the last user or tool turn.

## integration_todos

1. **Root Makefile** (scaffold or integrator; A-58). Add these lines:
   ```make
   up:  ## start the whole demo stack (gateway + feed + mocks)
   	uv run --frozen python scripts/run_stack.py --lean
   demo:  ## stack + warm-up + preflight
   	uv run --frozen python scripts/run_stack.py --demo
   demo-preflight:  ## READY / DEGRADED / NOT READY (ARGS=--reset|--quick|--json)
   	uv run --frozen python demo/preflight.py $(ARGS)
   demo-reset:  ## reset demo state between judges
   	uv run --frozen python demo/scenarios/reset.py $(ARGS)
   stack-check:  ## port/identity check without starting anything
   	uv run --frozen python scripts/run_stack.py --check
   ```
2. **Policy merge**: merge `config/snippets/demo-mocks-docs.yaml` `tests:` (2 entries) into `config/policy.yaml`. The `demo-chaos-hard-cap` test expects ACT-01 to block $5,000.01 for chaos-agent.
3. **A-35 env expansion** (policy-engine): `--auto-ports` and `--port-offset` move the mocks, but the policy `providers.mock-*.base_url` and `mcp.servers.*.url` only follow if `${AEGIS_MOCK_*_PORT:-…}` expansion is implemented. If it isn't, use the default ports (DEMO-19 fallback not built).
4. **Ambient pidfile**: `reset.py --stop-ambient` expects `data/run/ambient.pid` (an int or `{"pid": n}`). B23's `ambient.py` should write it.
5. **Preflight `--reset` with the feed**: feed reset calls `POST :8790/api/reset {"hard": true}`, which matches A-11's `reset --hard`, and then `POST /api/feed/refresh` on the gateway.
6. V07 and V16 are still to be run in the integration window. `make up`, then `preflight --reset`, should give READY or a named DEGRADED list. For V16, run the staging MCP spike, then `run_stack.py --check` should report "staging MCP spike".
7. Note for the orchestrator: when I finished, a stack started by another agent was still running (pids 76654–76658: `mocks.mock_llm`, `mock_mcp`, `exfil_sink`, `mock_saas`, `aegis serve`). I did not touch it.
