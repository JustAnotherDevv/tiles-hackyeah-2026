# Spike: MCP governance proxy

**Status (2026-10-03): works end to end.** `./run_demo.sh` → 16/16 checks pass using the official `mcp` 2.3.0 SDK client in both protocol eras plus the stdio wrapper. Claude Code 2.1.271 (`claude -p`, spike-only config, `--strict-mcp-config`): poisoned tool hidden over HTTP and stdio, rug pull caught in session 2, secret-in-args blocked with the reason relayed by Claude, PII argument redacted. Governance overhead: `tools/list` median 335 µs (max 673), `tools/call` request median 14 µs, result scan median 119 µs.

## Run it
- `./run_demo.sh` — starts fake servers + proxy, runs the demo client, stops everything.
- `./run_demo.sh --with-claude` — also one tiny `claude -p` through the proxy.
- Ports: fake servers 8791 (crm), 8792 (poisoned), 8793 (rugpull); proxy 8796 (avoids the gateway's 8787). Logs in `$TMPDIR/aegis-mcp-spike/`; decision events in `proxy.jsonl`.

| File | Role |
|---|---|
| `aegis_mcp/detectors.py` | Pure functions: tool-definition poisoning scan (MCP-02); argument scan for secrets, PII (PESEL/IBAN/Luhn validators) and base64/hex blobs (decoded and re-scanned); result injection scan (INJ-01); `redact()`; `sanitize_injection()`. |
| `aegis_mcp/pins.py` | Trust-on-first-use `PinStore`: SHA-256 of each tool's canonical JSON; tools are pinned or quarantined (poisoned / changed / new after first complete listing); diffs, `approve()`, optional atomic JSON file. |
| `aegis_mcp/governor.py` | Transport-agnostic core: `on_client_message(ctx, msg)` → forward or respond; `on_server_message(ctx, msg, request)` → possibly rewritten message. |
| `aegis_mcp/protocol.py` | Era detection; 2026-07-28 header checks and recomputation (reuses the SDK's `mcp.shared.inbound`); SSE codec; synthetic results. |
| `aegis_mcp/http_router.py` | `build_mcp_router(governor)` — FastAPI `APIRouter` for POST/GET/DELETE `/mcp/{server}`; `build_admin_router()` — pins, approve, events, reset. |
| `aegis_mcp/stdio_wrapper.py` | `python -m aegis_mcp.stdio_wrapper --server X --policy catalog.json -- <real cmd>` |
| `aegis_mcp/events.py`, `policy.py`, `catalog.json` | Decision events and sinks; server catalog (url, trust zone, injected upstream headers, allow/deny lists) and per-check actions. |
| `fake_servers.py` | `crm` (benign, but customer C-6666 carries an injection in notes), `poisoned` (`add` has an `<IMPORTANT>` block; `get_weather` clean), `rugpull` (definition changes after the first listing). |
| `demo_client.py` | Demo + self-test (non-zero exit on failure). |
| `claude/spike.mcp.json` | Spike-only Claude Code config: three HTTP servers via the proxy, one stdio server via the wrapper. |

## Design
Transparent, message-level proxy (research 02 §2.2): HTTP passes through as-is (`Mcp-Session-Id`, `MCP-Protocol-Version`, other `Mcp-*` headers, SSE framing, keep-alive comments); every JSON-RPC body and SSE event is parsed but rewritten only when the governor decides; sessions stay with the upstream, so one code path serves both protocol eras.
- **`tools/list` — poisoning scan (MCP-02):** scans name, title, description, annotations and every string in input/output schemas; score ≥ 3 (high = 3, medium = 1) → removed and quarantined.
- **`tools/list` — pinning (MCP-03):** pins keyed by catalog server name (not session); a tool whose hash changed, or that appears after the first complete listing, is hidden and its calls blocked; alert event carries both hashes + diff; `POST /aegis/mcp/pins/{s}/{t}/approve` re-pins.
- **`tools/call` request:** only pinned tools callable; allow/deny lists (GOV-03); blocked calls get a synthetic result with `isError: true` naming the control and an incident id; nothing reaches upstream.
- **`tools/call` arguments:** block secrets (DLP-02) and base64/hex blobs that decode to secrets/injections (DLP-04); block ≥512-char blobs to external servers; redact PII (DLP-01) to placeholders like `[EMAIL_1]` for external servers; on 2026-07-28 recompute `Mcp-Name` / `Mcp-Param-*` after any rewrite.
- **Results (`tools/call`, `resources/read`, `prompts/get`):** neutralize injection text (INJ-01) and redact secrets (DLP-05) in BOTH `content[]` and `structuredContent`; add a warning banner and `_meta["io.aegis/decision"]`.
- **2026 header/body mismatch:** duplicated routing headers or headers disagreeing with body/pinned schema → HTTP 400 + JSON-RPC -32020 (request-smuggling defense).
- **Unknown server / bad `Origin`:** 404 / 403.
- **Notifications & server requests:** `notifications/tools/list_changed`, sampling/elicitation and the new `input_required` results are passed through and logged.

Decision events: one JSON line each — `type, id, ts, server, method, tool, decision, direction, controls[], reasons[], findings[], detail{diff, hidden, placeholders, policy_version}, transport, era, session, latency_us`; decisions `allow | redact | block | hide | sanitize | alert | observe`. Secret/PII evidence is masked (e.g. `AKIA…(20 chars)`); injection/tool-definition matches logged verbatim up to 80 chars.

## Protocol gotchas (verified)
1. Claude Code 2.1.271 speaks **2026-07-28 over HTTP** (`server/discover` probe, no `initialize`, no session id, `_meta` envelope on every request) but **legacy `initialize` (2025-11-25) over stdio**.
2. Era routing is header-first (SDK goes stateless only if `MCP-Protocol-Version` is present and not a handshake version); the proxy also treats a body `_meta` protocolVersion as modern so omitting the header can't slip through.
3. **Redacting a header-mirrored argument breaks the call unless headers are recomputed** (`x-mcp-header` args are copied into `Mcp-Param-<Name>`; otherwise 400 -32020). The proxy rebuilds `Mcp-Method`, `Mcp-Name`, `Mcp-Param-*` from the rewritten body using the pinned input schema — validated with Claude Code.
4. Decide on the body, never on headers (`classify_inbound_request`, `validate_mcp_param_headers`, `find_duplicated_routing_header`). On -32020 the SDK client re-lists once and resends — harmless.
5. Modern results need `resultType: "complete"`; add it only in the modern era (strict legacy TS clients reject unknown keys).
6. The 2026 client caches `tools/list` (`ttlMs` / `cacheScope`); the demo disables it with `cache=None`. The real defense is the pin check on `tools/call`.
7. Hidden tools have no client-side header map, so calls carry no `Mcp-Param-*` — fine, they're blocked anyway.
8. SSE: Python SDK uses CRLF; keep `:` keep-alive comments; 2026 servers answer in JSON unless they emit notifications/pings — handle both content types on every response; incremental UTF-8 decoder; `x-accel-buffering: no`.
9. Legacy plumbing: pass the session id both ways; pass through DELETE and the long-lived GET stream (no short read timeout); refuse JSON-RPC batches (removed in 2025-06-18).
10. Don't forward `Host` (upstream DNS-rebinding guard), `Authorization`, `Cookie` (token passthrough is a spec MUST NOT — the catalog injects per-server credentials). Check `Origin` in the proxy; bind 127.0.0.1.
11. SDK servers duplicate results into `content[]` and `structuredContent`, and **Claude Code displayed the `structuredContent` JSON** — sanitizing only `content[]` would let injections through; the banner may go unseen by the model.
12. Return blocks as `isError` results, not JSON-RPC errors — Claude Code relayed "[aegis] Blocked call … (DLP-02). Incident …" and continued cleanly.
13. Pinning catches what scanning misses: the rug-pull v2 description scores 0 on the poisoning scan; only the hash catches it. Whole-tool hashing (incl. `_meta`) is strict — volatile fields need a per-server normalization allowlist.
14. stdio: stdout is JSON-RPC only → events to stderr or `--events-file`; keep a request-id → request map; preserve per-direction ordering; fail closed on `tools/call` if governance errors.
15. `mcp` 2.3.0 API differs from 1.x: `MCPServer` replaces FastMCP; `Client(url, mode="legacy"|"auto"|"2026-07-28", cache=…)`; one `streamable_http_app()` serves both eras on the same path; declare `x-mcp-header` via `Field(json_schema_extra={"x-mcp-header": "Name"})`.
16. Demo prompts must read as ordinary tasks — Haiku refused a "security test" prompt with a key-like string; "open two CRM tickets…" went through.

## Claude Code wiring
- `claude -p "…" --mcp-config claude/spike.mcp.json --strict-mcp-config --allowedTools mcp__crm__lookup_customer --model haiku --no-session-persistence < /dev/null`
- Put the prompt before `--mcp-config` (it takes multiple values); `< /dev/null` avoids a 3 s stdin wait; `--bare` is unusable (requires `ANTHROPIC_API_KEY`, no OAuth).
- stdio entry: `uv run … python -m aegis_mcp.stdio_wrapper … -- python fake_servers.py --stdio poisoned` with `env.PYTHONPATH`; absolute paths are machine-specific — the gateway should generate this config.
- Observed: Claude Code saw `get_weather` from both poisoned servers but never `add`; `rugpull__get_exchange_rate` visible in session 1, gone in session 2.
- Production: gateway serves `/mcp/<name>` on 8787; point Claude Code at it via `.mcp.json` / `--mcp-config`; hardening (managed MCP / `allowedMcpServers`, PreToolUse hook) per research 02 §3 — not installed by the spike.

## Integrating into the gateway
```python
governor = Governor(Policy.from_dict(catalog["mcp"]), PinStore(...), sink=gateway_sink)
app.include_router(build_mcp_router(governor))   # its lifespan closes its own httpx client
app.include_router(build_admin_router(governor, prefix="/api/mcp"))
```
- Move `aegis_mcp/` in as-is (no gateway imports). Deps: `mcp>=2.3` (header helpers + protocol constants), `fastapi`, `httpx`. Pass `client=` to share the gateway's HTTP pool.
- Hot reload: `governor.policy = Policy.from_dict(new_yaml["mcp"])` is an atomic swap; events already carry `policy_version`.
- Event sink → hash-chained audit log, Prometheus counters, SSE bus for the dashboard.
- Pins/approvals: back `PinStore` with SQLite (same methods); route `approve()` through the org approval flow (admin role) with the stored diff shown in the dashboard's MCP inventory.
- Detectors: swap spike regexes for the signed signature feed (research 04) and the redaction engine (research 07 — vault placeholders, HMAC fingerprints, re2); keep the `Finding` contract; add Prompt Guard behind the scan functions with a timeout.
- stdio wrapper: call the gateway over loopback (`POST /v1/mcp/decide`), small allow-cache, fail closed for `tools/call`.
- Tests: lift `demo_client.py` scenarios and the fake servers (ports 8791–8799) into the self-test suite.

## Not done
Poisoning scans of `prompts/list` / `resources/list`; cross-server shadowing and typosquat checks; governing sampling inside `input_required` and `subscriptions/listen`; per-tool budgets; vault rehydration; upstream OAuth broker; 403/404 are FastAPI-style JSON rather than JSON-RPC errors; paginated `tools/list` untested.
