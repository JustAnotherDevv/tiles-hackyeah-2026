# B02-gateway-proxy — status

Model data plane: provider adapters, router, upstream, buffered/passthrough streaming, `ModelCall`
flow, and the `/v1/messages`, `/v1/chat/completions`, `/openai/v1/chat/completions`,
`/ollama/{path}` and `GET /v1/models` routes.

## Tasks
| ID | Priority | State | Notes |
|---|---|---|---|
| GW-08 | must | done | `proxy/router.py` (resolve_route, wire filter, enabled_if_env, `:cloud` ⇒ remote, built-in providers/routes), `proxy/upstream.py` (shared client, `set_transport`, header policy, 502), `adapters/anthropic.py` |
| GW-09 | must | done | `proxy/sse.py` (port), `proxy/streaming.py` (3-wire accumulators/synthesizers, keep-alives), `proxy/flow.py` `ModelCall`, `routes/proxy_anthropic.py` (`/v1/messages`, `count_tokens`) |
| GW-10 | must | done | `adapters/openai.py` (`prepare_openai_request`, usage-chunk hiding), `routes/proxy_openai.py` |
| GW-12 | should | done | `adapters/ollama.py`, `routes/proxy_ollama.py` (chat/generate via flow, `model.admin` ops evaluated + relayed, passthrough for the rest), `GET /v1/models` |
| GW-13 | should | done | per-control `ctl-<ID>` Server-Timing (top 8), `X-Aegis-Budget-Remaining` (A-06 headers, plus a `ctx.state["bud.remaining"]` fallback), `-Downgraded-From`, `-Approval-Id`, `-Response-Decision-Id`; Ollama up/down `system` bus toasts (from the `/v1/models` tags probe). `observe_overhead` phases are emitted by B01's pipeline |
| GW-14 | should | done | `stream_mode: passthrough` (tee accumulator, `record_only`, `complete()` in finally, disconnect-safe); `count_tokens` forwards the dry-run-redacted body for remote providers, local estimate otherwise; `holdback` ⇒ WARNING once + buffered |
| GW-15 | should | done | `config/snippets/core-gateway.yaml` (validates as `PolicyDoc`; added a note that deterministic controls need `timeout_ms` ≥ 50) |
| GW-16 | could | not started | holdback streaming (30 min stretch). `holdback` falls back to buffered |
| GW-17 | could | done | `flow.fresh_segments()` ⇒ `interaction.meta["fresh_segments"]` (session sha256 LRU); orjson fast path + raw-bytes forwarding when unchanged; 1 MB body measured |

## Verification
All commands use `AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off`.

| ID | Result | Command / evidence |
|---|---|---|
| GW-V06 | PASS | `uv run --frozen pytest -q tests/unit/core_gateway_proxy/test_adapters.py` |
| GW-V07 | PASS | `.../test_streaming.py` (+ OpenAI usage hidden/asked in `test_openai_ollama_routes.py`) |
| GW-V08 | PASS | `.../test_proxy_anthropic.py`, `.../test_openai_ollama_routes.py` (JSON+SSE, OAuth passthrough, no x-aegis-* upstream, block ⇒ 200, 402/429, 403 error style, upstream error verbatim, 502). `HEAD /api/hello` is B01's route and is not tested here |
| GW-V09 | PASS | `.../test_redact_rehydrate.py` (upstream sees `[EMAIL_1]`, client gets the original, WireView fields set, tool_use never rehydrated) |
| GW-V12 | PASS | `uv run --frozen pytest -q -s tests/unit/core_gateway_proxy/test_overhead.py`. Real `Pipeline`, 3 controls × 2 hops, 300 calls: **p50 0.66 ms, p95 1.09 ms** (limits: 5/15 ms). 1.03 MB Claude Code-sized body: p50 3.2 ms |
| GW-V13 | PASS (in-process) | `.../test_integration_v13.py` (marked `slow`): real `create_app` + Runtime (33 controls, `config/policy.yaml`) with a MockTransport echo upstream in place of `mocks/mock_llm` (not built yet). trading-copilot@trading + PESEL + email: upstream saw `[PESEL_1]`/`[EMAIL_1]`, client got the real values, `X-Aegis-Decision: redact`, `X-Aegis-Redactions: 2`, `X-Aegis-Budget-Remaining` set, decision row present. Warm overhead ~4.4 ms with all real controls |
| GW-V14 | NOT RUN | Manual: a real Claude Code session against the running stack uses a little subscription quota. Integrator/user step |

Full owned suite: **67 passed in ~6 s** (`uv run --frozen pytest -q tests/unit/core_gateway_proxy`). `ruff check` on all owned src and test paths: clean.

## Files
- src: `src/aegis/core/timing.py`, `src/aegis/proxy/{__init__,router,upstream,blocking,sse,streaming,jpath,flow}.py`, `src/aegis/proxy/adapters/{__init__,_common,anthropic,openai,ollama}.py`, `src/aegis/api/routes/proxy_{anthropic,openai,ollama}.py`
- config: `config/snippets/core-gateway.yaml`
- tests: `tests/unit/core_gateway_proxy/{conftest,fakes,streams,test_adapters,test_streaming,test_proxy_anthropic,test_redact_rehydrate,test_router_upstream_timing,test_openai_ollama_routes,test_overhead,test_integration_v13}.py` and `fixtures/`

## How to run / demo
- Gateway: `make gateway`. Then `curl -s localhost:8787/v1/messages -H 'x-aegis-agent: trading-copilot@trading' -d '{"model":"mock-echo","max_tokens":64,"messages":[{"role":"user","content":"PESEL 44051401359 jan@example.com"}]}' -i`. Check the `X-Aegis-*` and `Server-Timing` headers. This needs `mocks/mock_llm` on :8791; without it the call returns 502 `upstream_error`.
- Claude Code: `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`. OAuth is forwarded only to `anthropic` (`passthrough_auth: true`).
- Overhead numbers for the deck: `uv run --frozen pytest -q -s -m bench tests/unit/core_gateway_proxy/test_overhead.py`.

## deps_needed
None. orjson is optional; a stdlib json fallback is used if it is missing.

## contract_deviations
- `fresh_segments` (GW-17) is an additive `interaction.meta` hint. Controls may ignore it.
- `X-Aegis-Budget-Remaining` is also read from `ctx.state["bud.remaining"]` (plan 01 §4.3 #1), in addition to the A-06 `meta.response_headers`.

## integration_todos
1. `mocks/mock_llm` (demo-mocks-docs) does not exist yet. GW-V13 with `make up` + curl + `/_mock/requests` must be re-run once it exists. The in-process test covers the same logic.
2. The audit scrubber (B15, `aegis.audit.privacy`) warns "audit scrubber replaced sensitive values … count=4" on every model call. It redacts `destination.host`/`url` `127.0.0.1` as `[REDACTED:IP_ADDRESS]` in decision rows (seen in `/api/decisions`). B15 should allowlist loopback/destination fields.
3. GW-V14 (manual Claude Code passthrough) is for the integration window. Run `cd demo/claude/project && claude -p 'say hi' --settings ../settings.json --model haiku`.
4. The first request after startup has ~55 ms overhead (control warm-up, cold imports). Later requests take ~4 ms. A warm-up request at startup (B01/B15 `metrics/warmup.py`) would hide this in the demo.
5. GW-16 holdback is not implemented. `stream_mode: holdback` in policy logs a warning and behaves as `buffered`.
