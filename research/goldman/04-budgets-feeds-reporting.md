# 04: Budgets, attack signature feed, reporting and telemetry

**Track:** Goldman Sachs "AI Control Layer" at HackYeah 2026 (Kraków, 3–4 Oct 2026)
**Scope:** research and planning only. Nothing installed, no code written.
**Covers these brief requirements:** budget and resource governance, historical attack mitigation using an externally managed feed, and security reporting with auditing and performance telemetry.
**Scoring weights it affects:** guardrail robustness 30%, architecture and performance 20%, security reporting 20%, tests 15%, implementability and scalability 15%.

---

## 0. Summary of decisions

| Area | Decision |
|---|---|
| Budget unit | One ledger with several **dimensions**: `usd`, `tokens_in`, `tokens_out`, `local_compute_s`, `requests`, `tool_calls`, `steps`, `wall_s`. Local (Ollama) models get a configurable shadow price per compute-second, so their cost shows up in USD too. |
| Hierarchy | `org → team → agent → session`, plus optional per-model and per-tool limits. A request has to pass **every** level (AND). This is deliberately different from LiteLLM, where a key in a team only enforces the team budget. |
| Accounting | **Reserve, then settle.** Before the call, reserve the estimated maximum cost (input tokens counted, `max_tokens` clamped). After the call, settle on the provider's reported usage. During streaming, enforce mid-stream and cut the stream if a budget is crossed. |
| Runaway agents | Limits on maximum steps, tool calls, wall time, context size and output size. A **loop detector** catches exact repeats, short cycles (A→B→A→B), no-progress calls (same call, same result), error streaks and burn-rate spikes. |
| When a limit is exceeded | A graduated ladder: `warn → throttle (429) → downgrade model → require approval → block (402/403, not retryable) → kill switch`. The action is set per control in the catalog. |
| Signature feed | A separate **threat-intel service** publishes a signed (Ed25519/minisign), monotonically versioned YAML/JSON bundle. Its matcher types are a closed set: `regex` (RE2), `literal_set`, `url`, `package`, `hash`, `bytes`/`yara`, `pickle_globals`, `json_path`, `semantic` (exemplars), and composites. The gateway pulls it, with an SSE push, then verifies, runs the **inline test vectors**, compiles and swaps it in atomically. It keeps the last good version and refuses rollback. |
| Seed signatures | 18 historical attack families plus a canary (§2), covering pickle, nullifAI, Keras, GGUF SSTI, Probllama, ShadowRay, Langflow, LLM code exec, mcp-remote, MCP Inspector and the LiteLLM MCP RCE, tool poisoning, Unicode smuggling, EchoLeak exfiltration, agent-config hijack, slopsquatting and compromised packages, HF namespace reuse, and prompt-injection families. |
| Telemetry | OpenTelemetry GenAI and MCP semantic conventions. They are still marked Development and moved to a separate repo in June 2026; §4.2 lists the exact names. Our own `aicl.*` metrics are exported to Prometheus. Each request records per-control latency, and the gateway sends a `Server-Timing` header. |
| Audit | Hash-chained JSONL with one record per decision. Content is redacted by default, and redactions are recorded as spans. Export to JSONL, CSV or **OCSF** (Detection Finding 2004 and API Activity 6003, using the OCSF 1.9 `ai_model`/`ai_agent` objects). |
| Dashboards | Three views. **Management** shows spend against budget, blocks, cost avoided and forecasts. **Security** shows the live decision stream, signature hits, feed status, approvals and the kill switch. **Performance** shows p50/p95/p99 overhead and per-control latency. |

---

## 1. Budget and resource governance

### 1.1 Threat model and framing

- **OWASP LLM10:2025 "Unbounded Consumption"** covers denial of wallet, variable-length input floods, continuous context overflow and resource-heavy queries. Its recommended mitigations are rate limits, quotas, timeouts, throttling, input size limits, graceful degradation, and logging with anomaly detection. ([OWASP](https://genai.owasp.org/llmrisk/llm102025-unbounded-consumption/))
- **MITRE ATLAS AML.T0034 "Cost Harvesting"**: deliberately pushing a victim's AI spend up with many cheap queries or a few expensive ones. ([summary](https://www.startupdefense.io/mitre-atlas-techniques/aml-t0034-cost-harvesting))
- **OWASP Top 10 for Agentic Applications (Dec 2025)**: ASI02 "Tool Misuse and Exploitation" includes loops and runaway volume, and ASI08 covers cascading agent failures. ([OWASP](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026), [overview](https://goteleport.com/blog/owasp-top-10-agentic-applications))
- Agent frameworks have their own step limits: LangGraph's `recursion_limit` defaults to 25 and raises `GraphRecursionError`, and the OpenAI Agents SDK's `max_turns` defaults to 10 and raises `MaxTurnsExceeded`. ([LangGraph](https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT.md), [OpenAI Agents](https://openai.github.io/openai-agents-python/ja/ref/exceptions/)) These limits only work if every framework sets them, and nothing is enforced centrally across frameworks. **Our pitch:** the gateway enforces these limits whatever the framework, and does the same for local models.

### 1.2 Prior art

| Feature | LiteLLM Proxy | Portkey | What we take |
|---|---|---|---|
| Hierarchy | Global/proxy, team, team member, internal user, virtual key, per-model, end-user/customer. If a key belongs to a team, **only team and team-member budgets apply**. ([docs](https://docs.litellm.ai/docs/proxy/users)) | Policies with `conditions` (AND) and `group_by` over `api_key`, `virtual_key`, `provider`, `model`, `metadata.*`, `workspace_id`. ([budget policies](https://portkey.ai/docs/product/enterprise-offering/budget-policies)) | Explicit hierarchy that is **checked at every level**, plus Portkey-style `group_by` over metadata (agent and session come from headers). |
| Fields | `max_budget`, `budget_duration` (`30s`/`30m`/`30h`/`30d`/`1mo`), `soft_budget`, `tpm_limit`, `rpm_limit`, `max_parallel_requests`, `model_max_budget` | `type: cost\|tokens\|requests`, `credit_limit`, `alert_threshold`, `periodic_reset: weekly\|monthly`, `periodic_reset_days` | Same ideas under our own names. Soft thresholds become alerts. |
| Window | Durations, with reset at midnight UTC, Monday or the 1st | Calendar weekly/monthly, or N days | Calendar windows for money, sliding windows for rate. |
| Rate limits | rpm/tpm per key, user or team | `rpm/rph/rpd/rpw` for requests or tokens. The MCP gateway can rate-limit per `mcp_server` or `mcp_tool`. ([MCP rate limits](https://portkey.ai/docs/aigw/product/mcp-gateway/rate-limits)) | Rate limits per tool and per MCP server, which matter for agents. |
| On exceed | Returns 400/401 with `ExceededBudget` / `ExceededTokenBudget` | Usage limit returns **412**; rate limit returns **429** | Distinct, non-retryable error for budgets (§1.7). |
| Metrics | `litellm_spend_metric`, `litellm_remaining_team_budget_metric`, `litellm_remaining_api_key_budget_metric`, `litellm_overhead_latency_metric`, `litellm_guardrail_latency_seconds`, … ([docs](https://docs.litellm.ai/docs/proxy/prometheus)) | Audit log entry when the alert threshold is crossed | Remaining-budget gauges and a separate **overhead** latency metric. |
| Cost table | `model_prices_and_context_window.json`: `input_cost_per_token`, `output_cost_per_token`, `cache_read_input_token_cost`, `cache_creation_input_token_cost`, `max_input_tokens`… ([docs](https://docs.litellm.ai/docs/provider_registration/add_model_pricing)) | (managed) | **Vendor LiteLLM's JSON at a pinned commit** to seed our cost table. |

> **Warning from the field:** LiteLLM itself was hit twice in 2026. Its PyPI package was backdoored (v1.82.7 and v1.82.8, 24 Mar 2026), and CVE-2026-42271, an RCE through MCP test endpoints, was added to CISA KEV on 8 Jun 2026. Both are in our seed feed (§2). Gateways are high-value targets, so we should harden ours (see §3.8).

### 1.3 Measuring usage for each provider

**Principle:** count before the call so we can reserve budget, then settle on what the provider reports after the call.

| Provider | Pre-flight estimate | Actual usage (post) | Notes |
|---|---|---|---|
| **OpenAI / OpenAI-compatible** | `tiktoken`: `tiktoken.encoding_for_model(model)`, falling back to `o200k_base` ([repo](https://github.com/openai/tiktoken)). Add a few tokens of overhead per message for chat formatting. | `usage.prompt_tokens`, `completion_tokens`, `prompt_tokens_details.cached_tokens`, `completion_tokens_details.reasoning_tokens`. In streaming, **inject `stream_options: {"include_usage": true}`** so the final chunk carries usage. ([OpenAI forum](https://community.openai.com/t/usage-stats-now-available-when-using-streaming-with-the-chat-completions-api-or-completions-api/738156)) | Reasoning tokens are billed as output and are already counted in `completion_tokens`. |
| **Anthropic** | `POST /v1/messages/count_tokens`. It is free, has its own RPM limits (5k/10k/20k by tier) and handles tools, images (base64) and PDFs. The result is "an **estimate**". ([docs](https://platform.claude.com/docs/en/build-with-claude/token-counting)) | `usage.input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` | **Don't use tiktoken as a proxy for Claude.** Claude Opus 4.7 and later models use a tokenizer that gives about 30% more tokens for the same text (same docs). If calling count_tokens would add latency, use a chars/3 heuristic with a safety margin and reconcile afterwards. |
| **Ollama (local)** | Heuristic (chars/3.5), or the Hugging Face tokenizer for the model family | Final chunk (`done: true`): `prompt_eval_count`, `prompt_eval_cached_count`, `eval_count`, `total_duration`, `load_duration`, `prompt_eval_duration`, `eval_duration`, **all durations in nanoseconds**. ([docs](https://docs.ollama.com/api/usage)) | Use the native `/api/chat` path when we need compute time; the OpenAI-compatible `/v1` path doesn't return durations. **Always set `options.num_predict`** rather than relying on the default (`-1` means unlimited) and cap `num_ctx`. |

**Normalisation.** Store `input_tokens` as total input including cache, which follows the OTel convention that cache reads are a subset of input ([attribute inventory](https://coralogix.com/docs/user-guides/ai/otel-integration/span-attributes/)). Anthropic reports `input_tokens` *excluding* cache, so add the two cache fields when normalising. OpenAI's `prompt_tokens` already includes `cached_tokens`.

### 1.4 Cost model

```
cost_usd = (in_uncached × p_in) + (cache_read × p_cache_read) + (cache_write × p_cache_write)
         + (out × p_out)                               # reasoning tokens already inside `out` for OpenAI
local_cost_usd = compute_s × p_compute_s               # shadow price for local models
compute_s = (load_duration + prompt_eval_duration + eval_duration) / 1e9   # Ollama ns → s
```

`cost_table.yaml` is part of the control catalog. It is hot-reloadable and versioned, and its version is stamped on every audit record. **All prices below are placeholders.** Fill them at T0 from the vendored LiteLLM JSON or the providers' pricing pages.

```yaml
cost_table:
  version: 2026-10-03.1
  currency: USD
  unit: per_1m_tokens
  models:
    "openai/gpt-x":            {in: 0.00, out: 0.00, cache_read: 0.00, max_input_tokens: 0}
    "anthropic/claude-x":      {in: 0.00, out: 0.00, cache_read: 0.00, cache_write: 0.00}
    "ollama/llama3.2:3b":      {compute_s: 0.0002}   # shadow price ≈ $0.72/GPU-h, illustrative
    "ollama/*":                {compute_s: 0.0002}
  unknown_model_policy: block      # or: price_as "openai/gpt-x" (pessimistic)
```

A local GPU is also a **capacity** resource, not only a cost. Add `max_concurrent_local` for each agent, since one runaway agent can starve everyone else on the same laptop or GPU, and enforce `max_wall_s` for each call.

### 1.5 Hierarchical budgets

```
org (hard cap)
 └── team            (can oversubscribe the org; the org is still the hard cap)
      └── agent      (identified by API key and X-AICL-Agent header, or by the MCP client identity)
           └── session  (X-AICL-Session header | gen_ai.conversation.id | mcp.session.id | hash of first system+user msg)
```

**Semantics**
1. Every request resolves its chain: `[org:acme, team:research, agent:analyst-bot, session:abc]`.
2. **Check and reserve across all levels in one atomic step.** For each level and each dimension, if `used + reserved + estimate > limit`, deny and name the scope that tripped. Otherwise reserve the estimate at every level.
3. **Settle** after the response: `used += actual`, `reserved -= estimate`. If the actual exceeds the estimate (for example because `max_tokens` was large), record an `overshoot` event. The overshoot is bounded because `max_tokens` is clamped to the remaining budget.
4. **Windows:** money and token budgets use calendar windows (daily, weekly, monthly, reset at UTC midnight). Rate limits use sliding windows (token bucket or GCRA). Session budgets last for the life of the session.
5. **Soft thresholds** at 50%, 80% and 100% emit `budget.threshold` events and alerts, which can also trigger the downgrade policy (§1.7).
6. **Live edits:** when a judge lowers a limit in the catalog, counters keep their usage and the new limit applies on the next request. If usage already exceeds the new limit, the next request is blocked. This makes a good demo.

**Storage and scalability.** For the single-node demo, keep counters in process (behind an asyncio lock) and snapshot them to SQLite. For scale, use Redis with a Lua script that does the multi-key check-and-reserve atomically. In Redis Cluster, put each org's keys in one hash slot with hash tags (`{org:acme}:team:research:usd:2026-10-03`) so the Lua script stays single-slot. Rate limiting uses GCRA, which needs one key per limit.

```lua
-- KEYS = counter keys for every level×dimension; ARGV = limits..., estimates..., ttl
for i=1,#KEYS do
  local used = tonumber(redis.call('HGET', KEYS[i], 'used') or '0')
  local resv = tonumber(redis.call('HGET', KEYS[i], 'reserved') or '0')
  if used + resv + tonumber(ARGV[#KEYS+i]) > tonumber(ARGV[i]) then return {0, i} end  -- deny, which level
end
for i=1,#KEYS do redis.call('HINCRBYFLOAT', KEYS[i], 'reserved', ARGV[#KEYS+i]); redis.call('EXPIRE', KEYS[i], ARGV[#ARGV]) end
return {1, 0}
```

### 1.6 Agent runaway controls and loop detection

**Hard caps** (catalog, per agent or per session): `max_steps` (LLM calls), `max_tool_calls` (total and per tool), `max_wall_s`, `max_context_tokens` (pre-flight input count), `max_output_tokens` (clamp `max_tokens`/`num_predict`), `max_parallel`.

**Loop detector.** It keeps per-session state in a ring buffer of the last W=20 events.

| ID | Detector | Algorithm | Default |
|---|---|---|---|
| LOOP-001 | Exact repeat | `fp = sha256(tool_name ‖ canonical_json(args minus volatile keys like timestamps/nonces))[:16]`. Count occurrences of `fp` in the window. | ≥3 in a window of 20 |
| LOOP-002 | Short cycle | For period p in 2..4, check whether the last p·k fingerprints equal the last p repeated k times (A,B,A,B,A,B). | k = 3 |
| LOOP-003 | No progress | The same `(fp, result_hash)` pair is seen again, meaning the same call got the same result. | ≥2 |
| LOOP-004 | Error streak | The last N tool results are `isError` or have the same `error.type`. | N = 5 |
| LOOP-005 | LLM self-repeat | Assistant messages are identical, or have embedding cosine > 0.98, for consecutive steps. | 3 consecutive |
| LOOP-006 | Burn-rate spike | EWMA of $/min (or compute-s/min) per agent rises above 5× its baseline and above a floor. | throttle |
| LOOP-007 | Context growth | Input tokens grow on every step without the task finishing, as when an agent keeps appending tool output. | >3× first step |

**Graduated response for loops:**
1. First trip: return a *tool error result* to the agent. The MCP `isError: true` text says "Loop detected (LOOP-001): identical call `search{q:…}` repeated 3×. Change approach or finish." This often breaks the loop with no human involved.
2. Second trip: block the session's tool calls (403 / JSON-RPC error).
3. Third trip, or a burn-rate spike: kill the session and require approval to resume.

### 1.7 Actions when a limit is exceeded

| Step | Action | Mechanics |
|---|---|---|
| 0 | **warn** | Response headers `X-AICL-Budget-Remaining: usd=0.42;tokens=12000;scope=session`, an audit event and an alert. |
| 1 | **throttle** | `429` with a `Retry-After` header. Use this **only for rate limits**, where retrying is the right thing to do. |
| 2 | **downgrade** | Rewrite `model` using the catalog's `downgrade_map`, for example a large cloud model → small cloud model → `ollama/llama3.2:3b` through Ollama's OpenAI-compatible `/v1`. Add the header `X-AICL-Downgraded-From`. This is OWASP's "graceful degradation" and triggers at the soft threshold. |
| 3 | **require approval** | Hold the request (async) for up to N seconds while an approver clicks in the dashboard. Otherwise return `403 {code:"approval_required", approval_id}` and the client retries with an `X-AICL-Approval` header. On MCP, use elicitation where the client supports it. |
| 4 | **block** | **`402` (or `403`) with a non-retryable error body.** Don't use 429 for an exhausted budget. The OpenAI Python SDK retries 408, 409, 429 and 5xx by default (2 retries) ([ref](https://www.mintlify.com/openai/openai-python/concepts/retries)), so returning 429 would cause retry storms. |
| 5 | **kill switch** | Catalog `kill_switch: {global: false, teams: [], agents: [], sessions: []}` plus `POST /admin/kill`. It cancels in-flight upstream streams, sets the gauge `aicl_killswitch_active=1`, and writes an audit record. |

Error body (OpenAI-compatible). It is written so the **model itself can read it and stop**:
```json
{"error": {"type": "budget_exceeded", "code": "BUD-SESSION-TOKENS",
  "message": "AI Control Layer: session token budget exhausted (50,000/50,000). Stop and summarise progress.",
  "control_id": "BUD-003", "scope": "session", "scope_id": "abc",
  "limit": 50000, "used": 50000, "resets_at": null, "request_id": "01J..."}}
```
For Anthropic-format clients, return `{"type":"error","error":{"type":"budget_exceeded",...}}`. For MCP `tools/call`, return a tool result with `isError: true` and the same message.

**Mid-stream enforcement:** while relaying SSE, count output tokens incrementally (tokenizer or chars/4). If the reservation runs out and can't be extended, send a final event `{"choices":[{"finish_reason":"length"}], "aicl":{"terminated":"budget"}}`, close the upstream connection, and settle on what was actually sent.

### 1.8 Catalog excerpt (budgets)

```yaml
budgets:
  defaults:
    on_soft: [warn]
    on_hard: block
  scopes:
    - scope: org/acme
      limits: {usd: {limit: 50, window: 1d}, local_compute_s: {limit: 7200, window: 1d}}
    - scope: team/research
      limits: {usd: {limit: 10, window: 1d}, tokens_in: {limit: 2_000_000, window: 1d}}
      soft_thresholds: [0.5, 0.8]
      on_soft_0.8: downgrade
    - scope: agent/analyst-bot
      limits: {usd: {limit: 2, window: 1d}, requests: {rate: 60/m}, tool_calls: {rate: 30/m}}
      per_tool: {"web.search": {rate: 10/m}, "shell.exec": {limit: 0}}   # 0 means approval required
      max_parallel: 4
    - scope: session/*
      limits: {usd: {limit: 0.50}, tokens_total: {limit: 50_000}, steps: {limit: 30},
               tool_calls: {limit: 20}, wall_s: {limit: 600}, context_tokens: {max: 32_000}}
      loop_detection: {repeat: 3, cycle_k: 3, error_streak: 5, action_ladder: [tool_error, block, kill]}
downgrade_map: {"anthropic/claude-x": "anthropic/claude-small", "openai/gpt-x": "openai/gpt-x-mini", "*": "ollama/llama3.2:3b"}
kill_switch: {global: false, agents: []}
```

### 1.9 Budget demo scenarios for judges

1. **Runaway agent:** a scripted agent calls `search("same query")` in a loop. The audit log shows LOOP-001, the agent receives the tool error, it trips again and the session is blocked. The dashboard shows `loop.detections` rising and a flat spend line.
2. **Cost flood:** a script sends large prompts. The team crosses 80% and gets downgraded to Ollama, then crosses 100% and gets a 402. A judge edits `team/research.usd.limit` live from 10 to 20 and traffic resumes within one second.
3. **Local GPU cap:** two agents hammer Ollama. `max_concurrent_local` and `local_compute_s` kick in, and the dashboard shows compute-seconds next to USD.
4. **Kill switch:** a judge flips `kill_switch.agents: [analyst-bot]` in YAML and in-flight streams stop.

---

## 2. Historical attacks: seed list for the signature feed

**Interception points the gateway can observe.** These are the `applies_to.surfaces` values in the feed:
`llm.request` (prompt), `llm.response` (completion, including streamed output), `tool.call` (agent→MCP/tool args), `tool.result`, `tool.list` (tool names, descriptions and schemas), `mcp.auth` (OAuth metadata during MCP connect), `http.egress` (URLs, method and body of outbound tool HTTP calls), `artifact.fetch` (model or package downloads through the gateway), `artifact.bytes` (file contents and headers), `package.install` (install commands that appear in tool args or outputs), and `admin.api` (requests to local AI infrastructure such as Ollama, Ray or Langflow).

### 2.1 Overview table

| # | Feed ID | Attack (date) | References | Surface | Detectable pattern | Matcher | Action |
|---|---|---|---|---|---|---|---|
| 0 | AICL-TI-000 | **Canary** (an EICAR-style test string) | Our own | all | literal `AICL-TEST-SIGNATURE-7F3A` | literal_set | block |
| 1 | AICL-TI-001 | **Malicious pickle in model files.** JFrog found about 100 malicious HF models in Feb 2024, for example a `baller423` PyTorch model with a reverse shell to 210.117.212.93. | [BleepingComputer](https://bleepingcomputer.com/news/security/malicious-ai-models-on-hugging-face-backdoor-users-machines); ATLAS AML.T0011.000 / AML.T0010 | artifact.bytes | Pickle opcodes `GLOBAL`/`STACK_GLOBAL` + `REDUCE` that resolve to globals outside a safe allowlist (`os.system`, `subprocess.*`, `builtins.exec`, `runpy`, `pip`, `socket`) | pickle_globals | block |
| 2 | AICL-TI-002 | **nullifAI** (ReversingLabs, Feb 2025): a 7z-compressed PyTorch model with a deliberately broken pickle stream, so picklescan errored out before reaching the payload. Reverse shell to 107.173.7.141. Models `glockr1/ballr7`, `who-r-u0000/…`. | [ReversingLabs](https://www.reversinglabs.com/blog/rl-identifies-malware-ml-model-hosted-on-hugging-face) | artifact.bytes | A file with a model extension starting with 7z magic `37 7A BC AF 27 1C`. Any pickle parse error **counts as a detection (fail closed)**. | bytes/yara | block |
| 3 | AICL-TI-003 | **Unsafe model formats / torch.load bypass.** CVE-2025-32434 is RCE even with `weights_only=True` in PyTorch ≤2.5.1, fixed in 2.6.0 (CVSS 9.3, Apr 2025). Picklescan was bypassed by CVE-2025-1716 (`pip.main`), CVE-2025-1889 (non-standard extension), and CVE-2025-1944/1945 (ZIP header tricks). | [CVE-2025-32434](https://github.com/pytorch/pytorch/security/advisories/GHSA-53q9-r3pm-6pq6), [Sonatype](https://www.sonatype.com/blog/bypassing-picklescan-sonatype-discovers-four-vulnerabilities) | artifact.fetch, llm.response | Downloads of `.bin/.pt/.pth/.ckpt/.pkl/.joblib` instead of `.safetensors/.gguf`; any pickle inside a ZIP **whatever the member's extension**; `torch.load(` in generated code | url + regex | require_approval / alert |
| 4 | AICL-TI-004 | **Keras code-exec on load.** CVE-2024-3660 (Lambda layer, Keras <2.13, CVSS 9.8). CVE-2025-1550 (`config.json` bypasses `safe_mode=True`, Keras <3.8.0). | [CVE-2024-3660](https://cveawg.mitre.org/api/cve/CVE-2024-3660), [CVE-2025-1550](https://cveawg.mitre.org/api/cve/CVE-2025-1550) | artifact.bytes | `config.json` inside `.keras` with `"class_name": "Lambda"`, or a `"module"` outside `keras.*`, or `enable_unsafe_deserialization` | json_path + regex | block |
| 5 | AICL-TI-005 | **GGUF chat-template SSTI.** CVE-2024-34359 "Llama Drama" in llama-cpp-python 0.2.30–0.2.71: an unsandboxed Jinja2 `chat_template` in GGUF metadata leads to RCE (CVSS 9.7). | [CVE-2024-34359](https://cveawg.mitre.org/api/cve/CVE-2024-34359) | artifact.bytes, admin.api (`/api/create` template) | Template containing `__class__`, `__mro__`, `__subclasses__`, `__globals__`, `__builtins__`, `popen`, `os.system` | regex | block |
| 6 | AICL-TI-006 | **Probllama.** CVE-2024-37032 in Ollama <0.1.34: digest not validated, so path traversal via a malicious registry manifest on `/api/pull` led to arbitrary file write and then RCE (CVSS 8.8, May 2024). | [Wiz](https://wiz.io/blog/probllama-ollama-vulnerability-cve-2024-37032), [CVE](https://cveawg.mitre.org/api/cve/CVE-2024-37032) | admin.api | `/api/pull\|push\|create\|copy\|delete` from non-admin principals; `name` referencing a non-allowlisted registry host; `insecure: true`; a digest not matching `^sha256[:-][0-9a-f]{64}$`; `../` | url + json_path + regex | block |
| 7 | AICL-TI-007 | **ShadowRay.** CVE-2023-48022: the unauthenticated Ray Jobs API allowed RCE (CVSS 9.8, disputed by the vendor). Exploited in 2024, then **ShadowRay 2.0** (Nov 2025) turned it into a self-propagating botnet across more than 230k exposed clusters. | [CVE](https://cveawg.mitre.org/api/cve/CVE-2023-48022), [Oligo 2.0](https://oligo.security/blog/shadowray-2-0-attackers-turn-ai-against-itself-in-global-campaign-that-hijacks-ai-into-self-propagating-botnet), ATLAS AML.CS0023 | http.egress, tool.call | `POST :8265/api/jobs/` with `entrypoint`; download-and-exec shell (`curl … \| sh`) | url + regex | block |
| 8 | AICL-TI-008 | **Langflow unauthenticated RCE.** CVE-2025-3248 in Langflow <1.3.0: `/api/v1/validate/code` `exec`'d decorators and default args (CVSS 9.8, **CISA KEV since 5 May 2025**). | [CVE](https://cveawg.mitre.org/api/cve/CVE-2025-3248), [Horizon3](https://www.horizon3.ai/attack-research/disclosures/unsafe-at-any-speed-abusing-python-exec-for-unauth-rce-in-langflow-ai/) | http.egress, admin.api | Path `/api/v1/validate/code` and a body containing `@exec(`, `__import__(`, `subprocess` or `os.system` | url + regex | block |
| 9 | AICL-TI-009 | **Executing LLM-generated code.** LangChain PALChain CVE-2023-36258 (<0.0.236), LLMMathChain CVE-2023-29374, PandasAI CVE-2024-12366 (2.4.0, CVSS 9.8). | [CVE-2023-36258](https://cveawg.mitre.org/api/cve/CVE-2023-36258), [CVE-2024-12366](https://cveawg.mitre.org/api/cve/CVE-2024-12366) | llm.response, tool.call (code tools) | Generated code calling `os.system`, `subprocess`, `eval`, `exec`, `__import__`, `pty.spawn`, `socket`, `/dev/tcp/`, `bash -i >&`, `curl … \| sh`, `base64 -d \| sh` | regex (+ optional Python AST) | block on tool.call, alert on response |
| 10 | AICL-TI-010 | **mcp-remote OAuth command injection.** CVE-2025-6514 in mcp-remote 0.0.5–0.1.15: a malicious `authorization_endpoint` was passed to `open()`, causing OS command injection through PowerShell subexpressions (CVSS 9.6, Jul 2025). | [JFrog](https://research.jfrog.com/vulnerabilities/mcp-remote-command-injection-rce-jfsa-2025-001290844/), [CVE](https://cveawg.mitre.org/api/cve/CVE-2025-6514) | mcp.auth | `authorization_endpoint`/`token_endpoint`/`registration_endpoint` not `https://`, or containing `$(`, a backtick, `%24%28` or whitespace | json_path + url + regex | block |
| 11 | AICL-TI-011 | **Spawning stdio MCP servers over HTTP.** MCP Inspector CVE-2025-49596 (<0.14.1, CVSS 9.4, exploitable from the browser via 0.0.0.0/DNS rebinding). **LiteLLM CVE-2026-42271** (1.74.2–1.83.6): `POST /mcp-rest/test/connection` and `/mcp-rest/test/tools/list` spawn `command/args/env` (**CISA KEV 8 Jun 2026**). | [Oligo](https://www.oligo.security/blog/critical-rce-vulnerability-in-anthropic-mcp-inspector-cve-2025-49596), [CVE-2026-42271](https://cveawg.mitre.org/api/cve/CVE-2026-42271), [CSA](https://labs.cloudsecurityalliance.org/research/csa-research-note-litellm-cve-2026-42271-ai-gateway-exploita/) | http.egress, admin.api, ingress to our own gateway | `:6277/sse?…transportType=stdio&command=`; `/mcp-rest/test/(connection\|tools/list)` with a `command`; any stdio server config whose `command` isn't on the allowlist | url + json_path | block |
| 12 | AICL-TI-012 | **MCP tool poisoning, rug pulls and shadowing** (Invariant Labs, Apr 2025). Hidden `<IMPORTANT>` instructions in tool descriptions tell the model to read `~/.cursor/mcp.json` and `~/.ssh/id_rsa` and leak them through a `sidenote` parameter. | [Invariant](https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks) | tool.list, tool.result | `<IMPORTANT>`, "do not tell/mention … user", `~/.ssh`, `id_rsa`, `mcp.json`, `.env`, references to *other* tools; a description hash that changed since approval (rug pull) | regex + literal_set + hash | strip tool + alert |
| 13 | AICL-TI-013 | **Invisible Unicode / ASCII smuggling.** Tag characters U+E0000–U+E007F hide instructions that models read but humans don't see (Rehberger, 2024). | [overview](https://securelayer7.net/learn-pdf/ai-security/unicode-tag-smuggling.pdf) | llm.request, tool.list, tool.result, llm.response | Codepoints `\x{E0000}-\x{E007F}`, zero-width characters `\x{200B}-\x{200D}\x{2060}\x{FEFF}`, bidi controls `\x{202A}-\x{202E}\x{2066}-\x{2069}` | regex | redact (strip) + alert; block inside tool descriptions |
| 14 | AICL-TI-014 | **Markdown/URL data exfiltration.** EchoLeak CVE-2025-32711 in M365 Copilot: zero-click, CVSS 9.3, Jun 2025, using reference-style markdown images and links to carry data out. | [CVE](https://cveawg.mitre.org/api/cve/CVE-2025-32711) | llm.response, tool.result | `![..](https://non-allowlisted/?<long query>)`, or reference-style `[x]: https://…?…` with a long or high-entropy query | regex + url | redact link + alert |
| 15 | AICL-TI-015 | **Agent config hijack for auto-approve.** GitHub Copilot CVE-2025-53773 writes `"chat.tools.autoApprove": true` ("YOLO mode", CVSS 7.8). Cursor CVE-2025-54135 "CurXecute" (<1.3.9) creates `.cursor/mcp.json` without approval. | [CVE-2025-53773](https://cveawg.mitre.org/api/cve/CVE-2025-53773), [CVE-2025-54135](https://cveawg.mitre.org/api/cve/CVE-2025-54135) | tool.call (file write, shell) | Writes to `.vscode/settings.json`, `.cursor/mcp.json`, `.claude/settings*.json`, `.mcp.json`; content containing `chat.tools.autoApprove` | json_path + regex | require_approval / block |
| 16 | AICL-TI-016 | **Slopsquatting / hallucinated packages.** In 2024 `huggingface-cli` was registered as a proof of concept and got about 30k downloads in 3 months (Lanyado). A USENIX Security 2025 study found 19.7% of 2.23M samples contained hallucinated packages, 205,474 unique names, and 43% recurred across repeated prompts. | [Willison/Lanyado](https://simonwillison.net/2024/Apr/1/diving-deeper-into-ai-package-hallucinations/), [CSA note](https://labs.cloudsecurityalliance.org/research/csa-research-note-slopsquatting-ai-supply-chain-20260419/); ATLAS AML.T0060 | package.install, llm.response, tool.call | Parse `pip/uv/poetry install`, `npm i`, `npx -y`, `pnpm/yarn add` and look the name up in the feed's `hallucinated_packages` list, or treat it as unknown if it's missing from the allowlist | package | require_approval |
| 17 | AICL-TI-017 | **Compromised AI packages and MCP servers.** `postmark-mcp` 1.0.16 (Sep 2025, the first malicious MCP server, BCC'd all mail to `giftshop[.]club`). `litellm` 1.82.7/1.82.8 (24 Mar 2026, `litellm_init.pth` stealer). `mistralai` 2.4.6 (12 May 2026, Mini Shai-Hulud, `/tmp/transformers.pyz`). Amazon Q VS Code extension 1.84.0 (CVE-2025-8217, injected wiper prompt). | [Koi](https://koi.ai/blog/postmark-mcp-npm-malicious-backdoor-email-theft), [CSA LiteLLM](https://labs.cloudsecurityalliance.org/research/csa-research-note-litellm-pypi-backdoor-ai-toolchain-supply/), [Mistral advisory](https://docs.mistral.ai/resources/security-advisories/MAI-2026-002), [CVE-2025-8217](https://cveawg.mitre.org/api/cve/CVE-2025-8217) | package.install, tool.call (MCP server launch config), tool.call args (IOCs) | OSV-like `affected` (ecosystem, name, versions) list; IOC literals `giftshop.club`, `litellm_init.pth`, `transformers.pyz` | package + literal_set | block |
| 18 | AICL-TI-018 | **Model namespace reuse.** Unit 42 (2025) showed that deleted HF authors' namespaces can be re-registered and poisoned, affecting Vertex AI and Azure catalogs. | [Unit 42](https://unit42.paloaltonetworks.com/model-namespace-reuse/) | artifact.fetch | `huggingface.co/{ns}/{repo}/resolve/{rev}/…` with `ns` in the feed's `reregistered_namespaces` list (block), or `rev` not a 40-hex commit (alert: unpinned) | url | block / alert |
| 19 | AICL-TI-019 | **Prompt-injection payload families** (ATLAS AML.T0051 direct and indirect; OWASP ASI01 goal hijack): instruction override, persona jailbreak (DAN), system-prompt extraction, role and delimiter spoofing (`</system>`, `<\|im_start\|>system`), encoded instructions (base64), tool-forcing ("call send_email with…"). | ATLAS / OWASP | llm.request, tool.result (indirect) | High-precision regex anchors **plus semantic exemplars**: the semantic guardrail embeds them and uses max cosine ≥ threshold | regex + semantic | block (direct) / quarantine (indirect: wrap or strip) |

**The 12 to demo first:** 000 (canary), 001, 002, 006, 008, 009, 010, 011, 012, 013, 014, 016/017, 019.

### 2.2 Lessons that shape our detectors

- **Fail closed when a parser errors.** nullifAI worked because the scanner *validated and stopped* while `pickle` *executed opcodes as it streamed them*. Our pickle analyzer iterates `pickletools.genops`, which never executes anything, inspects opcodes **as they stream**, and treats a parse exception as malicious.
- **Use an allowlist, not a denylist.** CVE-2025-1716 slipped through because `pip` was missing from picklescan's denylist. Allow only the known tensor-rebuild globals (`torch._utils._rebuild_tensor_v2`, `collections.OrderedDict`, `torch.*Storage`, `numpy.core.multiarray._reconstruct`, `numpy.dtype`…) and block everything else. Track `STACK_GLOBAL` operands, including memo `BINGET`/`MEMOIZE` indirection, to resolve names.
- **Ignore file extensions.** CVE-2025-1889/1944/1945 hid pickles behind odd extensions or manipulated ZIP headers. Parse **both** the ZIP central directory and the local headers, scan every member, and compare the names.
- **Prefer safe formats by policy.** `.safetensors` and `.gguf` (with the template check from TI-005) are allowed. Pickle formats need approval. This is our CVE-2025-32434 mitigation: even `weights_only=True` wasn't safe on PyTorch < 2.6.
- **Lock down admin APIs of local AI infrastructure.** Probllama, ShadowRay, Langflow, MCP Inspector and the LiteLLM MCP endpoints are all "an unauthenticated or low-privilege control plane reachable by an agent or a browser". The gateway should front Ollama and allow agents **only** `/api/chat`, `/api/generate`, `/api/embed` and `/api/tags`. Everything else needs the admin role.
- **Treat our own gateway as a target.** LiteLLM was compromised through its supply chain and through an MCP test endpoint. Our MCP proxy must never spawn stdio servers from request data, and admin endpoints must require a separate admin token (§3.8).

---

## 3. Signature feed design

### 3.1 Requirements

| Brief / judge need | Design response |
|---|---|
| Signatures come "from an externally managed system" | A separate `threat-intel` service, its own container with its own signing key. The gateway holds **only the public key**. |
| Judges edit feeds live | An editor UI or YAML files in the intel service. Publishing signs and bumps the serial, an SSE notification goes out, and the gateway activates the change in **under 2 s** (a 10 s poll is the fallback). |
| Robustness (30%) | Signed bundles, inline test vectors, last-known-good fallback, anti-rollback, a closed matcher set, and the RE2 engine (no ReDoS from feed regexes). |
| Tests (15%) | Each signature carries positive and negative vectors that CI and the gateway's self-test both run. |
| Reporting | `feed.updated` / `feed.rejected` audit events, feed version stamped on every decision, and feed health gauges. |

### 3.2 Architecture

```
┌────────────── threat-intel service (separate container / Git repo) ─────────────┐
│ signatures/*.yaml  lists/*.txt|yaml  →  build (schema check + run vectors)      │
│   → dist/bundle-<serial>.json  + .minisig   → dist/latest.json (+ .minisig)     │
│ GET /feed/latest.json  GET /feed/bundle/<serial>.json(.minisig)  GET /feed/events (SSE) │
│ Editor UI for judges (textarea/Monaco) + "Publish" + "Tamper (demo)" button     │
└─────────────────────────────────────────────────────────────────────────────────┘
                  │ poll (ETag, 10 s) + SSE "new serial" push
                  ▼
┌────────────── gateway: FeedManager ─────────────────────────────────────────────┐
│ 1 fetch latest.json → verify sig → serial > current? not expired?               │
│ 2 fetch bundle → sha256 == latest.sha256 → verify minisig (pinned pubkey)        │
│ 3 JSON-Schema validate → limits (≤N sigs, regex ≤1 KB, RE2-compilable)           │
│ 4 compile: RE2 sets, Aho-Corasick literal sets, URL tries, hash sets, YARA-X     │
│   rules, package index, embed semantic exemplars                                │
│ 5 run every signature's inline tests → failing signatures are quarantined, not active │
│ 6 atomic swap (pointer/RCU), keep last 5 bundles on disk                        │
│ 7 emit audit feed.updated {from, to, added, removed, modified, quarantined}    │
│   metrics aicl_feed_serial, aicl_feed_reload_total{result}, compile duration    │
│ any failure → keep last-known-good, emit feed.rejected{reason}                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Production path, same format:** a Git repo. A PR edits `signatures/*.yaml`, CI runs the schema check and test vectors, and on merge it signs with minisign and publishes a release asset or Pages URL. The gateway pulls the raw URL. This is slower (minutes), so the live demo uses the service.

### 3.3 Bundle format

Inspired by **OSV** (`id`, `aliases`, `modified`, `published`, `withdrawn`, `affected`, `references`, `database_specific`; schema v1.9.1 as of Sep 2026 ([OSV](https://ossf.github.io/osv-schema/))), **Sigma** (`title`, `status`, `level`, `tags`, `logsource` and `detection` with `condition`, which map to our `applies_to` and `match`) and **YARA** (byte strings and a condition, for artifacts; YARA-X 1.0 has been stable since Jun 2025 and has Python bindings `yara-x` ([PyPI](https://pypi.org/p/yara-x))).

```yaml
# latest.json — tiny, signed, like a TUF "timestamp"
{ "feed": "aicl-threat-intel", "serial": 42, "version": "2026.10.03-4",
  "bundle": "bundle-000042.json", "sha256": "…", "published": "2026-10-03T21:14:05Z",
  "expires": "2026-10-04T21:14:05Z", "key_id": "<minisign key id, hex>" }
```

```yaml
# bundle-000042 (authored as YAML; distributed as canonical JSON bytes that are signed)
feed:
  name: aicl-threat-intel
  schema_version: 1
  serial: 42                         # strictly monotonic (anti-rollback)
  version: 2026.10.03-4
  published: 2026-10-03T21:14:05Z
  expires: 2026-10-04T21:14:05Z       # freshness; stale → alert (keep enforcing)
  min_gateway_version: 0.1.0
lists:                                # shared data referenced by signatures
  hallucinated_packages: {pypi: [huggingface-cli], npm: []}
  malicious_versions:                 # OSV-like
    - {ecosystem: npm,  name: postmark-mcp, versions: ["1.0.16"], ref: koi-2025-09}
    - {ecosystem: PyPI, name: litellm,      versions: ["1.82.7","1.82.8"], ref: csa-2026-03}
    - {ecosystem: PyPI, name: mistralai,    versions: ["2.4.6"], ref: mistral-MAI-2026-002}
  ioc_literals: ["giftshop.club", "litellm_init.pth", "/tmp/transformers.pyz", "107.173.7.141", "210.117.212.93"]
  reregistered_hf_namespaces: []      # filled from Unit 42-style monitoring
  allowed_egress_domains: ["api.openai.com", "api.anthropic.com", "huggingface.co", "registry.ollama.ai"]
signatures:
  - id: AICL-TI-010
    title: MCP OAuth authorization_endpoint command injection (mcp-remote)
    status: stable                    # experimental | test | stable | deprecated | withdrawn
    severity: critical                # info | low | medium | high | critical
    confidence: high
    aliases: [CVE-2025-6514, JFSA-2025-001290844]
    tags: [cwe.78, owasp-asi.ASI04, atlas.AML.T0010]
    references: [https://research.jfrog.com/vulnerabilities/mcp-remote-command-injection-rce-jfsa-2025-001290844/]
    published: 2025-07-09
    modified: 2026-10-03
    applies_to: {surfaces: [mcp.auth], direction: response}
    match:
      any_of:
        - {type: url, field: "$.authorization_endpoint", scheme_not_in: [https]}
        - {type: url, field: "$.token_endpoint",         scheme_not_in: [https]}
        - {type: regex, field: "$.*_endpoint", pattern: '\$\(|`|%24%28|\s'}
    action: block
    message: "Untrusted MCP server supplied a non-HTTPS / shell-metachar OAuth endpoint."
    tests:
      positive:
        - {surface: mcp.auth, json: {authorization_endpoint: "a:$(calc.exe)"}}
        - {surface: mcp.auth, json: {authorization_endpoint: "file:///etc/passwd"}}
      negative:
        - {surface: mcp.auth, json: {authorization_endpoint: "https://auth.example.com/authorize"}}
```

**Matcher types.** This is a closed set. The feed can never contain code.

| type | Fields | Engine | Used by |
|---|---|---|---|
| `literal_set` | `values[]`, `case_insensitive`, `list_ref` | Aho-Corasick | 000, 012, 017 |
| `regex` | `pattern` (RE2 syntax), `field` (JSONPath), `flags` | google-re2 (linear time) | most |
| `url` | `host_in`, `host_not_in`, `port_in`, `path_regex`, `query_has`, `scheme_not_in`, `method` | parsed URL | 006–008, 010, 011, 014, 018 |
| `json_path` | `path`, plus a nested matcher | jsonpath-lite | 004, 006, 011, 015 |
| `package` | `ecosystems[]`, `list_ref`, `unknown: approval\|allow` | install-command parser and index | 016, 017 |
| `hash` | `sha256[]`, `of: artifact\|tool_description` | set lookup | 001 (known-bad files), 012 (rug pull) |
| `bytes` / `yara` | `magic` hex at offset, or YARA-X rule source | yara-x (optional, with a pure-Python magic fallback) | 002, 004, 005 |
| `pickle_globals` | `mode: allowlist`, `allow[]`, `on_parse_error: block`, `scan_all_zip_members` | `pickletools.genops` streaming analyzer | 001, 003 |
| `semantic` | `exemplars[]`, `threshold`, `embed_model` | cosine against precomputed exemplar embeddings, shared with the semantic guardrail | 019 |
| composites | `any_of`, `all_of`, `not` | n/a | all |

**Actions** (the local catalog may override them, and every override is audited): `alert`, `redact`, `strip_tool`, `quarantine` (wrap untrusted content in a data-only envelope), `require_approval`, `downgrade`, `block`.

### 3.4 Signing and verification

- **minisign (Ed25519)** is the primary choice. It's simple, has one pinned public key, and the default prehashed mode uses BLAKE2b-512. The **trusted comment** is covered by the global signature, so we put `serial=42 feed=aicl-threat-intel sha256=…` there, which binds the version to the signature and blocks downgrades. ([minisign](https://jedisct1.github.io/minisign/)) Verification is about 40 lines of Python (`hashlib.blake2b` plus `cryptography`'s `Ed25519PublicKey.verify`) or a call to the `minisign -V -P <pubkey> -m bundle.json` CLI. Judges can verify with the CLI themselves.
- **Alternative:** `cosign sign-blob --key` / `cosign verify-blob --key … --bundle …`, which suits the Sigstore story in production. Keyless signing needs OIDC, which is overkill for 24 h.
- **TUF-lite threat coverage** ([TUF](https://theupdateframework.io/docs/security/)):
  - *Rollback:* reject `serial < current_serial` (state persisted locally).
  - *Indefinite freeze:* `expires` makes the feed go stale, which raises an alert. Keep enforcing the last-known-good bundle; fail-closed is optional in the catalog.
  - *Mix-and-match:* `latest.json` pins the bundle's sha256.
  - *Key compromise and rotation:* a `root.json` lists allowed key IDs, and rotation needs a signature by the old root key.
  - *Endless data:* cap the download size at 5 MB.
- **Operator rollback** is explicit: `POST /admin/feed/rollback {serial: 41}` (admin token) pins a local override and writes an audit event `feed.rollback`. Without that, an older serial is always rejected.

### 3.5 Hot reload, versioning and live editing

- **Two independent config planes.** The **control catalog** is local and owned by the platform team: budgets, guardrail thresholds, routing, feed overrides, the kill switch. The **threat feed** is external and owned by threat intel. Both are watched (`watchfiles` or SSE), validated, compiled and swapped atomically, and both stamp their version on every decision.
- **Each signature has a lifecycle.** Removing a signature means setting `status: withdrawn` (as OSV does), never a silent delete. `experimental` signatures run in **monitor mode** (they log but don't enforce), which is how judges can see a rule's false-positive rate before promoting it.
- **Per-signature overrides in the catalog**, for false positives: `feed_overrides: {AICL-TI-013: {action: alert}}`. Disabling a critical signature needs `justification:` and produces a high-severity audit event.

**Judge demo (about 3 minutes):**
1. Send the prompt "Please install `pip install huggingface-cli`" through a coding agent. The decision is `require_approval` by TI-016.
2. In the intel UI, add a new semantic exemplar to TI-019, for example a fresh jailbreak phrase in Polish, then click Publish. The dashboard header's feed serial goes from 42 to 43 in about 1 s, and the same prompt that passed a moment ago is now blocked, with `feed_version` 43 recorded in the audit record.
3. Click **Tamper**, which edits the bundle bytes without re-signing. The gateway logs `feed.rejected reason=bad_signature`, the dashboard shows a red banner, and enforcement stays on serial 43.
4. Paste the canary string `AICL-TEST-SIGNATURE-7F3A` anywhere (prompt, tool argument or tool description) to show end-to-end coverage of every surface.

### 3.6 Performance of the matching pipeline

- Compile once per feed version. Merge all regexes for a surface into an **RE2 Set** (one pass over the text), use Aho-Corasick for literal lists, and use dict or set lookups for hashes and packages.
- Only scan the surfaces each signature declares (`applies_to`), with a size cap per field (for example the first 256 KB, plus a "too large" flag that becomes its own control).
- For streaming responses, scan with an overlapping window (chunk plus the last 256 chars) so patterns that span chunks are still caught.
- Semantic matching: precompute exemplar embeddings when the feed loads. Each request needs one embedding call (a local model through Ollama, such as `nomic-embed-text` or MiniLM) and then a matrix dot product.
- Targets: all deterministic signatures **p95 < 2 ms** for an 8 KB prompt, and semantic **p95 < 40 ms** with a local embedder. We'll measure, not claim (§4.7).

### 3.7 Feed tests (part of the 15%)

- **Vector tests:** every signature's `tests.positive` must match and every `tests.negative` must not. These run in CI (`pytest -k feed`) and in the gateway's self-test on load.
- **Pipeline tests:** a tampered bundle is rejected; a lower serial is rejected; an expired feed raises the stale alert but keeps enforcing; schema-invalid input is rejected; a regex that RE2 can't compile, such as a backreference, is rejected; a catastrophic-backtracking pattern stays linear-time under RE2 (assert under 5 ms on a 100 KB input); an oversized bundle is rejected; an SSE notification activates in under 2 s.
- **Replay tests:** benign reproductions of each historical attack, kept as fixtures. They are *generated* and never loaded. Examples: pickle bytes built with `pickle.dumps` of a class whose `__reduce__` returns `(os.system, ("echo hi",))`, written as bytes and only ever *scanned*; a 7z-magic-prefixed `.bin`; a Keras `config.json` with Lambda; a GGUF metadata blob with a Jinja SSTI string; a Ray `/api/jobs/` request; a Langflow body; an OAuth metadata document with `$(...)`; a poisoned MCP tool description; Unicode tag text; an EchoLeak-style markdown image.

### 3.8 Hardening the gateway itself (lessons from LiteLLM)

- No endpoint ever spawns processes from request data. stdio MCP servers come **only** from the catalog.
- Admin API (`/admin/*`: kill switch, feed rollback, approvals) sits on a separate listener or port and requires an admin token. Agent keys can't call it.
- Pin and hash-lock our own dependencies, and run `pip install --require-hashes`. Note that `.pth` startup hooks are an infection vector (LiteLLM 1.82.8).
- Never log provider API keys. Hash key IDs in audit records.

---

## 4. Reporting, audit and telemetry

### 4.1 Data products

| Product | Audience | Transport | Retention in the demo |
|---|---|---|---|
| **Metrics** | management, ops | OTel SDK → Prometheus `/metrics` (and/or OTLP to a Collector) | Prometheus TSDB |
| **Traces** | engineers, security drill-down | OTel spans (GenAI + MCP semconv), OTLP | Jaeger/Tempo (optional) |
| **Audit log** | security team, compliance | hash-chained JSONL, plus export as CSV/OCSF and push to a SIEM | files plus SQLite index |
| **Live event stream** | dashboard | SSE `/events` (redacted decisions) | in-memory ring buffer |

### 4.2 OpenTelemetry GenAI semantic conventions (checked 2026-10-03)

**Status.** Every `gen_ai.*` attribute, metric and span is still **Development** (none are Stable). In **June 2026 (semconv v1.42.0)** the GenAI, provider-specific and MCP conventions were **moved to a dedicated repository, `open-telemetry/semantic-conventions-genai`**, which had no tagged release as of August 2026. The last in-tree definitions are in v1.41.x. ([dev.to summary](https://dev.to/azena-ai/opentelemetrys-genai-semantic-conventions-are-not-stable-yet-heres-what-actually-shipped-in-2026-3mke), [OTel page redirect](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-metrics/), [v1.41.0 metrics](https://raw.githubusercontent.com/open-telemetry/semantic-conventions/v1.41.0/docs/gen-ai/gen-ai-metrics.md))

**Renames to respect.** `gen_ai.system` became `gen_ai.provider.name`. `gen_ai.usage.prompt_tokens`/`completion_tokens` became `gen_ai.usage.input_tokens`/`output_tokens`. `gen_ai.prompt`/`gen_ai.completion` were removed in favour of the opt-in `gen_ai.input.messages`/`gen_ai.output.messages`/`gen_ai.system_instructions`. Migration uses the `OTEL_SEMCONV_STABILITY_OPT_IN` dual-emission mechanism.

**Span attributes we emit** (inference span name `{gen_ai.operation.name} {gen_ai.request.model}`, kind CLIENT) ([v1.41.0 spans](https://raw.githubusercontent.com/open-telemetry/semantic-conventions/v1.41.0/docs/gen-ai/gen-ai-spans.md)):
- Required: `gen_ai.operation.name` (`chat`, `embeddings`, `execute_tool`, `invoke_agent`, `invoke_workflow`, `create_agent`, `retrieval`, `text_completion`, `generate_content`), and `gen_ai.provider.name`. Well-known values include `openai`, `anthropic`, `aws.bedrock`, `azure.ai.openai`, `gcp.vertex_ai`, `gcp.gemini`, `mistral_ai`, `groq`, `deepseek`, `x_ai` and others. **`ollama` isn't a well-known value**, so we use the custom value `ollama`.
- Request and response: `gen_ai.request.model`, `gen_ai.request.max_tokens`, `gen_ai.request.temperature`, `gen_ai.request.stream`, `gen_ai.response.model`, `gen_ai.response.id`, `gen_ai.response.finish_reasons`, `gen_ai.response.time_to_first_chunk`.
- Usage: `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_creation.input_tokens`, `gen_ai.usage.reasoning.output_tokens`.
- Context: `gen_ai.conversation.id` (our session), `gen_ai.agent.id`, `gen_ai.agent.name`, `gen_ai.agent.version`, `gen_ai.workflow.name` ([agent spans](https://raw.githubusercontent.com/open-telemetry/semantic-conventions/v1.41.0/docs/gen-ai/gen-ai-agent-spans.md)).
- Tools (`execute_tool {gen_ai.tool.name}`): `gen_ai.tool.name`, `gen_ai.tool.call.id`, `gen_ai.tool.type`, and opt-in `gen_ai.tool.call.arguments`/`gen_ai.tool.call.result`.
- MCP (span name `{mcp.method.name} {target}`): `mcp.method.name` (`tools/call`, `tools/list`, `initialize`, `resources/read`, `prompts/get`, `sampling/createMessage`, …), `mcp.session.id`, `mcp.protocol.version`, `mcp.resource.uri`, `jsonrpc.request.id`, `rpc.response.status_code`, and `network.transport` (`pipe` for stdio, `tcp` for HTTP). **Propagate `traceparent` in `params._meta`.** ([v1.41.0 MCP](https://raw.githubusercontent.com/open-telemetry/semantic-conventions/v1.41.0/docs/gen-ai/mcp.md))
- Content capture is **off by default**, matching OTel's privacy-first stance.

**Standard metrics we emit:**

| Metric | Instrument / unit | Key attributes |
|---|---|---|
| `gen_ai.client.token.usage` | histogram `{token}` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.token.type` (`input`/`output`), `gen_ai.request.model`, `gen_ai.response.model` |
| `gen_ai.client.operation.duration` | histogram `s` | the above plus `error.type` |
| `gen_ai.client.operation.time_to_first_chunk` | histogram `s` | streaming |
| `gen_ai.client.operation.time_per_output_chunk` | histogram `s` | streaming |
| `mcp.client.operation.duration` / `mcp.server.operation.duration` | histogram `s` | `mcp.method.name`, `gen_ai.tool.name`, `error.type` |
| `mcp.client.session.duration` | histogram `s` | n/a |

**Our own metrics** (`aicl.*`; Prometheus names in brackets):

| Metric | Type | Labels (bounded cardinality) | Purpose |
|---|---|---|---|
| `aicl.requests` [`aicl_requests_total`] | counter | `surface`, `ingress` (openai/anthropic/ollama/mcp), `provider`, `decision` | traffic and outcome |
| `aicl.decisions` [`aicl_decisions_total`] | counter | `control_id`, `control_type` (deterministic/semantic/budget/signature/loop), `decision`, `severity`, `mode` (enforce/monitor) | **blocked interactions** |
| `aicl.signature.hits` [`aicl_signature_hits_total`] | counter | `signature_id`, `severity`, `surface` | threat view |
| `aicl.control.duration` [`aicl_control_duration_seconds`] | histogram | `control_id`, `control_type` | **per-control latency** |
| `aicl.gateway.overhead` [`aicl_gateway_overhead_seconds`] | histogram | `phase` (request/response/stream), `ingress` | **total overhead = total − upstream** |
| `aicl.upstream.duration` [`aicl_upstream_duration_seconds`] | histogram | `provider`, `model` | separates provider latency |
| `aicl.cost` [`aicl_cost_usd_total`] | counter | `team`, `agent`, `provider`, `model` | spend |
| `aicl.cost.avoided` [`aicl_cost_avoided_usd_total`] | counter | `team`, `reason` | estimated cost of blocked or downgraded requests |
| `aicl.local.compute` [`aicl_local_compute_seconds_total`] | counter | `model`, `agent` | Ollama compute |
| `aicl.budget.utilization` [`aicl_budget_utilization_ratio`] | gauge | `scope_type`, `scope_id` (org/team/agent only), `dimension` | management |
| `aicl.budget.remaining` [`aicl_budget_remaining`] | gauge | same | management |
| `aicl.loop.detections` [`aicl_loop_detections_total`] | counter | `detector`, `agent` | runaway agents |
| `aicl.approvals` [`aicl_approvals_total`] | counter | `outcome` (requested/approved/denied/expired) | human in the loop |
| `aicl.killswitch.active` | gauge | `scope_type` | n/a |
| `aicl.feed.serial`, `aicl.feed.signatures`, `aicl.feed.age_seconds` | gauge | `feed` | feed health |
| `aicl.feed.reloads` [`aicl_feed_reloads_total`] | counter | `result` (ok/bad_signature/rollback/schema/test_failed/stale) | feed integrity |
| `aicl.config.reloads` | counter | `plane` (catalog/feed), `result` | hot reload |

**Cardinality rule:** never use `session_id` or `request_id` as Prometheus labels. They belong in traces and audit records, and **exemplars** link histogram buckets to trace IDs. **Buckets for overhead histograms:** the OTel defaults start at 10 ms, which is too coarse for a gateway, so use `[0.0002, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1]`.

### 4.3 Audit log schema (`aicl.audit/1`, JSONL)

There is one record per decision-bearing event. Event types are `request` (summary with the final decision), `decision` (an individual control hit, optionally inlined into `request`), `approval.*`, `budget.threshold`, `killswitch.toggled`, `config.reloaded`, `feed.updated`, `feed.rejected` and `feed.rollback`.

```json
{
  "schema": "aicl.audit/1",
  "event_id": "01JB7Z6Q3N5V8W2K4X9R1T0M5C",
  "event_type": "request",
  "ts": "2026-10-03T22:41:07.123456Z",
  "request_id": "req_01JB7Z6Q…", "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "span_id": "00f067aa0ba902b7",
  "session_id": "sess_abc", "mcp_session_id": null,
  "actor": {"org": "acme", "team": "research", "agent_id": "analyst-bot", "agent_version": "1.2.0",
            "user_id": "u_42", "api_key_id": "sha256:9f2c…", "client_ip": "10.0.0.7"},
  "route": {"ingress": "openai", "operation": "chat", "provider": "anthropic",
            "model_requested": "anthropic/claude-x", "model_used": "ollama/llama3.2:3b",
            "downgraded_from": "anthropic/claude-x", "tool_name": null, "mcp_method": null},
  "interception_point": "llm.request",
  "decision": "block",
  "mode": "enforce",
  "controls": [
    {"control_id": "SIG:AICL-TI-019", "control_type": "signature", "source": "feed", "feed_serial": 43,
     "decision": "block", "severity": "high", "confidence": 0.91, "score": 0.91, "latency_ms": 18.4,
     "match": {"matcher": "semantic", "field": "messages[2].content", "span": [120, 188],
               "exemplar_id": "pi-override-pl-01", "excerpt": "Zignoruj [REDACTED:12] instrukcje…"}},
    {"control_id": "BUD-002", "control_type": "budget", "decision": "allow", "latency_ms": 0.08,
     "budget": {"scope": "team/research", "dimension": "usd", "limit": 10.0, "used": 8.41, "state": "soft"}},
    {"control_id": "LOOP-001", "control_type": "loop", "decision": "allow", "latency_ms": 0.02}
  ],
  "usage": {"input_tokens": 1834, "output_tokens": 0, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0, "reasoning_tokens": 0, "local_compute_s": 0.0, "tool_calls": 0},
  "cost": {"usd": 0.0, "usd_avoided_estimate": 0.0123, "cost_table_version": "2026-10-03.1", "estimated": true},
  "latency": {"total_ms": 21.7, "gateway_overhead_ms": 21.7, "upstream_ms": 0, "ttft_ms": null},
  "redactions": [{"field": "messages[1].content", "start": 54, "end": 90, "type": "secret.api_key", "control_id": "GR-SECRETS"}],
  "content": {"prompt_sha256": "c0ffee…", "response_sha256": null, "captured": false},
  "outcome": {"http_status": 403, "error_type": "policy_blocked"},
  "versions": {"catalog": "cat-2026-10-03.7", "feed_serial": 43, "gateway": "0.3.1"},
  "integrity": {"prev_hash": "sha256:7a1e…", "hash": "sha256:41d9…"}
}
```

**Design notes**
- **Redaction spans.** Raw content is never stored by default. We store hashes, redacted excerpts of at most 120 chars around the match, and `redactions[]` spans (`field`, `start`, `end`, `type`), so analysts know *what* was removed and *where* without seeing it. Full content capture is a catalog opt-in, as in OTel.
- **Tamper evidence.** `hash = sha256(prev_hash ‖ canonical_json(record minus integrity))`. Every N records (or every minute) a checkpoint `{seq, hash}` is signed with the gateway's Ed25519 key. `GET /audit/verify` re-walks the chain, which gives a nice "integrity OK" badge on the dashboard.
- **Correlation.** `trace_id` links to OTel traces, `request_id` is also returned to the client as the `X-AICL-Request-Id` header, and `versions` makes every decision reproducible ("which catalog and feed blocked this?").

### 4.4 OCSF mapping for SIEM export

Our audit records can be expressed as OCSF events. OCSF v1.9.0 includes **`ai_model`** (`ai_provider`, `name`, `uid`, `version`) and **`ai_agent`** (`uid`, `name`, `version`, `instance_uid`, `type_id`: Native/LangChain/AutoGen/CrewAI, `ai_model`) objects. ([ai_model](https://schema.ocsf.io/objects/ai_model), [ai_agent](https://schema.ocsf.io/objects/ai_agent))

| Our event | OCSF class | Key mappings |
|---|---|---|
| Signature/guardrail hit (block, redact or alert) | **Detection Finding** `class_uid 2004`, category 2 | `finding_info.title` = signature title, `finding_info.uid` = `event_id`, `finding_info.analytic.uid` = `control_id`, `severity_id` (critical→5, high→4, medium→3, low→2, info→1), `evidences[]` = match details, `observables[]` (URL, file hash, package), `resources[]` = target tool or model, `attacks[]` = ATLAS/ATT&CK tags, `message` ([class](https://schema.ocsf.io/classes/detection_finding)) |
| Gateway request summary | **API Activity** `class_uid 6003` | `api.operation` = `gen_ai.operation.name`, `api.service.name` = provider, `actor` (user + `ai_agent`), `src_endpoint`, `http_request`, `ai_model`, `duration` |
| Security-control outcome on either class | **Security Control profile** | `action_id`: 1 Allowed, 2 Denied, 3 Observed, 4 Modified (redact/downgrade). `disposition_id`: 1 Allowed, 2 Blocked, 3 Quarantined, 19 Alert. Also `is_alert`, `policy` (catalog version), `risk_score` ([profile](https://schema.ocsf.io/profiles/security_control)) |
| Config or feed change | API Activity (Update) or a custom `aicl.config_change` | `metadata.product`, actor = admin |

`metadata.product = {name: "AI Control Layer", vendor_name: "<team>"}`, `metadata.version = "1.9.0"`.

### 4.5 Export paths

- `GET /audit/export?format=jsonl|csv|ocsf&from=…&to=…&decision=block&control_id=…&agent=…` streams the result, with a CSV column set flattened from the schema above.
- Daily rotated files `audit-YYYYMMDD.jsonl` with a signed `.sha256` manifest.
- SIEM push: OTLP logs to an **OTel Collector**, which fans out to Splunk HEC, Elastic or a file. Alternatively a syslog/HTTP sink. For the demo, the Collector with `file` and `prometheus` exporters is enough.
- A management one-pager: `GET /reports/daily?date=` returns JSON or CSV with spend by team, blocks by category, top signatures and cost avoided.

### 4.6 Dashboard views

Grafana (pre-provisioned JSON dashboards on Prometheus) works well for metrics. A **custom live page** (SSE) handles the interactive parts: decision stream, approvals, kill switch, feed and catalog status, and export buttons. If time is short, build the custom page only and draw charts from `/api/stats`.

**Management**
- KPI tiles: spend today against the org budget, % of budget used, blocked interactions (24 h), cost avoided, active agents, local versus cloud share.
- Spend over time, stacked by team, with a budget line. Also local compute-seconds over time.
- Budget utilization per team and agent as bullet bars with 80% and 100% markers.
- Top 5 agents by spend, and downgrades over time.
- Month-end burn forecast: a linear projection from the 7-day trend.

**Security**
- Live decision stream: severity-coloured table with filters (agent, surface, control, decision) and a drill-down to the full audit record and trace.
- Signature hits by `signature_id` (top N) and by interception point.
- Blocks over time with **annotations for feed and catalog version changes**, so you can see the system adapt.
- An agent × attack-category heatmap.
- Feed status panel: serial, signer key ID, age, number of signatures (active, monitor, quarantined), and the last rejection with its reason, shown as a red banner.
- Approvals queue with approve/deny buttons. Kill-switch toggles.
- Audit-chain integrity badge and export buttons (JSONL/CSV/OCSF).

**Performance (ops and judges)**
- Gateway overhead p50/p95/p99 over time, from `histogram_quantile` on `aicl_gateway_overhead_seconds`.
- Per-control latency p95 as a sorted bar chart (`aicl_control_duration_seconds` by `control_id`).
- Upstream latency and TTFT by provider, throughput (RPS) and error rate.
- Feed compile and reload times, and config reload counts.

### 4.7 Performance telemetry and benchmark plan

- **Instrumentation:** wrap every control in a `perf_counter_ns` timer. The result feeds the `aicl.control.duration` histogram and `controls[].latency_ms` in the audit record. Overhead = total wall time − upstream time (time-to-headers plus stream relay time).
- **`Server-Timing` response header** (W3C), for example `Server-Timing: aicl;dur=3.2, sig;dur=0.4, sem;dur=2.1, budget;dur=0.1, upstream;dur=812`. Judges can see it in browser devtools or with `curl -i`.
- **Benchmark harness:** a **mock upstream** (an OpenAI-compatible echo with a fixed 50 ms latency) isolates our overhead. Load comes from k6, Locust or `hey` at 1, 10 and 50 concurrent clients, with three profiles: deterministic-only, deterministic + semantic, and the full path with streaming. We report p50/p95/p99 overhead, RPS and CPU, and commit the results as `bench/results-<git-sha>.json`. A CI regression test fails if p95 overhead grows by more than 20%.
- **Targets** (to validate, not claim): deterministic path p95 < 5 ms; with local semantic embedding p95 < 50 ms; feed reload under 300 ms for 100 signatures.

### 4.8 Reporting tests

- Golden test: a single blocked request produces exactly one `request` record with the expected `controls[]`, and the counters `aicl_decisions_total{decision="block"}` and `aicl_signature_hits_total` go up by one.
- Audit-chain test: changing one byte in an audit file makes `/audit/verify` fail at that record.
- Redaction test: a secret in the prompt never appears in the audit log, the SSE stream, the OTel span attributes or the logs. Grep all sinks.
- OCSF export validates against the OCSF 1.9.0 JSON schema for classes 2004 and 6003.
- Budget metrics: after N priced requests, `aicl_cost_usd_total` equals the sum of `cost.usd` in the audit records.
- Concurrency: 200 parallel requests against a $0.10 session budget never exceed the limit by more than one maximum-size reservation.

---

## 5. Suggested module layout and 24 h build order (this track)

```
gateway/
  budgets/      ledger.py (reserve/settle, hierarchy), pricing.py (cost_table), tokenize.py (tiktoken/anthropic/heuristic),
                ratelimit.py (GCRA), loops.py (LOOP-00x), actions.py (ladder, error bodies, downgrade)
  feed/         manager.py (pull/SSE, verify, swap), minisign.py, schema.json, compile.py,
                matchers/{regex,literal,url,package,hash,bytes,pickle_globals,semantic,jsonpath}.py
  telemetry/    otel.py (semconv attrs), metrics.py (aicl.*), audit.py (JSONL + hash chain), export.py (csv/ocsf),
                server_timing.py
threat-intel/   app.py (serve/edit/publish/tamper), signatures/*.yaml, lists/*, keys/ (demo key, never in gateway)
dashboard/      live page (SSE) + grafana/provisioning/*.json
tests/          test_budgets.py, test_loops.py, test_feed_pipeline.py, test_signatures_vectors.py,
                test_audit_chain.py, test_redaction_sinks.py, bench/
```

| Hours | Deliverable |
|---|---|
| 0–3 | Cost table and token accounting (OpenAI, Anthropic, Ollama), reserve/settle ledger, session and agent caps, error bodies |
| 3–6 | Feed manager (file-based first), matchers (regex/literal/url/package/json_path), canary plus 6 signatures with vectors |
| 6–9 | minisign verification, the threat-intel service with SSE push, tamper and rollback handling |
| 9–12 | Audit JSONL with hash chain, `aicl.*` metrics, Server-Timing header, `/events` SSE |
| 12–15 | Loop detector, downgrade, approvals, kill switch; remaining signatures including pickle_globals and bytes |
| 15–18 | Dashboard views and exports (CSV/OCSF) |
| 18–21 | Benchmark harness, replay fixtures, CI test run |
| 21–24 | Demo script rehearsal, buffer |

**Candidate dependencies** (Python, not installed yet): `tiktoken`, `anthropic`, `httpx`, `opentelemetry-sdk` + `opentelemetry-exporter-prometheus`/`-otlp` (or `prometheus_client`), `google-re2`, `pyahocorasick`, `cryptography` (Ed25519), `jsonschema`, `watchfiles`, `pyyaml`, optionally `yara-x` and `redis`.

---

## 6. Open questions and risks

1. **Model files may never pass through the gateway.** Artifact signatures (001–005, 018) need an interception point. Options: an egress proxy for `huggingface.co` and the Ollama registry, an MCP "model registry" tool, or fronting Ollama `/api/pull` and `/api/create`. Pick one for the demo.
2. **Anthropic count_tokens adds latency to every request.** Use it only when the remaining budget is tight; otherwise use the heuristic and reconcile afterwards.
3. **False positives in semantic signatures.** Ship new exemplars in `experimental` (monitor) mode first and show the hit rate before promoting them.
4. **OTel GenAI conventions are still unstable.** Pin to v1.41 names and note that dual emission through `OTEL_SEMCONV_STABILITY_OPT_IN` is the migration path.
5. **Prices change.** Vendor LiteLLM's price JSON at a pinned commit, and print the cost-table version on the dashboard.
6. **Some 2026 incidents (LiteLLM, Mistral) are recent.** Recheck the advisories on the day so the versions and IOCs in the seed feed are exact.

---

## 7. Sources

**Budgets and accounting**
- LiteLLM budgets and rate limits: https://docs.litellm.ai/docs/proxy/users
- LiteLLM Prometheus metrics: https://docs.litellm.ai/docs/proxy/prometheus
- LiteLLM model pricing JSON: https://docs.litellm.ai/docs/provider_registration/add_model_pricing
- Portkey budget limits: https://portkey.ai/docs/product/ai-gateway/virtual-keys/budget-limits
- Portkey budget/usage policies: https://portkey.ai/docs/product/enterprise-offering/budget-policies
- Portkey rate limits (LLM and MCP): https://portkey.ai/docs/aigw/product/policies/rate-limits, https://portkey.ai/docs/aigw/product/mcp-gateway/rate-limits
- Anthropic token counting: https://platform.claude.com/docs/en/build-with-claude/token-counting
- tiktoken: https://github.com/openai/tiktoken
- Ollama usage fields: https://docs.ollama.com/api/usage
- OpenAI streaming usage (`include_usage`): https://community.openai.com/t/usage-stats-now-available-when-using-streaming-with-the-chat-completions-api-or-completions-api/738156
- OpenAI SDK retry behaviour: https://www.mintlify.com/openai/openai-python/concepts/retries
- LangGraph recursion limit: https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT.md
- OpenAI Agents SDK exceptions: https://openai.github.io/openai-agents-python/ja/ref/exceptions/
- OWASP LLM10:2025: https://genai.owasp.org/llmrisk/llm102025-unbounded-consumption/
- OWASP Top 10 for Agentic Applications 2026: https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026
- MITRE ATLAS technique summaries: https://www.startupdefense.io/mitre-atlas-techniques/aml-t0034-cost-harvesting, https://www.startupdefense.io/mitre-atlas-techniques/aml-t0011-000-unsafe-ai-artifacts, https://www.startupdefense.io/mitre-atlas-techniques/aml-t0060-publish-hallucinated-entities

**Historical attacks**
- CVE-2025-32434 (PyTorch): https://github.com/pytorch/pytorch/security/advisories/GHSA-53q9-r3pm-6pq6, https://cveawg.mitre.org/api/cve/CVE-2025-32434
- nullifAI: https://www.reversinglabs.com/blog/rl-identifies-malware-ml-model-hosted-on-hugging-face
- JFrog malicious HF models (2024): https://bleepingcomputer.com/news/security/malicious-ai-models-on-hugging-face-backdoor-users-machines
- Picklescan bypasses: https://www.sonatype.com/blog/bypassing-picklescan-sonatype-discovers-four-vulnerabilities
- Keras CVE-2024-3660 / CVE-2025-1550: https://cveawg.mitre.org/api/cve/CVE-2024-3660, https://cveawg.mitre.org/api/cve/CVE-2025-1550
- llama-cpp-python CVE-2024-34359: https://cveawg.mitre.org/api/cve/CVE-2024-34359
- Probllama CVE-2024-37032: https://wiz.io/blog/probllama-ollama-vulnerability-cve-2024-37032, https://cveawg.mitre.org/api/cve/CVE-2024-37032
- ShadowRay CVE-2023-48022 and ShadowRay 2.0: https://cveawg.mitre.org/api/cve/CVE-2023-48022, https://oligo.security/blog/shadowray-2-0-attackers-turn-ai-against-itself-in-global-campaign-that-hijacks-ai-into-self-propagating-botnet
- Langflow CVE-2025-3248: https://cveawg.mitre.org/api/cve/CVE-2025-3248, https://www.horizon3.ai/attack-research/disclosures/unsafe-at-any-speed-abusing-python-exec-for-unauth-rce-in-langflow-ai/
- LangChain CVE-2023-36258: https://cveawg.mitre.org/api/cve/CVE-2023-36258
- PandasAI CVE-2024-12366: https://cveawg.mitre.org/api/cve/CVE-2024-12366
- mcp-remote CVE-2025-6514: https://research.jfrog.com/vulnerabilities/mcp-remote-command-injection-rce-jfsa-2025-001290844/, https://cveawg.mitre.org/api/cve/CVE-2025-6514
- MCP Inspector CVE-2025-49596: https://www.oligo.security/blog/critical-rce-vulnerability-in-anthropic-mcp-inspector-cve-2025-49596, https://cveawg.mitre.org/api/cve/CVE-2025-49596
- MCP filesystem server CVE-2025-53110 (path-prefix bypass, background): https://cveawg.mitre.org/api/cve/CVE-2025-53110
- LiteLLM CVE-2026-42271: https://cveawg.mitre.org/api/cve/CVE-2026-42271, https://labs.cloudsecurityalliance.org/research/csa-research-note-litellm-cve-2026-42271-ai-gateway-exploita/
- LiteLLM PyPI backdoor (Mar 2026): https://labs.cloudsecurityalliance.org/research/csa-research-note-litellm-pypi-backdoor-ai-toolchain-supply/
- Mistral / Mini Shai-Hulud (May 2026): https://docs.mistral.ai/resources/security-advisories/MAI-2026-002, https://www.root.io/malicious-packages/mistralai-pypi-compromise
- vLLM CVE-2025-32444 (pickle over ZMQ, background): https://cveawg.mitre.org/api/cve/CVE-2025-32444
- postmark-mcp: https://koi.ai/blog/postmark-mcp-npm-malicious-backdoor-email-theft
- Amazon Q CVE-2025-8217: https://cveawg.mitre.org/api/cve/CVE-2025-8217
- Tool poisoning: https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks
- EchoLeak CVE-2025-32711: https://cveawg.mitre.org/api/cve/CVE-2025-32711
- Copilot CVE-2025-53773 / Cursor CVE-2025-54135: https://cveawg.mitre.org/api/cve/CVE-2025-53773, https://cveawg.mitre.org/api/cve/CVE-2025-54135
- Unicode tag smuggling: https://securelayer7.net/learn-pdf/ai-security/unicode-tag-smuggling.pdf
- Package hallucinations: https://simonwillison.net/2024/Apr/1/diving-deeper-into-ai-package-hallucinations/, https://labs.cloudsecurityalliance.org/research/csa-research-note-slopsquatting-ai-supply-chain-20260419/
- Model namespace reuse: https://unit42.paloaltonetworks.com/model-namespace-reuse/

**Feed formats and signing**
- OSV schema: https://ossf.github.io/osv-schema/
- minisign: https://jedisct1.github.io/minisign/
- TUF security model: https://theupdateframework.io/docs/security/
- YARA-X Python bindings: https://pypi.org/p/yara-x

**Telemetry and audit**
- OTel GenAI move notice: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-metrics/
- OTel GenAI status summary (2026): https://dev.to/azena-ai/opentelemetrys-genai-semantic-conventions-are-not-stable-yet-heres-what-actually-shipped-in-2026-3mke
- v1.41.0 GenAI metrics / spans / agent spans / MCP: https://raw.githubusercontent.com/open-telemetry/semantic-conventions/v1.41.0/docs/gen-ai/gen-ai-metrics.md, …/gen-ai-spans.md, …/gen-ai-agent-spans.md, …/mcp.md
- OTel GenAI observability blog: https://opentelemetry.io/blog/2026/genai-observability/
- Cache-token attribute inventory: https://coralogix.com/docs/user-guides/ai/otel-integration/span-attributes/
- OCSF Detection Finding / Security Control profile / ai_model / ai_agent: https://schema.ocsf.io/classes/detection_finding, https://schema.ocsf.io/profiles/security_control, https://schema.ocsf.io/objects/ai_model, https://schema.ocsf.io/objects/ai_agent
