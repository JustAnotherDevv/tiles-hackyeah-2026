# B01-gateway-core — status

Bundle: runtime, pipeline, discovery, app factory/CLI, health/events/ui, guard/playground.
Two agents: agent 1 (22:55–23:17) wrote all source files; agent 2 (resume) audited them against
CONTRACTS §3.3/§3.5 + Addendum A, added the missing verification suites, ran live smoke + lint.

## Tasks
| ID | State | Notes |
|---|---|---|
| GW-01 | done | settings, log (SecretScrubFilter), core.{crypto,paths,errors,deps}, runtime.get_runtime, app.create_app |
| GW-02 | done | EventBus (ring 1000, replay, since/Last-Event-ID, drop-oldest, thread-safe), db.connect (WAL), SessionStore + resolve_session_id |
| GW-03 | done | Runtime + SERVICE_TABLE (§3.3 order), Null fallbacks on import/create/start, component_status (A-16), Ollama probe (off in test mode) |
| GW-04 | done | discover_routers (ORDER, on_startup/on_shutdown), create_registry over `aegis.controls` + `aegis.integrations` (A-15), discover_adapters w/ built-in fallback |
| GW-05 | done | §3.5 steps 1–11 + A-01/02/03/04/05/08/09/10/14; complete() exactly once + `outcome` audit record; wire/attach_response/attach_request_preview/record_only |
| GW-06 | done | lifespan, pure-ASGI GuardMiddleware (413, admin token), envelope vs wire-format errors; CLI serve(--port 0/--port-file/--reload)/selftest/verify-audit/seed/reset/routes/version |
| GW-07 | done | /healthz (+/healthz/details), HEAD/GET /api/hello, /api/events SSE (no-cache, X-Accel-Buffering: no, heartbeat 15 s), ui.py ORDER 900 + SPA fallback + placeholder |
| GW-11 | done | /v1/guard (always 200, A-12 string destinations, artifact_b64, tool_args leaf segments, parked completions + TTL sweep), /v1/guard/complete, /api/playground (A-11 non-dry, ModelCall reuse, never 5xx) |

## Verification
| ID | Command | Result |
|---|---|---|
| GW-V01 | `AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off AEGIS_DATA_DIR=$(mktemp -d) uv run --frozen python -c "from aegis.app import create_app, route_table; ..."` | PASS — 111 routes from 23 routers, `plugin_errors == []` |
| GW-V02 | `uv run --frozen pytest tests/unit/core_gateway -q` | PASS — 76 tests, ~5 s, no fixed ports/network |
| GW-V03 | test_basics.py, test_bus_events.py | PASS |
| GW-V04 | test_runtime.py (create raises / start raises / import missing → Null, /healthz degraded, system events, broken control module → plugins degraded, duplicate id first-wins, `_` skipped) | PASS |
| GW-V05 | test_pipeline.py (33 cases: selection/scope/off, A-01 ctx.policy, precedence+tie-break, monitor (cfg + control-set A-04), A-03 allow rows + phase metrics, semantic skip / selftest no-skip / concurrency, timeouts closed/open/deterministic_only, late-completed task used, enrich ordering+errors, pre-approved/auto/denied/pending/wait/exception/Null approvals, dry-run isolation, redactor.apply + mutations, no mutations on block, redactor failure + internal error fail-closed, record once, complete once + outcome record, LRU eviction, new_context header/session/wait rules, response hop shares ctx) | PASS |
| GW-V10 | test_guard_playground.py (11) + test_bus_events.py + test_events_live.py (`@slow`, uvicorn port 0, real SSE `decision`) | PASS |
| GW-V11 | `python -m aegis serve --port 0 --port-file $PF` then curl `/api/hello`, `/healthz`, `/v1/guard`, `/api/events?replay=5`, `/` | PASS — 200 / HealthResponse / DLP-01 redacted PESEL+EMAIL live / SSE frames / 302; 33 controls, 0 fallbacks; clean shutdown |
| GW-V15 | `uv run --frozen ruff check <owned files> tests/unit/core_gateway` | PASS |

## Files
src/aegis/{__main__,app,settings,log}.py, src/aegis/core/{runtime,nulls,bus,db,sessions,discovery,pipeline,deps,errors,crypto,paths}.py,
src/aegis/api/routes/{health,events,guard,playground,ui}.py,
tests/unit/core_gateway/{conftest,gw_fakes,test_basics,test_bus_events,test_pipeline,test_runtime,test_guard_playground,test_events_live}.py

## How to run / demo
- `uv run python -m aegis serve` (default 127.0.0.1:8787) · `--port 0 --port-file /tmp/p` for ephemeral.
- `uv run python -m aegis routes` lists every discovered route; `/healthz/details` shows fallbacks + plugin errors.
- Guard: `curl -s localhost:8787/v1/guard -H 'content-type: application/json' -H 'X-Aegis-Agent: trading-copilot@trading' -d '{"interaction":{"surface":"prompt.user","text":"PESEL 44051401359 email jan@example.com"}}'`

## deps_needed
none.

## contract_deviations
- `/healthz` component `feed` reports `degraded` when the feed is in `seed` state (per plan §2.2 map), so overall `status` is `degraded` with `AEGIS_FEED_URL=disabled`. Integrator may prefer mapping `seed → ok` for the demo.
- Extra (additive) routes: `GET /healthz/details`, `GET|HEAD /ui` (→ 302 `/ui/`).
- Pipeline extras beyond the protocol: `build_summary`, `is_completed`, `audit_ref(decision_id)`.

## integration_todos
- `aegis.proxy.flow.ModelCall` (B02) is imported lazily in `src/aegis/api/routes/playground.py` (`playground()`), signature `ModelCall(rt, wire=, ctx=, source=, provider=, identity=, stream_mode=)`, `await run(body)` → needs `.verdict/.blocked/.status/.error/.response_raw_text/.response_local_text/.route`. Matches current B02 code; covered only by a fake in tests.
- `aegis.core.timing.server_timing_header(ctx, upstream_ms=)` (B02) used by guard/playground `Server-Timing`; local fallback in `guard._server_timing`.
- GW-V12 (overhead bench) / V13 / V14 belong to the integration window (B02 proxies + mocks).
- `python -m aegis --help` is routed to `serve --help` (bare flags default to `serve`).
