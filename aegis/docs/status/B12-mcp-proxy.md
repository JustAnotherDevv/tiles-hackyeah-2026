# B12-mcp-proxy — status

MCP proxy and mock MCP servers. Covers pinning, tool poisoning, rug pull and re-pin approvals (plan `docs/plan/11-mcp-proxy.md`).

Two agents worked on this bundle. Agent 1 wrote MCP-01 to MCP-08 (code and mocks). Agent 2 added the snippet, the tests, the e2e script, lint fixes and this report.

## Tasks

| ID | State | Notes |
|---|---|---|
| MCP-01 | done | Every public surface; `config/snippets/mcp-proxy.yaml` |
| MCP-02 | done | `aegis.mcp.jsonrpc` (guarded SDK imports), `aegis.mcp.detect` (tool-definition scan + `cross_reference`) |
| MCP-03 | done | `PinStore` on SQLite (`mcp_tools`, `mcp_tool_candidates`, `mcp_server_state`): in-memory cache, write-through |
| MCP-04 | done | Builders for `mcp.init/list/call/result`; write-back into `content[]` and `structuredContent`, with banner and `_meta` |
| MCP-05 | done | `McpGovernor` and `McpService`, routes `POST\|GET\|DELETE /mcp/{server}` for both eras over JSON and SSE. Includes the approval hold, fail-closed handling, 502 errors and `X-Aegis-*` / `Server-Timing` headers |
| MCP-06 | done | Controls MCP-01 (registry/launch), MCP-02 (poisoning: drop via `Mutation(remove)`, no spans), MCP-03 (pins/rug pull/collision) |
| MCP-07 | done | `mcp_pin` executor; `ensure_repin_approval` reuses an approval or cancels and recreates it; `/api/mcp/*` admin API; SSE `mcp.tool` and audit `mcp.tool_changed` |
| MCP-08 | done | `mocks/mock_mcp`: 9 servers on one port, both eras. `/_mock/{rugpull/flip,reset,requests,health}`, `--stdio NAME`. Port precedence is `--port` > `$AEGIS_MOCK_MCP_PORT` > 8792. Health returns `service: mock_mcp` |
| MCP-09 | done | `tests/unit/mcp_proxy/` (FakeRuntime and in-process mock): 50 tests |
| MCP-10 | done | Hot reload: list-cache invalidated per policy version (tested in V06) |
| MCP-11 | mostly done | Vet-on-first-use `scan_server` (throttled) and `POST /api/mcp/servers/{s}/scan`. The `scan_on_startup` param is accepted but not implemented |
| MCP-12 | done | `python -m aegis.mcp.claude_config` and `GET /api/mcp/claude-config` |
| MCP-13 | done | `python -m aegis.mcp.stdio` wrapper and `_stdio` endpoint (launch check, fail-closed); the e2e stdio check passes |
| MCP-14 | done | Control MCP-04: header mismatch, forbidden scopes, OAuth URL rules, bearer redaction |
| MCP-15 | done | `mocks/mock_mcp/demo_client.py` (official SDK, both eras plus stdio, F4) and `mocks/mock_mcp/e2e.py` |
| MCP-16 | done | MCP-03 collision (rapidfuzz, `collision_action` defaults to log) and MCP-02 `cross_reference` |
| MCP-17 | partial | Done: `resources/read` and `prompts/get` results are governed; `list_changed` marks the server stale and is audited; modern `ttlMs` is clamped to 0. Not done: `prompts/list`/`resources/list` scanning and a background re-scan |
| MCP-18 | done | Deny watcher (denied `mcp_pin` → quarantined; off in test mode) and the tool detail endpoint |
| MCP-19 | passive | `apply_call_verdict` writes back any rewritten `tool_args` segments, so DLP-08 rehydration works as soon as DLP-08 rewrites them |

## Verification

| ID | Command | Result |
|---|---|---|
| V01 | import smoke of all modules with `AEGIS_DATA_DIR=<tmp>` | **pass**: 0 files created |
| V02 | `AEGIS_SEMANTIC=off AEGIS_TEST_MODE=1 uv run --frozen pytest tests/unit/mcp_proxy -q` | **50 passed**. About 3 s without `test_integration_real_app.py`; about 30 s with it while the machine's load average was about 21 |
| V03 | `test_proxy_http.py` covers scenarios (a)–(g) in both eras, plus F4 hold→approve→same call proceeds, retry with an approval token, 502, fail-closed and overhead | **pass** |
| V04 | `test_mock_mcp.py`: 9 servers in both eras, flip changes the hash, reset, acme_db count > 0, PESEL checksums, marketpulse plans | **pass** |
| V05 | `uv run --frozen python -m mocks.mock_mcp.e2e` (free ports; kills only its own children) | **17/17 checks passed** |
| V06 | `test_admin_api.py::test_hot_reload`: MCP-02 off makes `add` visible; `on_tool_change: log` makes the tool callable; removing `weather` gives -32001 | **pass** |
| V07 | `test_admin_api.py`: shapes match the pydantic mirrors; member gets 403 `forbidden`; admin gets 200; `mcp.tool` keys are `{server,tool,status,reason}`; audit `mcp.tool_changed` is written | **pass** |
| V08 | live Claude Code run | **not run** (needs the full stack and Claude quota) |
| V09 | `test_overhead`: 200 calls through the proxy | **pass**: governance p50 ≈ 0.5 ms (FakeRuntime) |
| V10 | `python -m aegis selftest` | **pass**: 82/82, including the MCP-01 and MCP-02 inline tests |
| V11 | `ruff check` + `ruff format --check` on the owned paths | **clean** |
| V12 | stdio | **partial**: in-process `_stdio` test (launch check OK and mismatch, poisoned list dropped, call blocked) plus bridge fail-closed unit tests, and the e2e stdio check passes. There is no separate threaded-gateway spawn test |

The real-app integration (`test_integration_real_app.py`) runs `aegis.app.create_app()` with the in-process mock and passes:
- F9: poisoned tool dropped; rug pull blocked; sponsor gets 403 and admin re-pins; unknown server gets 404.
- F4: the `marketpulse.purchase_subscription($50)` call is held, an admin approves through `/api/approvals/{id}/approve`, and the same held call goes through, reaching the mock exactly once.

## Files
- `src/aegis/mcp/{__init__,jsonrpc,detect,pins,interactions,proxy,service,events,inventory,client,stdio,claude_config}.py`
- `src/aegis/controls/mcp/mcp0{1_registry,2_poisoning,3_pinning,4_auth}.py`
- `src/aegis/api/routes/{mcp,mcp_admin}.py`
- `config/snippets/mcp-proxy.yaml`
- `mocks/mock_mcp/{__init__,__main__,app,state,seed_db,demo_client,e2e}.py`
- `mocks/mock_mcp/servers/*.py` (9 servers)
- `tests/unit/mcp_proxy/{fakes,conftest,test_proxy_http,test_admin_api,test_controls,test_wire_pins_detect,test_mock_mcp,test_integration_real_app}.py`

## How to run / demo
- Mock: `python -m mocks.mock_mcp` (port 8792). Rug pull: `curl -XPOST :8792/_mock/rugpull/flip`. Reset: `curl -XPOST :8792/_mock/reset`.
- Pin reset before a demo: `curl -XPOST :8787/api/mcp/reset -H 'X-Aegis-View-As: u_marek'`.
- Claude config: `python -m aegis.mcp.claude_config --servers acme-db,acme-crm,mailer,web,weather,poisoned,rugpull > demo/claude/mcp.json`.
- Full self-check: `uv run --frozen python -m mocks.mock_mcp.e2e`.
- SDK agents should use `aegis.mcp.client.McpHttpClient(base, server, headers={"X-Aegis-Agent": ...})`.

## deps_needed
None. `mcp==2.3.0`, `asgi-lifespan`, `rapidfuzz` and `google-re2` are already in the venv.

## contract_deviations
- The unknown-server JSON-RPC message reads `"[Aegis] Blocked by MCP-01: unknown MCP server '<name>' (not in mcp.servers)"`. A-46 gives the shorter `"[Aegis] unknown MCP server <name>"`. The code (-32001) and HTTP 404 match.
- `mcp_pin` drafts carry both `labels.dest` (A-21) and `labels.destination` (plan); this is additive.
- `/_mock/health` returns `{service:"mock_mcp", ok, servers, rugpull_flipped}`, a superset of A-46.

## integration_todos
1. **policy-engine (`config/policy.yaml`)**: add the `poisoned-stdio` server from `config/snippets/mcp-proxy.yaml` to `mcp.servers`. Without it, the stdio demo and the generated Claude config for `poisoned-stdio` are blocked by MCP-01. Optionally switch the mock URLs to `${AEGIS_MOCK_MCP_PORT:-8792}` (A-35).
2. **action-guards (EXE-02, `src/aegis/controls/actions/exe02_scope.py`)**: on `mcp.call`, EXE-02 treats `interaction.url` (the registered upstream MCP server URL) as an SSRF target. It currently passes only because of `allow_hosts: ["127.0.0.1:8791-8799"]`; any other mock port gets `Blocked by EXE-02: loopback`. Consider skipping `interaction.url` when `kind == "mcp"`, since MCP-01 governs the registry. `mocks/mock_mcp/e2e.py` adds its port to the temp policy as a workaround.
3. **demo-mocks-docs (`scripts/run_stack.py`, demo preflight)**: start `python -m mocks.mock_mcp`. In the preflight, call `POST /api/mcp/reset` with `X-Aegis-View-As: u_marek`, then `POST :8792/_mock/reset`.
4. **claude-code-integration**: generate `demo/claude/mcp.json` with the claude_config CLI (MCP-V08 still to be run live).
5. **FYI injection-defense**: during `python -m aegis selftest`, INJ-04 logs `IndexError: no such group` (degraded allow). This is not an MCP problem.
