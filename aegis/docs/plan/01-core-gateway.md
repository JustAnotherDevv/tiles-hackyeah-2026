# 01 — core-gateway: Core gateway & provider adapters

Workstream **core-gateway** · task prefix **GW** · research refs 02 (architecture / Claude Code), 03 (building blocks, fail-modes, providers) · binding contract: `docs/CONTRACTS.md` (§1.2 ownership, §2.1 discovery, §3 types/protocols/pipeline semantics, §5.1–5.3 data plane + errors, §6.3 SSE, §6.5 env).

This workstream is the **backbone**: every other workstream plugs into the runtime, discovery and pipeline built here. The plan is ordered so that the *interfaces exist within the first ~15 minutes* (contract rule 7.1-4) and so the gateway *boots and proxies with nothing but frozen files + core-gateway* (rule 7.1-6).

> If two implementers are available, split at the GW-08 boundary: **A** = GW-01…07, GW-11 (runtime, pipeline, routes); **B** = GW-08…10, GW-12…16 (adapters, router, upstream, streaming). B codes against the frozen types and `rt.pipeline` and can start as soon as GW-01 lands.

---

## 1. Goal & demo value

What judges and the demo see:

| Visible effect | Where | Criteria served |
|---|---|---|
| Claude Code runs **unmodified** through Aegis (`ANTHROPIC_BASE_URL=http://127.0.0.1:8787`): subscription OAuth passes through, prompts are tokenized before leaving, replies are rehydrated locally, blocks arrive as a clean `[Aegis] Blocked by …` assistant message (no retries, no auth errors) | `/v1/messages`, `HEAD /api/hello` | Robustness 30 %, implementability 15 % |
| Same pipeline for every surface: one `Verdict` shape, one live feed row, one audit record per hop — model calls (Anthropic / OpenAI / Ollama wires), `/v1/guard` (SDK + test suite), playground, and every other workstream's surface (MCP, hooks, egress, config changes) | `aegis.core.pipeline` | Architecture 20 %, reporting 20 % |
| Budget stops behave exactly as Claude Code expects: **402 `budget_exceeded`** / **429 + `retry-after` + `x-should-retry: false`** (one attempt, clean exit — verified in `staging/spikes/claude-code/FINDINGS.md`) | model proxies | Budget governance |
| `Server-Timing: aegis;dur=…, ctl;dur=…, upstream;dur=…` + `X-Aegis-*` headers on every data-plane response — "overhead is a sliver of model time", visible in DevTools | all data-plane routes | Performance telemetry |
| Live decision feed over SSE with replay / `Last-Event-ID`, heartbeat, `system` toasts when a component degrades | `/api/events` | Security reporting |
| Gateway never crashes: a broken plug-in or missing service shows `degraded` in `/healthz` and the dashboard instead of taking traffic down; semantic timeouts follow the per-control `fail_mode` | runtime + Null fallbacks | Robustness, practical implementability |
| Judges' live policy edits apply to the **next request** (snapshot pinned per request; every decision stamped with policy version + feed serial) | pipeline | Live config adaptation |

---

## 2. Design

### 2.1 Files (all inside core-gateway ownership, §1.2)

```
src/aegis/__main__.py            CLI: serve | selftest | reset | verify-audit | seed | routes | version
src/aegis/app.py                 create_app(settings=None) -> FastAPI; lifespan builds/starts Runtime; middleware; exception handlers
src/aegis/settings.py            Settings (pydantic BaseModel from env, §6.5), get_settings() (lru_cache), Settings.env(name)
src/aegis/log.py                 setup_logging(level, json, access_log); SecretScrubFilter
src/aegis/core/runtime.py        Runtime (RuntimeProto), SERVICE_TABLE, get_runtime(), set_runtime(), component_status()
src/aegis/core/nulls.py          Null fallbacks for metrics/audit/policy/org/ledger/redactor/semantic/feed/approvals
src/aegis/core/bus.py            EventBus (ring buffer 1000, per-subscriber queues, drop-oldest), create(rt)
src/aegis/core/db.py             connect(path) (WAL, Row, busy_timeout), core tables (sessions)
src/aegis/core/sessions.py       SessionStore (in-memory LRU + write-behind to `sessions`), resolve_session_id()
src/aegis/core/discovery.py      discover_routers(), create_registry(rt) (controls), discover_adapters(), plugin_errors
src/aegis/core/pipeline.py       Pipeline (§3.5 steps 1–11), WireView LRU, summaries, complete(), record_only()
src/aegis/core/deps.py           get_rt, viewer, require_role(min_role)
src/aegis/core/errors.py         api_error(), AegisHTTPError, wire_error(wire, status, type, message, **fields)
src/aegis/core/crypto.py         hmac_hex(value, *, purpose="fp") with persistent key (public surface §3.3; absent from §1.1 tree — added under owned core/)
src/aegis/core/paths.py          get_path / set_path / remove_path / glob_match
src/aegis/core/timing.py         Stopwatch, server_timing_header(ctx), add_timing(ctx, key, ms)
src/aegis/proxy/__init__.py
src/aegis/proxy/router.py        resolve_route(model, wire, snap, settings) -> Route; builtin fallback providers
src/aegis/proxy/upstream.py      shared httpx.AsyncClient, header policy, send(), set_transport() (tests)
src/aegis/proxy/streaming.py     buffered accumulate/synthesize per wire, passthrough relay, keep-alives
src/aegis/proxy/sse.py           ported SSEParser / NDJSONParser / encode_sse / encode_comment (staging sse.py)
src/aegis/proxy/flow.py          ModelCall orchestrator shared by the 3 proxies + playground
src/aegis/proxy/adapters/__init__.py
src/aegis/proxy/adapters/anthropic.py   ADAPTERS = [AnthropicAdapter()]
src/aegis/proxy/adapters/openai.py      ADAPTERS = [OpenAIAdapter()]
src/aegis/proxy/adapters/ollama.py      ADAPTERS = [OllamaAdapter()]
src/aegis/proxy/stream/          (GW-16, could) full port of staging aegis_stream for `holdback`
src/aegis/api/routes/health.py          GET /healthz, HEAD|GET /api/hello
src/aegis/api/routes/proxy_anthropic.py POST /v1/messages, POST /v1/messages/count_tokens
src/aegis/api/routes/proxy_openai.py    POST /v1/chat/completions, POST /openai/v1/chat/completions, GET /v1/models
src/aegis/api/routes/proxy_ollama.py    ANY /ollama/{path:path}
src/aegis/api/routes/guard.py           POST /v1/guard, POST /v1/guard/complete
src/aegis/api/routes/events.py          GET /api/events (SSE)
src/aegis/api/routes/playground.py      POST /api/playground
src/aegis/api/routes/ui.py  (ORDER 900) GET / -> 302 /ui/, GET /ui/{path:path} (web/dist, SPA fallback)
config/snippets/core-gateway.yaml       providers / models.routes / defaults the gateway expects (§7 below)
tests/unit/core_gateway/                unit tests (fakes.py, fixtures/, test_*.py)
```

### 2.2 Runtime & service container (`aegis.core.runtime`)

- `SERVICE_TABLE` = ordered list of `(attr, "module:create", null_factory)` exactly as §3.3: settings, bus, metrics, audit, policy, org, sessions, ledger, redactor, semantic, feed, approvals, controls, pipeline.
- `Runtime.build()`: for each row → `importlib.import_module` + `create(rt)` inside `try/except Exception` → on failure `log.exception(...)`, install Null, record `self.status[attr] = "down"` (null) and queue a `system` warning event. `Runtime.start()` calls `await svc.start()` in order (failure → swap to Null + start it); `stop()` reverse order, each guarded.
- `get_runtime()` returns the module-global runtime (raises `RuntimeError` before startup); `set_runtime(rt)` used by `create_app` lifespan.
- `rt.db()` → `aegis.core.db.connect(settings.data_dir / "aegis.db")` (WAL, `row_factory=sqlite3.Row`, `check_same_thread=False`, `busy_timeout=5000`). `data_dir` created on start (+ `data/keys`).
- `component_status()` → `{"bus","policy","org","ledger","redactor","semantic","feed","approvals","audit","metrics","plugins","ollama"}` → `ok|degraded|down|off|stale`: Null = `down`; services may expose optional `health() -> str`; `semantic.status()["degraded"]` → `degraded`; `FeedStatus.status` map (`ok→ok, stale→stale, seed→degraded, disabled→off, rejected|unreachable→degraded`); `plugins` = `degraded` if any discovery import error; `ollama` from a cached (30 s) 1 s probe of `GET {ollama_url}/api/version` (skipped in `AEGIS_TEST_MODE`).
- `AEGIS_TEST_MODE=1`: no session flush loop, no Ollama probe, no background tasks.

### 2.3 Null fallbacks (`aegis.core.nulls`) — gateway usable with nothing else present

| Service | Null behaviour (contract §3.3) |
|---|---|
| metrics | all no-ops; `render()` → `(b"", "text/plain; version=0.0.4")` |
| audit | `record()` logs DEBUG and returns the event with `seq` incremented in memory; `verify()` → `ok=False, message="audit disabled"`; `query()` → `([], None)`; `export()` yields nothing |
| policy | parse `AEGIS_POLICY` once (PyYAML → `PolicyDoc.model_validate`, on error `PolicyDoc()`); snapshot v1 with `controls={c.id: c}` (no profile merge, no watch); `propose/apply_*/rollback` → `ApplyResult(status="rejected", message="policy engine unavailable")`; `validate` → schema-only report |
| org | single org `default`; `resolve_identity`: `X-Aegis-Agent/Member/Team` headers (+ hints) → `Identity(authenticated=False)`; `resolve_viewer` → `Identity(member_id=view_as or "owner", role="owner")`; list methods → `[]`; `resources()` → `{}` |
| ledger | `reserve` → `Reservation(id=new_id("res"), scopes=…, estimate)`; `status()` → `[]`; `price()` → `0.0` |
| redactor | `detect*` → `[]`; `apply` replaces finding spans with `[REDACTED]` (descending offsets, skip `redactable=False`), returns `Redaction` records; `rehydrate` → identity; `mask_for_log` masks digits (`\d→•`) and emails (`x@y→[EMAIL]`) and truncates |
| semantic | every score `ScoreResult(score=0.0, degraded=True, model="null")`; `status()` → `{"mode":"off","degraded":True,"models":[]}` |
| feed | `serial=None`; `status()` → `FeedStatus(status="disabled")`; `signatures()` → `[]` |
| approvals | **fail-closed**: `request()` → `ApprovalRequest(status="denied", summary="approvals unavailable", …)`; `find_preapproved` → `None`; `route` → `ApprovalRoute(required_role="deny")`; `vote/cancel` raise `PermissionError` |

### 2.4 Discovery (`aegis.core.discovery`, contract §2.1)

- `discover_routers()` → iterate `pkgutil.iter_modules(aegis.api.routes.__path__)`, skip `_*`, import each in `try/except` → collect `(ORDER=getattr(mod,"ORDER",100), name, mod)`; sorted; `app.include_router(mod.router)` (no prefix). Hooks `on_startup(rt)` / `on_shutdown(rt)` run in the same order inside lifespan after `rt.start()`. Failures append to `plugin_errors` (`{"module","error"}`), logged ERROR.
- `create_registry(rt)` → `pkgutil.walk_packages(aegis.controls.__path__, "aegis.controls.")`, skip modules whose last segment starts with `_`; collect `CONTROLS`; validate each has `id`, `kind`, `applies_to`, async `evaluate`; duplicate id → ERROR, first by module path wins. Registry: `all()`, `get(id)`, plus `errors`, `by_id` dict.
- `discover_adapters()` → `aegis.proxy.adapters.*` `ADAPTERS` → `dict[wire, adapter]`; the three built-in adapters are also imported directly as a fallback so a broken third-party adapter cannot remove the Anthropic path.

### 2.5 Request context, identity & session (`Pipeline.new_context`)

`rt.pipeline.new_context(source, identity, session_id=None, headers=None, approval_token=None, wait_for_approval_s=0.0, dry_run=False)`:

- `request_id = new_id("req")`; `trace_id` from `traceparent` (trace-id part) or `x-request-id`, else `request_id`; `t0 = perf_counter()`.
- `headers` → lower-cased copy with **secrets removed** (`authorization`, `x-api-key`, `proxy-authorization`, `cookie`, `set-cookie`) — rule 7.1-8.
- `session_id` when None: `X-Aegis-Session` > `x-claude-code-session-id` > `mcp-session-id` > generated `ses_<sha256(principal|YYYYMMDDHH)[:20]>` (deterministic per agent+hour, §5.2). Body-derived ids (hook `session_id`, Anthropic `metadata.user_id` JSON `.session_id`, body `session_id`) are passed in explicitly by the surface handler.
- `approval_token` default from `X-Aegis-Approval`; `wait_for_approval_s` = arg, else `X-Aegis-Wait` header (float, clamped 0–120).
- Pin policy: `ctx.policy = rt.policy.snapshot()`, `ctx.policy_version`, `ctx.feed_serial = rt.feed.serial`; `rt.sessions.get(session_id)` touched (identity, last_seen, requests += 1).

Identity for the data plane (in every handler of this workstream): `identity = await rt.org.resolve_identity(request.headers, hints=hints)` where `hints` = `{"agent_id": …}` from guard/playground bodies (demo mode only) or `{"client": "claude-code"}` when `user-agent` starts with `claude-cli` / `x-app: cli` (org-rbac maps it, e.g. to `claude-code@platform`). Header stripping before upstream: `x-aegis-*` and **only** credentials whose value starts with `aegis_` (Claude Code's `sk-ant-oat…` OAuth token passes untouched).

### 2.6 Pipeline (`aegis.core.pipeline`) — implements §3.5 exactly

`evaluate(ctx, interaction, *, policy=None, dry_run=False) -> Verdict`; internal exceptions anywhere in the core path → **fail-closed** `Verdict(action="block", primary=Decision(control_id="AEGIS-CORE", reason="internal error (fail-closed)", degraded=True))`, logged with `log.exception`.

1. **Snapshot**: `snap = policy or ctx.policy or rt.policy.snapshot()`; stamp `ctx.policy_version/feed_serial`; `interaction.id ||= new_id("int")`; `dry = dry_run or ctx.dry_run`.
2. **Select**: `rt.controls.all()` ∩ `snap.controls[id]` with `enabled` and `mode != "off"` and `control.applies_to.matches(i)` and scope match: `glob_match` of `cfg.scope.orgs/teams/members/agents` against identity fields (None field ⇒ only `"*"` matches); non-empty `scope.kinds/surfaces/destinations` narrow further. Sort `(priority, id)`.
3. **Enrich** (sequential): controls whose class overrides `BaseControl.enrich` (or that have an `enrich` attr for protocol-only objects) → `await c.enrich(ctx, i, cfg)`; errors logged, ignored.
4. **Deterministic** (`kind in {deterministic, stateful}`): sequential, each as a task with `asyncio.wait({task}, timeout=cfg.timeout_ms/1000)`; **if the task finished, its result is used even if the deadline passed** (CPU-bound sync controls cannot be interrupted anyway — this avoids spurious fail-closed blocks under load); a still-pending task is cancelled → fail-mode. Controls exceeding their budget are logged at WARNING (rate-limited) and still observed by metrics.
5. **Semantic** (`kind in {semantic, hybrid}`): skipped if phase 4 produced an enforce-mode `block`; else `asyncio.gather` of tasks, each with timeout `cfg.timeout_ms` if `"timeout_ms" in cfg.model_fields_set` else `snap.doc.defaults.semantic_timeout_ms`.
6. **Fail modes** (exception or timeout): `closed` → `Decision(action="block", degraded=True, reason="<id> unavailable (fail-closed)", control_id=id)`; `open` / `deterministic_only` → `Decision(action="allow", degraded=True, reason="<id> unavailable (fail-open)")`. Core overwrites `latency_ms` with the measured value; `None` / allow results become an implicit allow (not stored unless degraded).
7. **Monitor**: `cfg.mode == "monitor"` ⇒ `decision.mode = "monitor"`; kept in `verdict.decisions` (feed shows "would have blocked") but excluded from combination, approvals and transform.
8. **Combine**: highest `ACTION_PRECEDENCE` among enforce decisions; `primary` = first by `(precedence desc, control.priority, control_id)`; none ⇒ `allow`.
9. **Approvals** (final == `require_approval` and not `dry`): `pre = await rt.approvals.find_preapproved(ctx, i)` → found: every enforce `require_approval` decision becomes `allow` with `reason=f"approved by {', '.join(pre.decided_by)} ({pre.id})"`, `approval_id=pre.id`, recombine. Else `req = await rt.approvals.request(ctx, i, primary)`: `approved` → same as pre-approved; `denied`/`expired`/`cancelled` → primary becomes `block` (`reason += " — approval denied"`); `pending` and `ctx.wait_for_approval_s > 0` → `await rt.approvals.wait(req.id, ctx.wait_for_approval_s)` and re-check status; still pending → final `require_approval`, `verdict.approval = req`, `primary.approval_id = req.id`. Approval-service exceptions ⇒ `block` (fail-closed).
10. **Transform** (final ∈ {allow, log, redact}): spans = findings (with `segment_index/start/end`) of enforce `redact` decisions → `segments, redactions = rt.redactor.apply(ctx, i.segments, spans)` (never touches `redactable=False`); `verdict.mutations` = mutations of enforce `redact`/`allow` decisions in decision order. Final `block`/`require_approval` ⇒ `verdict.segments = []` (nothing leaves).
11. **Record** (not `dry`): WireView into an in-memory LRU (`OrderedDict`, ≤ 500 entries, 1 h TTL; `original = i.segments`, `outbound = verdict.segments`); build `DecisionSummary` (preview = `rt.redactor.mask_for_log(<outbound text of the last non-system segment>, 160)`; `entities` = sorted unique redaction + finding entities; `controls` = `ControlHit` per non-allow decision incl. monitor; `cost_usd/tokens/upstream_ms` from `ctx.state["core.outcome"]` when the handler set it — response hops); `await rt.audit.record(AuditEvent(event_type="decision", event_id=new_id("evt"), actor=identity, …, usage=outcome.usage if any, data={"summary": …, "detail": DecisionDetail-without-wire}))`; `rt.metrics.observe_verdict(ctx, i, verdict)`; `rt.bus.publish("decision", summary)`. Each sink call wrapped (`try/except` + log) — sinks never break a request. Timings: `ctx.timings["ctl"] += verdict.latency_ms`, `ctx.timings[f"ctl.{id}"] += decision.latency_ms`, phase timings → `rt.metrics.observe_overhead(phase, s)` (`enrich`, `deterministic`, `semantic`, `approvals`, `transform`, `record`).

Bookkeeping for `complete()`: `ctx.state["core.evaluated"][interaction.id] = [(control, cfg), …]` (controls whose `evaluate` ran).

`complete(ctx, interaction, verdict, outcome)`: called **exactly once** per request-direction interaction by the surface handler (guarded by `ctx.state["core.completed"]` set — a second call is a logged no-op); runs `on_complete` of the stored controls (each guarded, sequential); `rt.metrics.observe_upstream(outcome.provider or "-", outcome.model_used, (outcome.upstream_ms or 0)/1000, outcome.usage)`; `observe_overhead("total", …)`.

Extra (non-protocol) methods used only by core handlers: `attach_request_preview(decision_id, preview: dict)`; `record_only(ctx, interaction, outcome)` (allow verdict with no decisions, used for `passthrough` stream responses so usage still reaches audit + feed); `wire(decision_id)`; `attach_response(decision_id, response_raw=, response_local=)`.

### 2.7 Provider adapters (`aegis.proxy.adapters.*`, `ProviderAdapter` protocol)

Common rules: `parse_request(body, headers)` returns `Interaction(kind="model_call", surface="model.request", direction="out", model=body["model"], segments, max_output_tokens, est_input_tokens, meta)`; segment `path` is in `aegis.core.paths` grammar so `apply_segments` = deep-copy + `set_path(copy, seg.path, seg.text)` for each segment whose text changed. Non-text parts (images, documents with base64, tool definitions, `cache_control`, `metadata`, unknown fields) are **never** segments and are copied verbatim. `est_input_tokens` via `aegis.budgets.tokens.estimate_tokens` (guarded import; fallback `len(text)//4`), over segment text + `len(json.dumps(tools))`. `interaction.meta` = `{"wire", "stream", "client", "body_bytes", "n_messages"}`.

| | Anthropic Messages | OpenAI chat completions | Ollama native |
|---|---|---|---|
| request segments | `system` (str or text blocks; role `system`; **`redactable=False` for Claude Code clients** unless `providers.<p>.redact_system: true`); `messages[i].content` str or blocks: `text` → role of message; `tool_result` (str or text blocks) → `tool_result`, `trusted=False`; `tool_use.input` string leaves → `tool_args` (path `messages[i].content[j].input.<dotted>`); `thinking`/`redacted_thinking` → `redactable=False` | `messages[i].content` str or `[{type:text}]` parts; roles `system`/`developer`→`system`, `user`, `assistant`, `tool`→`tool_result` (`trusted=False`); `tool_calls[k].function.arguments` (one segment, role `tool_args`) | `/api/chat`: `messages[i].content` (+`thinking` redactable=False); `/api/generate`: `prompt` (user), `system` (system) |
| max_output | `max_tokens` | `max_completion_tokens` or `max_tokens` | `options.num_predict` |
| stream flag | `stream` (default false) | `stream` (default false); request prepared with `stream_options.include_usage=true` (remember if client asked) | `stream` **default true** |
| response segments | `content[i].text`, `content[i].input.<leaf>` (tool_args), thinking redactable=False | `choices[i].message.content`, `tool_calls[k].function.arguments` | `message.content` / `response` |
| `parse_usage` | `input = input_tokens + cache_read_input_tokens + cache_creation_input_tokens`, `cache_read_tokens`, `cache_write_tokens`, `output_tokens`, `estimated=False` | `prompt_tokens`, `completion_tokens`, `prompt_tokens_details.cached_tokens` | `prompt_eval_count`, `eval_count`, `compute_s = total_duration/1e9` |
| blocked message (200) | `{"id":"msg_aegis_…","type":"message","role":"assistant","model",…,"content":[{"type":"text","text":…}],"stop_reason":"end_turn","stop_sequence":null,"usage":{"input_tokens":0,"output_tokens":0}}`; stream → `message_start`, `content_block_start/delta/stop`, `message_delta{end_turn}`, `message_stop` (staging spike `synthetic_sse`) | `chat.completion` with `finish_reason:"stop"`; stream → role chunk, content chunk, finish chunk, usage chunk iff client asked, `data: [DONE]` | chat `{"model","created_at","message":{"role":"assistant","content":…},"done":true,"done_reason":"stop"}` / generate `{"response":…,"done":true}`; stream → NDJSON content line + done line |
| error envelope | `{"type":"error","error":{"type","message"},"aegis":{inner}}` | `{"error":{inner + "code": type}}` | `{"error":"[Aegis] …","aegis":{inner}}` |

`blocked_response(verdict, model, stream, style)` (shared logic in `aegis.core.errors.block_status()`): if `primary.http_status in {402, 429}` or `error_type in {"budget_exceeded","rate_limited","killed"}` → **wire error regardless of style**: 402 `budget_exceeded` (+`x-should-retry: false`), 429 `rate_limited` (+`retry-after: <retry_after_s or 60>`, `x-should-retry: false`), 403 `killed`; else `style="message"` → 200 synthetic reply; `style="error"` → 403 `policy_blocked` / `approval_required`. Message text:
- block: `[Aegis] Blocked by DLP-02: AWS access key detected. (decision dec_…, policy v12)`
- require_approval: `[Aegis] Approval required (apr_…, needs admin): <title>. Approve at http://127.0.0.1:8787/ui/governance/approvals?id=apr_… then retry with header X-Aegis-Approval: apr_…`
Envelope inner object always carries `control_id, decision_id, approval_id, required_role, expires_at, scope, retry_after_s` (§5.3).

### 2.8 Routing & upstream (`aegis.proxy.router`, `aegis.proxy.upstream`)

- `resolve_route(model, inbound_wire, snap, settings) -> Route(provider, cfg, wire, url_base, destination: Destination, model)`: first `models.routes` entry where `glob_match(match, model)` and (`route.wire is None or route.wire == inbound_wire`) and provider exists and (`enabled_if_env` unset or `settings.env(name)` truthy) and **provider wire == inbound wire** (cross-wire translation is out of scope → route skipped, see Contract gaps). `Destination(name=provider, dest_class=cfg.destination, provider=provider, host, url)`; model ending `:cloud` ⇒ `dest_class="remote"` even on the Ollama provider. No policy providers at all ⇒ built-in defaults (anthropic passthrough, ollama/ollama-openai/ollama-anthropic at `settings.ollama_url`, mock-anthropic/mock-openai at `127.0.0.1:8791`) so the gateway works with the Null policy. No route ⇒ 400 `invalid_request` in wire format ("no provider route for model X on the anthropic API").
- Upstream URL: anthropic `{base}/v1/messages[?query]`, count_tokens `{base}/v1/messages/count_tokens`; openai `{base}/chat/completions`; ollama `{base}/api/{op}`.
- `upstream.py`: one `httpx.AsyncClient(timeout=Timeout(connect=10, read=cfg.timeout_s, write=60, pool=10), limits=Limits(100, 20), trust_env=False, follow_redirects=False)` created in app lifespan; `set_transport(transport)` for tests. Outbound headers: inbound minus hop-by-hop (`host, content-length, connection, keep-alive, transfer-encoding, te, trailer, upgrade, proxy-connection`), minus `x-aegis-*`, minus `aegis_…` credentials; `accept-encoding: identity` (FINDINGS gotcha 11); all `anthropic-*` / `x-claude-code-*` / `x-stainless-*` / unknown headers forwarded verbatim. Auth: `passthrough_auth` → forward non-aegis `authorization`/`x-api-key`; else drop client creds; if no credential remains and `api_key_env` is set → inject (`x-api-key` for anthropic, `Authorization: Bearer` for openai). Header mutations (`target="header"`) applied last.
- Response headers forwarded: `content-type, cache-control, request-id, retry-after, x-should-retry, anthropic-*, openai-*, x-ratelimit-*`; dropped: `content-length, transfer-encoding, connection, keep-alive, date, server, content-encoding`. Upstream non-2xx bodies forwarded **unmodified** (Claude Code keys recovery off the wording). Network error → 502 `upstream_error` in wire format.

### 2.9 Model-call flow (`aegis.proxy.flow.ModelCall`) — shared by all proxies and the playground

```
ingress: raw = body bytes (≤ defaults.max_body_bytes → else 413 invalid_request); json once (orjson if present)
identity → ctx (source="proxy") → route = resolve_route(...)
req_i = adapter.parse_request(body, headers); req_i.destination = route.destination
verdict = await rt.pipeline.evaluate(ctx, req_i)
block / require_approval → adapter.blocked_response(...) → complete(Outcome(status, Usage(requests=0))) → respond
outbound = body if (no redactions and no body mutations) else adapter.apply_segments(body, verdict.segments) + body mutations
          (remove ops on list items in descending index order); raw bytes forwarded byte-identical when unchanged
route mutation (path "model"/"provider") → re-resolve; if the new destination is MORE remote than the evaluated one → re-evaluate once
          (never under-redact); header X-Aegis-Downgraded-From
attach_request_preview(dec_id, trimmed redacted outbound: model, max_tokens, stream, last 2 messages ≤ 2k chars each)
upstream send (stream or not) → upstream_ms
non-stream: resp = json; usage = adapter.parse_usage(resp); usage.cost_usd = rt.ledger.price(model, usage)
          ctx.state["core.outcome"] = Outcome(...); resp_i = adapter.parse_response(resp) (direction "in",
          destination per §3.4: remote unless agent max_destination == local; parent_id = req_i.id)
          rv = evaluate(ctx, resp_i) → block ⇒ blocked_response(style="message", status 200) ; redact ⇒ apply_segments
          rehydrate ⇒ if any enforce decision in rv has control_id DLP-08 and meta.rehydrate and defaults.rehydrate_responses:
                       rt.redactor.rehydrate(ctx, text) on assistant text segments (+ tool_args unless meta.rehydrate_tool_args is False)
          attach_response(dec_id, response_raw=<upstream text>, response_local=<rehydrated text>)
          complete(ctx, req_i, verdict, Outcome(status, usage, upstream_ms, provider, model_used, response_verdict_id=rv.id))
stream: per defaults.stream_mode (2.10); same steps on the accumulated message
headers on every response: X-Aegis-Request-Id, X-Aegis-Decision-Id, X-Aegis-Decision, X-Aegis-Policy-Version, X-Aegis-Feed-Serial,
          X-Aegis-Redactions (request + response), Server-Timing, and when applicable X-Aegis-Downgraded-From,
          X-Aegis-Budget-Remaining (from ctx.state["bud.remaining"]), X-Aegis-Approval-Id, X-Aegis-Response-Decision-Id (additive)
```

### 2.10 Streaming (`aegis.proxy.streaming`, `aegis.proxy.sse`)

- **`buffered` (contract MVP, default)**: Anthropic — forward the upstream `message_start` and `ping` events immediately (TTFB = upstream TTFB, keeps Claude Code's 5-min idle watchdog fed), synthesize `event: ping` every 15 s while waiting, buffer every other event, accumulate the final Message (accumulator ported from `staging/spikes/streaming/tests/helpers.py::accumulate_anthropic`, extended to keep `signature`, `redacted_thinking.data`, server-tool blocks, `stop_sequence`, usage merge), run the non-stream response path, then **re-synthesize** content blocks (`text` → one `text_delta`; `tool_use` → `content_block_start` with `input:{}` + one `input_json_delta`; `thinking` → `thinking_delta` + `signature_delta` byte-identical values; other block types → `content_block_start` with the full block + stop), `message_delta`, `message_stop`. If the response verdict blocks after `message_start` was already sent → emit the notice as a text block + `end_turn`. OpenAI — `: keep-alive` comments every 15 s; accumulate (`accumulate_openai`) into a `chat.completion`; re-emit chunks (usage chunk only if the client asked). Ollama — accumulate NDJSON (`accumulate_ollama`) → re-emit content line + final `done` line with the upstream counters. Upstream stream errors (`event: error` / error JSON) are forwarded unmodified.
- **`passthrough` (should)**: relay upstream bytes as they arrive (raw), tee into the accumulator for usage; output controls skipped; `pipeline.record_only(...)` + `complete(...)` in a `finally` (always runs, also on client disconnect).
- **`holdback` (could, GW-16)**: port `aegis_stream` (sans-IO transformers, 131 tests) into `aegis.proxy.stream`; `StreamOptions(vault=RedactorVault(rt.redactor, ctx), scanner=LeakScanner compiled per policy version (cached in `snap.compiled["core-gateway:leak_scanner"]`): DLP-02 secrets → block, DLP-05 canaries (`params.canaries`) → block, DLP-06 images outside `destinations.allowed_link_domains` → mask, PII/PCI → alert)`; tee accumulator; after the stream, post-hoc `evaluate(model.response)` with `meta.post_hoc=True` for audit/feed. Not implemented ⇒ log WARNING once and use `buffered`.
- `RedactorVault.resolve(key)`: `v = rt.redactor.rehydrate(ctx, key); return None if v == key else v` (only placeholders this session issued; contract placeholders `[ENTITY_N]` match the staged `PLACEHOLDER_RE`).

### 2.11 Other routes

- **`health.py`**: `GET /healthz` → `HealthResponse{status: "degraded" if any component in {down, degraded} else "ok", version, uptime_s, policy_version, feed_serial, components}` (always 200). `HEAD|GET /api/hello` → 200 `{"ok": true}` locally (no upstream call; Claude Code warm-up probe, works offline).
- **`guard.py`** `POST /v1/guard`: body (§5.1) → `Interaction` (`segments` given, or `text` → one segment role `user` (`tool_result`/`trusted=False` for `direction="in"` surfaces), plus every string leaf of `tool_args` → `TextSegment(path="tool_args.<dotted>", role="tool_args")`); destination: explicit, else by surface/tool (`destinations.local_tools` → local, `third_party_tools` → third_party, `mcp.servers[s].destination`, model calls → route); identity: body `identity` used as hints only when `settings.demo_mode`; `wait_s` (default `approvals.defaults.hold_s.guard`), `approval_id`, `dry_run`. Response always **200** `{verdict, decision_id, segments, text, approval}`. Request-direction, non-dry, allowed verdicts are parked in a pending map (TTL 600 s) for `POST /v1/guard/complete {decision_id, status_code, usage}` → `pipeline.complete` → `{ok: true}` (unknown id → 404 envelope); blocked/pending verdicts are completed immediately with `Usage(requests=0)`; expired parked entries are completed with `Outcome(status_code=499, usage=Usage(requests=0))` so reservations are released.
- **`playground.py`** `POST /api/playground` (`PlaygroundRequest` → `PlaygroundResponse`, §5.5): identity = viewer (`rt.org.resolve_viewer`) or `resolve_identity({}, hints={"agent_id": agent_id})` when impersonating; session `ses_playground_<viewer>`; source `playground`; `destination`: dest class or provider name (`local` → model `aegis-judge` via `ollama-openai`, `remote` → `mock-echo` via `mock-openai`, `third_party` → evaluate only); default surface `model.request` (also `prompt.user`, tool surfaces with `tool_name/tool_args` → `kind="tool_call"`, evaluate only). Builds an OpenAI-wire body and runs the **same `ModelCall` flow** (non-stream) when `send` and allowed; `send:false` evaluates (non-dry, so it shows in the live feed). Response: `original` (raw text), `outbound` (redacted text), `redactions`, `response{raw, local, model, provider}`, `timings{total_ms, controls:[{control_id, ms}]}`. Upstream unreachable → `response=null` + `system` warning, never 5xx.
- **`events.py`** `GET /api/events`: `sse_starlette.EventSourceResponse`; query `events=a,b` filter, `replay=n`, `view_as` (accepted, viewer resolved for RBAC; all members may read); `Last-Event-ID` → replay ring-buffer messages with `id > last`; wire format `id/event/data` per §6.3; per-connection `event: heartbeat` `{ts}` every 15 s (not stored in the ring buffer); headers `Cache-Control: no-cache`, `X-Accel-Buffering: no`; closes on client disconnect / shutdown.
- **`ui.py`** (`ORDER = 900`): `GET /` → 302 `/ui/`; `GET /ui/{path}` → file under `settings.ui_dist` (path-traversal safe via `resolve()` + `is_relative_to`), `assets/*` with `Cache-Control: public, max-age=31536000, immutable`, anything else → `index.html` (SPA fallback); dist missing → 200 HTML "Dashboard not built — run `make web`" with links to `/healthz` and `/api/events`.
- **`proxy_ollama.py`** `ANY /ollama/{path}`: `api/chat|generate` → `ModelCall` (wire ollama); `api/pull|create|push|delete|copy` → `Interaction(kind="model_call", surface="model.admin", destination=local, model=<target>, url=<registry or hf.co URL when derivable>, meta={"op", "source", "insecure", "from", "destination_model"}, segments=[modelfile text as role "document", trusted=False] if present)` → evaluate → blocked → 403 `{"error": "[Aegis] Blocked by SIG-02: …"}`; allowed → stream relay; `complete()`; `api/tags|show|version|ps|embed|embeddings` and everything else → plain passthrough (local). `ollama/v1/*` → OpenAI flow pinned to provider `ollama-openai` (could).
- **`proxy_openai.py`** `GET /v1/models`: union of exact (non-glob) `models.allowed` entries that resolve to an enabled route + `mock-echo`, `mock-sonnet` + Ollama `/api/tags` names (1 s timeout, cached 30 s); response shape satisfies both SDKs: `{"object":"list","data":[{"id","object":"model","type":"model","display_name","created","created_at","owned_by"}],"has_more":false,"first_id","last_id"}`.
- **`proxy_anthropic.py`** `POST /v1/messages/count_tokens`: MVP → local estimate `{"input_tokens": n}`; should → for remote providers evaluate with `dry_run=True` and forward the **redacted** body (never the raw body — data minimization), falling back to the estimate on block/error.

### 2.12 App factory, CLI, settings, logging

- `create_app(settings=None)`: `setup_logging`; `FastAPI(title="Aegis", version=__version__, lifespan=…, docs_url="/api/docs", openapi_url="/api/openapi.json")`; include discovered routers at creation time; lifespan: `rt = Runtime(settings); rt.build(); await rt.start(); set_runtime(rt); app.state.rt = rt; upstream client start; await on_startup hooks; publish system "gateway started policy vN"`; teardown reverse.
- Middleware (pure ASGI, not `BaseHTTPMiddleware`, so streaming is untouched): request-size guard (Content-Length > `max_body_bytes` → 413), admin token (`AEGIS_ADMIN_TOKEN` set → mutating `/api/*` requires `Authorization: Bearer <token>`; 401 envelope), uvicorn access log only if `AEGIS_ACCESS_LOG=1`.
- Exception handlers: `AegisHTTPError` → `api_error`; `RequestValidationError` → 400 `invalid_request` (wire-format for `/v1/*` and `/ollama/*`); unhandled → 500 `internal_error` envelope (wire-format on the data plane), logged with `log.exception` (no bodies).
- `Settings` (pydantic `BaseModel`, `pydantic-settings` is not a dependency): fields = §6.5 env vars lower-cased without `AEGIS_` (`host, port, policy, org_seed, pricing, data_dir, models_dir, hmac_key, feed_url, feed_pubkey, ollama_url, semantic, demo_mode, default_viewer, admin_token, ui_dist, host_map, vault_secret, log_level, log_json, access_log, test_mode, live_url`, plus `anthropic_api_key, openai_api_key, openrouter_api_key, gemini_api_key`); paths resolved relative to the repo root (`Path(__file__).parents[2]`) when relative; optional `.env` in repo root (env vars win); `env(name)` reads arbitrary env names for `providers.*.api_key_env/enabled_if_env`; `public_url` property for approval links.
- `__main__.py`: `serve [--host] [--port] [--reload] [--port-file PATH]` (binds the socket itself so `--port 0` works and writes the real port to `--port-file` and an INFO log line `aegis listening url=…`; `uvicorn.Server(Config("aegis.app:create_app", factory=True, …)).run(sockets=[sock])`; `--reload` uses the import-string path); `selftest` → `aegis.policy.selftest:main`; `verify-audit` → `aegis.audit.verify:main`; `seed` → `aegis.org.seed:main`; `reset` → refuse unless `data_dir` resolves inside the repo and ends with `data`, wipe it, copy `config/policy.golden.yaml` → `config/policy.yaml` if present, run seed; `routes` (prints method/path/module); missing targets → friendly error, exit 2.
- `log.py`: format `%(asctime)s %(levelname)-5s %(name)s | %(message)s` or JSON lines; `SecretScrubFilter` masks `sk-ant-[A-Za-z0-9_-]+`, `Bearer \S+`, `aegis_[A-Za-z0-9_]+`, `x-api-key: \S+` in every record (defence in depth; code never logs headers/bodies anyway).
- `crypto.hmac_hex(value, *, purpose="fp")` = HMAC-SHA256(key, `purpose.encode() + b"\x00" + value`) hex; key = `AEGIS_HMAC_KEY` or lazily generated 32 random bytes in `data/keys/hmac.key` (0600, created on first use, thread-safe) — no import-time side effects.
- `paths`: grammar `a.b[3].c[id=DLP-01].d[scope=team:x,window=day]`; works on dict/list (and attribute read on pydantic models for `get_path`); `set_path` creates intermediate dicts; `remove_path` returns bool, no-op when missing; `glob_match(pattern, value)` = `fnmatchcase` (None value → only `"*"`).

### 2.13 Config keys read

`defaults.{semantic_timeout_ms, stream_mode, block_response, rehydrate_responses, max_body_bytes, audit_content}`, `providers.*` (+ extra key `redact_system`), `models.routes`, `models.default_local`, `destinations.{local_tools, third_party_tools}`, `mcp.servers[*].destination` (guard destination), `approvals.defaults.hold_s` (guard/playground), `controls[*]` (selection/scope/mode/fail_mode/timeout_ms). Per-control `fail_mode` defaults are merged by policy-engine; the pipeline reads only `cfg`.

### 2.14 Events emitted

`decision` (every non-dry evaluation), `heartbeat` (per SSE connection, 15 s), `system` (`{level, message, component}` on startup, Null fallback, plugin import error, upstream unreachable from the playground, Ollama down/up transitions).

---

## 3. Reuse map (staging → owned paths; port, never import staging)

| Staging source | Destination | Adaptation |
|---|---|---|
| `staging/spikes/claude-code/proxy.py` — `HOP_BY_HOP`, `RESP_DROP`, `accept-encoding: identity`, header passthrough, `synthetic_sse()`, `anthropic_error()`, `BUDGET_MODES` (429 + `retry-after` + `x-should-retry: false`), `redact_headers()` | `proxy/upstream.py` (header policy), `proxy/adapters/anthropic.py` (`blocked_response`, synthetic SSE), `core/errors.py` (`wire_error`), `log.py` (scrub rules) | error types per contract §5.3 (`budget_exceeded` not `billing_error`, `rate_limited`, `policy_blocked`, `killed`) + `aegis` inner object; budget → 402 per contract, 429 only for rate/loop throttles |
| `staging/spikes/claude-code/proxy.py` — `summarize_body()` (metadata.user_id JSON parse, last-message trimming) | `proxy/flow.py` (`attach_request_preview`), `core/pipeline.py` session id from `metadata.user_id.session_id` | keep only redacted outbound text; never persist |
| `staging/spikes/claude-code/FINDINGS.md` facts | `health.py` (`/api/hello`), `proxy/adapters/anthropic.py` (`?beta=true`, thinking untouched, deterministic redaction), `proxy/streaming.py` (ping forwarding), budget statuses | — |
| `staging/spikes/streaming/aegis_stream/sse.py` (SSEParser, NDJSONParser, encode_sse, encode_comment) | `src/aegis/proxy/sse.py` | verbatim, imports fixed |
| `staging/spikes/streaming/tests/helpers.py` — `accumulate_anthropic`, `accumulate_openai`, `accumulate_ollama`, `anthropic_stream`, `openai_stream`, `ollama_chat_stream`, `validate_anthropic`, `validate_openai` | accumulators → `src/aegis/proxy/streaming.py` (production versions producing full wire objects); builders + validators → `tests/unit/core_gateway/streams.py` | accumulators extended (thinking `signature`, `redacted_thinking`, `stop_sequence`, ids, error passthrough); asserts → exceptions |
| `staging/spikes/streaming/tests/data/{anthropic_rehydrate.sse, openai_tool_calls.sse, ollama_chat.ndjson}` | `tests/unit/core_gateway/fixtures/` | as-is |
| `staging/spikes/streaming/aegis_stream/openai.py::prepare_openai_request` | `proxy/adapters/openai.py` | as-is |
| `staging/spikes/streaming/aegis_stream/aio.py` (`stream_transform`, `StreamController`, keep-alive + early close + always-run `on_complete`) | `proxy/streaming.py` (relay loop for passthrough/buffered keep-alives) | generic over "transformer or accumulator" |
| `staging/spikes/streaming/aegis_stream/*` (whole package) + `tests/test_*.py` (131 tests) | GW-16 only: `src/aegis/proxy/stream/` + `tests/unit/core_gateway/stream/` | hypothesis-based property tests guarded with `pytest.importorskip("hypothesis")`; detectors replaced/extended by a `RedactorDetector` wrapping `rt.redactor.detect`; `Finding` renamed `StreamFinding` to avoid clashing with `core.types.Finding` |
| research 02 §2.1.2 (stream pitfalls, keep-alive, index integrity), §2.1.4 (budget statuses), §5.4 (lifecycle stages → Server-Timing phases) | `proxy/streaming.py`, `core/timing.py` | — |
| research 03 §6.2–6.3 (fail-open/closed, degraded tagging, circuit-breaker idea) | pipeline fail modes, `degraded` flags, `/healthz` | per-control `fail_mode` only (circuit breaker = stretch, not planned) |

---

## 4. Interfaces

### 4.1 Provided (exact names from CONTRACTS §3.3; everything else is private)

- `aegis.core.runtime`: `get_runtime() -> RuntimeProto` (+ private `Runtime`, `set_runtime`).
- `aegis.core.deps`: `async get_rt(request) -> RuntimeProto`; `async viewer(request) -> Identity`; `require_role(min_role: Role)`.
- `aegis.core.errors`: `api_error(status, type, message, **fields) -> JSONResponse`; `class AegisHTTPError(Exception)` (`status, type, message, fields`).
- `aegis.core.crypto`: `hmac_hex(value: str | bytes, *, purpose: str = "fp") -> str`.
- `aegis.core.paths`: `get_path(obj, path, default=None)`, `set_path(obj, path, value)`, `remove_path(obj, path)`, `glob_match(pattern, value) -> bool`.
- `aegis.settings`: `Settings`, `get_settings()`.
- `aegis.app`: `create_app(settings: Settings | None = None) -> FastAPI` (`app.state.rt`).
- Services via `rt.`: `bus` (`EventBus`), `sessions` (`SessionStore`), `controls` (`ControlRegistry`), `pipeline` (`Pipeline`), `db()`; factories `aegis.core.bus:create`, `aegis.core.sessions:create`, `aegis.core.discovery:create_registry`, `aegis.core.pipeline:create`.
- Plug-ins: `ADAPTERS` in `aegis.proxy.adapters.{anthropic,openai,ollama}` implementing `ProviderAdapter`.
- HTTP: every route in §1.3 owned by core-gateway; headers §5.2; status codes §5.3; SSE §6.3 (`decision`, `heartbeat`, `system`).
- Pipeline semantics §3.5 (all controls rely on them) incl. `ctx.state` keys written by core: `core.evaluated`, `core.completed`, `core.outcome` (an `Outcome`, set before evaluating a response hop), `core.client` (`"claude-code"` or absent).

### 4.2 Consumed (all optional — Null fallbacks keep the gateway usable)

| From | What | If missing |
|---|---|---|
| scaffold (frozen) | `aegis.core.types`, `protocols`, `policy_schema`; empty packages; `pyproject` deps | **hard dependency** — cannot start without them |
| policy-engine | `aegis.policy.store:create` (`snapshot()`, `control_config()`), `aegis.policy.selftest:main` | Null policy (parse file once) |
| org-rbac | `aegis.org.service:create` (`resolve_identity`, `resolve_viewer`, `get_agent`), `aegis.org.seed:main` | Null org (header identity) |
| approvals-engine | `aegis.approvals.service:create` (`find_preapproved`, `request`, `wait`) | Null approvals (fail-closed deny) |
| redaction-engine | `aegis.redaction.engine:create` (`apply`, `rehydrate`, `mask_for_log`) | Null redactor (`[REDACTED]`) |
| audit-metrics | `aegis.audit.log:create`, `aegis.metrics.prom:create`, `aegis.audit.verify:main` | Null audit/metrics |
| budgets-ledger | `aegis.budgets.ledger:create` (`price`), `aegis.budgets.tokens.estimate_tokens`; BUD-01 writes `ctx.state["bud.remaining"]` (see gaps) | Null ledger; chars/4 estimate; no budget header |
| semantic-models / threat-feed | `aegis.semantic.engine:create` (`status()` for health), `aegis.feed.manager:create` (`serial`, `status()`) | Null services |
| every control owner | `CONTROLS` lists under `aegis.controls.**` | nothing enforced (allow) |
| dashboard-shell | `web/dist` built bundle | placeholder page |
| demo-mocks-docs | `mocks.mock_llm` on :8791 (models `mock-echo`, `mock-sonnet`) | proxies return 502 `upstream_error`; playground shows evaluation only |

### 4.3 Contract gaps (proposed addenda — additive, no conflicting shapes)

1. **`ctx.state["bud.remaining"]`** (str, e.g. `"usd=0.42;scope=team:research"`): BUD-01 sets it during `evaluate`; core copies it into `X-Aegis-Budget-Remaining` (§5.2 lists the header but no source). → budgets-ledger.
2. **Response-hop context**: core sets `ctx.state["core.outcome"] = Outcome(...)` (usage priced with `rt.ledger.price`) *before* evaluating `model.response`, so the response decision's `DecisionSummary.cost_usd/tokens/upstream_ms` and `AuditEvent.usage` are populated. Usage is audited on the response decision (no separate "usage" audit event type exists). → audit-metrics (index those fields from response decisions).
3. **Cross-wire routing is unsupported**: a `models.routes` entry whose provider wire differs from the inbound wire is skipped (e.g. OpenAI-wire request for `claude-*`). Clarify in §4.3 comments. → policy-engine (route table comments).
4. **`count_tokens` forwarding** forwards only the **dry-run-redacted** body (contract says "forwarded upstream"; forwarding raw would leak PII the main call redacts).
5. **Interaction conventions set by core adapters** (for control owners): `meta.wire`, `meta.stream`, `meta.client` (`"claude-code"`), `meta.body_bytes`; Anthropic `system` segments are `redactable=False` for Claude Code clients (attribution block / cache safety) unless `providers.<p>.redact_system: true` (extra key); tool definitions are **not** segments; `model.admin` shape = `model`, `url`, `meta.op ∈ {pull,create,push,delete,copy}`, `meta.source/from/insecure/destination_model`, optional modelfile segment (role `document`, `trusted=False`). → threat-feed (SIG-02), budgets-ledger (BUD-02), org-rbac (GOV-02), metadata-egress (DLP-03).
6. **Holdback mode semantics** (GW-16): in-stream enforcement by a scanner compiled from DLP-02/05/06 params; the `model.response` verdict is computed post-hoc with `meta.post_hoc=True` (audit/feed only). Controls on `model.response` must tolerate `meta.post_hoc`.
7. **Additive response header** `X-Aegis-Response-Decision-Id` (response-hop verdict) next to the request-hop `X-Aegis-Decision-Id`.
8. **Deterministic timeouts**: a control task that completed is always used even if past `timeout_ms` (only awaiting controls can time out). Staged policy values `timeout_ms: 2/5` for deterministic controls are too tight for `asyncio.to_thread` offloading → **request policy-engine to default deterministic controls to ≥ 50 ms**.
9. **Per-agent `Agent.profile`** is not applied by the pipeline (needs per-profile control configs). Optional addendum: policy-engine publishes `snap.compiled["policy-engine:profile_controls"][<profile>] -> dict[id, ControlConfig]`; core would then select those for agents with a profile override (`could`, not planned).
10. **Kill switch on the Anthropic wire**: contract says 403 `killed`; Claude Code renders 403 as "Failed to authenticate" (FINDINGS). We keep 403 and put `[Aegis] kill switch active for <scope>` in the message. Optional addendum: map `killed` to 429 + `x-should-retry: false` on the Anthropic wire only.
11. `aegis.core.crypto` is in the §3.3 public-surface table but missing from the §1.1 tree; core-gateway creates it under its owned `core/`.

---

## 5. Tasks

Estimates assume one strong implementer; **must ≈ 125 min** (≈ 65 + 60 when split at GW-08 between two implementers), should ≈ 35 min, could ≈ 40 min. If only one implementer and time is short, the must path that keeps every other workstream unblocked is GW-01 → 03 → 04 → 05 → 06 → 07 → 11 (guard) — the proxies (GW-08…10) come right after. Each task ends with `uv run --frozen ruff check` on the touched files.

### GW-01 — Public surfaces first (interfaces-first)
- [ ] `settings.py` (`Settings`, `get_settings`, `.env`, `env()`, path resolution, `public_url`)
- [ ] `log.py` (`setup_logging`, `SecretScrubFilter`, JSON mode)
- [ ] `core/crypto.py` (`hmac_hex`, lazy key file 0600)
- [ ] `core/paths.py` (grammar incl. `[key=value,…]`, `glob_match`)
- [ ] `core/errors.py` (`api_error`, `AegisHTTPError`, `wire_error(wire, …)`, `block_status(decision)`)
- [ ] `core/deps.py` (`get_rt`, `viewer`, `require_role`) + `core/runtime.py` skeleton with `get_runtime()`
- [ ] `app.py` stub `create_app()` returning a FastAPI with lifespan placeholder (so others can import immediately)
- **priority** must · **demo_critical** yes · **estimate** 12 min · **deps** frozen files from scaffold

### GW-02 — Event bus, DB, sessions
- [ ] `core/bus.py`: ring buffer 1000, monotonic ids, `publish` (dumps pydantic `mode="json", by_alias=True`; thread-safe via `call_soon_threadsafe` when off-loop), `subscribe(events, replay)` async iterator with per-subscriber bounded queue (drop-oldest + counter), `recent(n, events)`, `since(last_id)` helper for `Last-Event-ID`
- [ ] `core/db.py`: `connect()`, `CREATE TABLE IF NOT EXISTS sessions …` (§6.1)
- [ ] `core/sessions.py`: `SessionStore.get/all`, LRU (10 000) + idle TTL 24 h, write-behind flush every 5 s (off in test mode) + flush on stop; `resolve_session_id(headers, body_hint, principal)`
- **priority** must · **demo_critical** yes · **estimate** 8 min · **deps** GW-01

### GW-03 — Runtime + Null fallbacks
- [ ] `core/nulls.py`: 9 Null services per §2.3 table (each satisfies its Protocol; `isinstance` checks in tests)
- [ ] `core/runtime.py`: `SERVICE_TABLE`, `build/start/stop`, fallback-on-error (import, `create`, `start`), `component_status()`, `db()`, Ollama probe (non-test mode), `system` events for fallbacks
- **priority** must · **demo_critical** yes · **estimate** 12 min · **deps** GW-01, GW-02

### GW-04 — Discovery
- [ ] `discover_routers()` with ORDER sort, `on_startup/on_shutdown`, error capture
- [ ] `create_registry(rt)` (`walk_packages`, `CONTROLS`, duplicate detection, shape validation)
- [ ] `discover_adapters()` with built-in fallback
- **priority** must · **demo_critical** yes · **estimate** 6 min · **deps** GW-03

### GW-05 — Pipeline orchestrator (§3.5)
- [ ] `new_context` (§2.5), `evaluate` steps 1–11 (§2.6) with fail-closed core, monitor, combine/primary ties, approval flow, transform, record (WireView LRU, DecisionSummary/DecisionDetail builders, audit, metrics, bus, timings)
- [ ] `complete` (exactly-once guard, `on_complete`, metrics), `wire`, `attach_response`, `attach_request_preview`, `record_only`
- [ ] `create(rt)` factory
- **priority** must · **demo_critical** yes · **estimate** 22 min · **deps** GW-03, GW-04

### GW-06 — App factory + CLI
- [ ] `create_app`: lifespan (Runtime, `set_runtime`, upstream client, `on_startup` hooks, startup `system` event), routers included at creation, ASGI middleware (body-size guard, admin token), exception handlers (envelope vs wire format by path prefix)
- [ ] `__main__.py`: `serve` (`--port 0`, `--port-file`, `--reload`), `selftest`, `verify-audit`, `seed`, `reset` (safety checks), `routes`, `version`
- **priority** must · **demo_critical** yes · **estimate** 8 min · **deps** GW-03, GW-04

### GW-07 — Health, UI and live events routes
- [ ] `health.py` (`/healthz`, `HEAD|GET /api/hello`)
- [ ] `ui.py` (ORDER 900, static + SPA fallback + traversal guard + placeholder page)
- [ ] `events.py` (EventSourceResponse, filters, replay, `Last-Event-ID`, per-connection heartbeat, disconnect handling)
- **priority** must · **demo_critical** yes · **estimate** 8 min · **deps** GW-06

### GW-08 — Anthropic adapter, router, upstream
- [ ] `proxy/router.py` (`resolve_route`, wire filter, `enabled_if_env`, `:cloud` ⇒ remote, built-in fallback providers, URL builders)
- [ ] `proxy/upstream.py` (client lifecycle, `set_transport`, outbound header policy incl. auth passthrough/injection and header mutations, response header filter, 502 mapping)
- [ ] `proxy/adapters/anthropic.py` (parse_request/response, apply_segments, parse_usage, blocked_response JSON + SSE, Claude Code detection, `redact_system` handling)
- **priority** must · **demo_critical** yes · **estimate** 15 min · **deps** GW-01 (can run in parallel with GW-02…07)

### GW-09 — ModelCall flow, buffered streaming, `/v1/messages`
- [ ] `proxy/sse.py` (port), `proxy/streaming.py` (accumulators + synthesizers for 3 wires; Anthropic early `message_start`/`ping` forwarding + 15 s pings; OpenAI keep-alive comments)
- [ ] `proxy/flow.py` (§2.9: ingress, evaluate, block/approval responses, apply segments + mutations, byte-identical forward when unchanged, route re-resolve + re-evaluate when more remote, upstream, response evaluation, rehydration, attach wire view, `complete` in `finally`, X-Aegis headers + Server-Timing via `core/timing.py`)
- [ ] `proxy_anthropic.py`: `POST /v1/messages` (`?beta=true` ok), `POST /v1/messages/count_tokens` (local estimate)
- **priority** must · **demo_critical** yes · **estimate** 15 min · **deps** GW-05, GW-08

### GW-10 — OpenAI adapter + routes
- [ ] `proxy/adapters/openai.py` (incl. `prepare_openai_request`, usage-chunk hiding in synthesized streams)
- [ ] `proxy_openai.py`: `POST /v1/chat/completions`, `POST /openai/v1/chat/completions` (same handler)
- **priority** must · **demo_critical** yes · **estimate** 8 min · **deps** GW-09

### GW-11 — `/v1/guard` + playground
- [ ] `guard.py` (§2.11: interaction builder from body, tool_args leaf segments, destination classification, demo-mode identity hints, wait/approval/dry_run, always-200 response, parked completions + TTL sweep, `/v1/guard/complete`)
- [ ] `playground.py` (§2.11: viewer/impersonation identity, destination/model mapping, ModelCall reuse, PlaygroundResponse incl. timings; never 5xx on upstream failure)
- **priority** must · **demo_critical** yes · **estimate** 10 min · **deps** guard: GW-05, GW-06 · playground: GW-09, GW-10

### GW-12 — Ollama native proxy + `/v1/models`
- [ ] `proxy/adapters/ollama.py` (chat + generate; default `stream: true`)
- [ ] `proxy_ollama.py` (chat/generate via flow; `model.admin` ops evaluated + streamed relay; passthrough for tags/show/version/ps/embed)
- [ ] `GET /v1/models` (union list, dual-SDK shape, Ollama tags cache)
- **priority** should · **demo_critical** no (research-agent may use OpenAI wire to Ollama) · **estimate** 12 min · **deps** GW-09

### GW-13 — Telemetry polish
- [ ] Server-Timing per-control entries (`ctl-DLP-01;dur=…`, top 8 by time) + `desc` strings; `X-Aegis-Budget-Remaining`, `X-Aegis-Downgraded-From`, `X-Aegis-Approval-Id`, `X-Aegis-Response-Decision-Id`
- [ ] `observe_overhead` phases (`total`, `pipeline`, per §2.6 phases); `system` events for Ollama up/down and plugin errors
- **priority** should · **demo_critical** yes (perf story) · **estimate** 8 min · **deps** GW-09

### GW-14 — Passthrough stream mode + redacted count_tokens forward
- [ ] `stream_mode: passthrough` relay (tee accumulator, `record_only`, `complete` in `finally`, client-disconnect safe)
- [ ] `count_tokens`: dry-run evaluate → forward redacted body for remote providers; estimate fallback
- [ ] `stream_mode: holdback` unimplemented ⇒ WARNING once + buffered
- **priority** should · **demo_critical** no · **estimate** 10 min · **deps** GW-09

### GW-15 — Policy snippet
- [ ] write `config/snippets/core-gateway.yaml` (content in §7 below) with comments explaining each provider/route
- **priority** should · **demo_critical** yes (policy-engine merges providers/routes from it) · **estimate** 4 min · **deps** none

### GW-16 — Holdback streaming (stretch)
- [ ] port `aegis_stream` → `src/aegis/proxy/stream/` (+ tests, hypothesis guarded); `RedactorVault`; `RedactorDetector`; per-policy `LeakScanner` cache in `snap.compiled["core-gateway:leak_scanner"]`
- [ ] flow integration for 3 wires (`stream_transform` with `StreamController`), tee accumulator, post-hoc `model.response` evaluation (`meta.post_hoc=True`), findings → `system`/audit
- [ ] active-stream registry + bus subscription to `killswitch` events → `StreamController.abort()` for matching agent/session scopes (in-flight streams cut, scenario F6)
- **priority** could · **demo_critical** no · **estimate** 30 min · **deps** GW-09, GW-14

### GW-17 — Claude Code body-size optimisations (stretch)
- [ ] session segment-hash memory: `interaction.meta["fresh_segments"]` = indexes of segments whose sha256 was not seen earlier in this session (hint for expensive controls; redaction still runs everywhere)
- [ ] orjson fast path for parse/dump; skip re-serialization when unchanged (already in GW-09) — measure 1 MB body overhead
- **priority** could · **demo_critical** no · **estimate** 10 min · **deps** GW-09

### Verification tasks

| ID | Verifies | Command / check | Expected |
|---|---|---|---|
| **GW-V01** | GW-01…06 boot with only frozen + core | `AEGIS_TEST_MODE=1 AEGIS_SEMANTIC=off AEGIS_DATA_DIR=$(mktemp -d) uv run --frozen python -c "from aegis.app import create_app; a=create_app(); print(sorted(r.path for r in a.routes))"` | prints all core routes; no traceback even if other workstreams' modules are missing/broken |
| **GW-V02** | unit suite | `uv run --frozen pytest tests/unit/core_gateway -q` | all pass, < 10 s, no fixed ports, no network |
| **GW-V03** | paths/crypto/bus/sessions | `tests/unit/core_gateway/test_paths.py`, `test_crypto.py` (stable per key, differs per purpose, key file 0600), `test_bus.py` (replay, `since`, filter, drop-oldest, slow subscriber does not block publish), `test_sessions.py` (resolution order, deterministic generated id) | pass |
| **GW-V04** | runtime fallbacks | `test_runtime.py`: monkeypatch `SERVICE_TABLE` with a factory that raises on import / `create` / `start` → app boots, `/healthz` 200 with that component `down`, `status: degraded`; a `system` event is in `bus.recent()`; a broken module in a temp `aegis.controls` sub-package → `components.plugins == "degraded"` | pass |
| **GW-V05** | pipeline semantics §3.5 | `test_pipeline.py` with fake controls + fake services (`tests/unit/core_gateway/fakes.py`): scope/applies_to selection, `mode: off` skipped, monitor never affects action, precedence + primary tie-break, semantic skipped after deterministic block, timeout → closed/open/deterministic_only, completed-late task still used, enrich errors ignored, pre-approved → allow with reason, auto-approved, denied → block, pending + wait, approvals exception → block, redact spans → `rt.redactor.apply`, mutations collected (and not when final block), dry_run → no approvals/record, record → audit + bus `decision` + metrics called once, WireView LRU eviction, `complete` exactly once | pass |
| **GW-V06** | adapters | `test_adapter_anthropic.py` on a synthetic Claude Code-shaped body (system blocks incl. attribution text, 7 `<system-reminder>` text blocks, `thinking` + `signature`, `tool_use`, `tool_result` list, `cache_control`, `metadata.user_id` JSON string): identity `apply_segments` ⇒ equal dict; redacting one user segment changes only that path; thinking/system untouched for Claude Code UA; `parse_usage` with cache fields; same for OpenAI (string + parts content, tool_calls arguments, include_usage injection) and Ollama (chat/generate, default stream true) | pass |
| **GW-V07** | buffered streaming | `test_streaming.py`: accumulate → synthesize → accumulate round-trip equals for the 3 staged fixtures + builder streams with tool calls/thinking; synthesized Anthropic stream passes the ported `validate_anthropic` (contiguous indices, message_delta before message_stop); OpenAI passes `validate_openai` and hides the usage chunk when the client did not ask; upstream `event: error` forwarded verbatim | pass |
| **GW-V08** | data-plane end-to-end (in-process ASGI app + `httpx.MockTransport` fake upstream) | `test_proxy_anthropic.py`: JSON + `stream:true` happy path; request headers seen upstream contain `anthropic-beta`, `anthropic-version`, `authorization: Bearer sk-ant-oat…` (fake), `accept-encoding: identity`, and **no** `x-aegis-*` / `aegis_…` key; response headers contain `server-timing` with `aegis;dur=`, `ctl;dur=`, `upstream;dur=` and all `X-Aegis-*`; fake block control → **200** synthetic message (JSON and SSE variants, SSE validates); `http_status=402` decision → 402 `budget_exceeded` + `x-should-retry: false`; `http_status=429, retry_after_s=30` → 429 + `retry-after: 30` + `x-should-retry: false`; `block_response: error` → 403 wire envelope with `aegis` inner object; upstream 529 body forwarded unmodified; upstream connection error → 502 `upstream_error`; `HEAD /api/hello` → 200; `?beta=true` accepted; unchanged request forwarded byte-identical | pass |
| **GW-V09** | redact + rehydrate loop | same harness with a fake DLP control (redact span → Null/fake redactor placeholder `[EMAIL_1]`) + fake DLP-08 decision (`meta.rehydrate=True`): upstream receives only `[EMAIL_1]`; client receives the original email; `rt.pipeline.wire(dec)` has original/outbound/response_raw/response_local | pass |
| **GW-V10** | guard, playground, events | `test_guard.py` (always 200, tool_args leaf segments `tool_args.to`, `/v1/guard/complete` → `on_complete` called once, unknown id 404, parked TTL sweep); `test_playground.py` (send:false → verdict + feed event; send:true with fake upstream → `response.local` rehydrated, timings present; upstream down → `response: null`, status 200); `test_events.py` drives the events generator directly (ASGITransport buffers streaming bodies) — replay + filter + Last-Event-ID + heartbeat; plus one `@pytest.mark.slow` test running uvicorn on port 0 in a thread and reading the first `decision` event over real HTTP | pass |
| **GW-V11** | live smoke (ephemeral port, no fixed ports) | `PF=$(mktemp); AEGIS_TEST_MODE=1 uv run --frozen python -m aegis serve --port 0 --port-file $PF & sleep 2; P=$(cat $PF); curl -sI http://127.0.0.1:$P/api/hello; curl -s http://127.0.0.1:$P/healthz; curl -sN "http://127.0.0.1:$P/api/events?replay=5" --max-time 3; curl -sI http://127.0.0.1:$P/ ; kill %1` | `HTTP/1.1 200`; HealthResponse JSON; `event: system` lines; `302` to `/ui/`; process exits cleanly |
| **GW-V12** | overhead budget | `test_overhead.py` (`@pytest.mark.bench`): 300 `/v1/messages` calls through ASGI with Null services + 3 trivial fake controls + MockTransport upstream; parse `Server-Timing aegis;dur` | p50 < 5 ms, p95 < 15 ms on the dev Mac (report numbers in the implementer report for the deck) |
| **GW-V13** | integration with mocks (after demo-mocks-docs lands; integration window only) | `make up`, then `curl -s localhost:8787/v1/messages -H 'content-type: application/json' -H 'anthropic-version: 2023-06-01' -H 'X-Aegis-Agent: trading-copilot@trading' -d '{"model":"mock-echo","max_tokens":64,"messages":[{"role":"user","content":"PESEL 44051401359 email jan@example.com"}]}' -D -` and `curl -s localhost:8791/_mock/requests?limit=1` | client reply shows real values (rehydrated), mock log shows placeholders only; `X-Aegis-Decision: redact`; live feed row appears |
| **GW-V14** | Claude Code passthrough (manual, integration window, uses subscription quota ≈ $0.01) | with the stack up: `cd demo/claude/project && env -i HOME=$HOME PATH=$PATH claude -p "say hi" --settings ../settings.json --model haiku < /dev/null` | reply printed, exit 0; feed shows `allow` rows for `claude-code@platform`; gateway log shows no 401 (OAuth `anthropic-beta` forwarded) |
| **GW-V15** | lint | `uv run --frozen ruff check src/aegis/__main__.py src/aegis/app.py src/aegis/settings.py src/aegis/log.py src/aegis/core src/aegis/proxy src/aegis/api/routes/{health,proxy_anthropic,proxy_openai,proxy_ollama,guard,events,playground,ui}.py tests/unit/core_gateway` (exclude frozen files) | no errors |

---

## 6. Demo cut

**Must really work live**
- `POST /v1/messages` JSON + SSE (buffered) with Claude Code OAuth passthrough, `HEAD /api/hello`, deterministic redaction round-trip (placeholders out, real values back), synthetic 200 block/approval messages, 402 / 429 (+`x-should-retry: false`) budget stops.
- `POST /v1/chat/completions` JSON + SSE (mock-openai, ollama-openai), used by scripted agents.
- `/v1/guard` (+ `/complete`), `/api/playground` (evaluate + send to `mock-echo` / `aegis-judge`), `/api/events` live feed, `/healthz`, `/ui` static serving.
- Pipeline §3.5 complete incl. approvals, monitor mode, fail modes, policy snapshot pinning, audit/metrics/bus recording; Null fallbacks; Server-Timing + X-Aegis headers.

**May be simplified / stubbed convincingly**
- Streaming is `buffered` (whole answer appears at once; TTFB preserved via early `message_start`). `holdback` falls back to buffered with a log line; `passthrough` is a raw relay (should).
- `count_tokens` returns a local estimate (Claude Code's `/context` tolerates estimates).
- `/v1/models` is a static union from policy + mocks (+ cached Ollama tags).
- Ollama native: chat/generate governed; admin ops evaluated then relayed; embeddings passthrough.
- No cross-wire translation (route skipped → 400 with a clear message).
- Sessions persisted best-effort (in-memory authoritative).
- In-flight stream cut on kill switch only with GW-16; otherwise the next request is blocked by EXE-04 (instant enough for the runaway-agent demo).

---

## 7. Snippet for `config/snippets/core-gateway.yaml`

```yaml
# core-gateway expectations (policy-engine merges into config/policy.yaml). No controls are owned by core-gateway.
defaults:
  stream_mode: buffered          # buffered (MVP) | passthrough (no output controls) | holdback (stretch; falls back to buffered)
  block_response: message        # model proxies: 200 synthetic "[Aegis] Blocked by …" reply; "error" = 403 wire error
  rehydrate_responses: true
  max_body_bytes: 8000000        # Claude Code resends multi-MB histories
  semantic_timeout_ms: 400
providers:
  anthropic:        {wire: anthropic, base_url: "https://api.anthropic.com", destination: remote, passthrough_auth: true, api_key_env: ANTHROPIC_API_KEY, redact_system: false}
  openai:           {wire: openai, base_url: "https://api.openai.com/v1", api_key_env: OPENAI_API_KEY, enabled_if_env: OPENAI_API_KEY}
  openrouter:       {wire: openai, base_url: "https://openrouter.ai/api/v1", api_key_env: OPENROUTER_API_KEY, enabled_if_env: OPENROUTER_API_KEY}
  ollama:           {wire: ollama, base_url: "http://127.0.0.1:11434", destination: local, timeout_s: 300}
  ollama-openai:    {wire: openai, base_url: "http://127.0.0.1:11434/v1", destination: local, timeout_s: 300}
  ollama-anthropic: {wire: anthropic, base_url: "http://127.0.0.1:11434", destination: local, timeout_s: 300}
  mock-anthropic:   {wire: anthropic, base_url: "http://127.0.0.1:8791", destination: remote, timeout_s: 30}
  mock-openai:      {wire: openai, base_url: "http://127.0.0.1:8791/v1", destination: remote, timeout_s: 30}
models:
  routes:                        # first match wins; provider wire must equal the inbound wire (no translation)
    - {match: "mock-*",       provider: mock-anthropic, wire: anthropic}
    - {match: "mock-*",       provider: mock-openai,    wire: openai}
    - {match: "claude-*",     provider: anthropic,      wire: anthropic}
    - {match: "gpt-*",        provider: openai,         wire: openai}
    - {match: "meta-llama/*", provider: openrouter,     wire: openai}
    - {match: "*",            provider: ollama-openai,    wire: openai}
    - {match: "*",            provider: ollama,           wire: ollama}
    - {match: "*",            provider: ollama-anthropic, wire: anthropic}
  default_local: aegis-judge
```

---

## 8. Dependencies

Python runtime (all in §7.6): `fastapi`, `uvicorn[standard]` (uvloop, httptools), `httpx`, `pydantic>=2.9`, `sse-starlette`, `pyyaml` (Null policy parse), `orjson` (optional fast path, guarded import), `python-multipart` (not needed; no forms). No `pydantic-settings` (Settings is a plain `BaseModel`).
Python dev (in §7.6): `pytest`, `pytest-asyncio`, `asgi-lifespan`, `ruff` (`respx` not needed — `httpx.MockTransport`).
**Deps requested (optional):** `hypothesis` (dev) — only to run the ported property tests in GW-16; tests skip cleanly without it.
No npm dependencies.

---

## 9. Risks & mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | Re-synthesized SSE breaks Claude Code (retries, "response incomplete", thinking-signature errors) | Forward upstream `message_start`/`ping` verbatim; re-emit thinking/signature byte-identical values; contiguous indices; always end with `message_delta` + `message_stop`; protocol validators in tests (GW-V07); live switch `stream_mode: passthrough` as an escape hatch; GW-V14 manual check early in the integration window |
| 2 | Spurious fail-closed blocks from tight deterministic timeouts (staged policy uses 2–5 ms) | Completed-late tasks are always used; only awaiting controls can time out; WARNING log + metrics; request policy-engine to default deterministic `timeout_ms ≥ 50` (gap 8) |
| 3 | Multi-MB Claude Code bodies make every hop slow | Parse once (orjson if present), forward raw bytes when unchanged, only text leaves become segments (no tool schemas), `fresh_segments` hint (GW-17); overhead benchmark GW-V12 |
| 4 | Body rewriting invalidates prompt cache / signatures | Redaction is deterministic per session (redaction-engine), system blocks of Claude Code non-redactable by default, thinking never touched, unknown fields/`cache_control` copied verbatim |
| 5 | Another workstream's service raises in the hot path | Every `rt.*` call in the pipeline/flow is wrapped: sinks swallow + log; approvals errors fail closed; redactor errors on transform → fail-closed block (never forward unredacted) |
| 6 | Null fallbacks silently hide broken services | `/healthz` components, `system` SSE toast on fallback, ERROR logs with the import error |
| 7 | `httpx.ASGITransport` buffers streaming responses → SSE tests hang | Test generators directly; one slow test on a real ephemeral-port uvicorn |
| 8 | Credentials leak via logs or the wire view | `ctx.headers` sanitized, `SecretScrubFilter`, no header/body logging, WireView in memory only (never audited), `audit_content: false` honoured |
| 9 | Kill switch 403 shows "Failed to authenticate" in Claude Code | Message text names the kill switch; optional addendum (gap 10) |
| 10 | Audit write latency on the hot path | Measure in GW-V12; if p50 > 2 ms, move `record()` to a bounded background queue with `pipeline.flush()` for tests (keeps semantics: one audit event per verdict) |
| 11 | Shared 8 GB machine / port collisions | No fixed ports in tests (ASGI, `--port 0 --port-file`); Ollama probe disabled in test mode; one `httpx` client pool |
| 12 | Scope too large for one implementer | Ordered must → should → could; split point GW-08 for a second implementer; buffered streaming covers all wires with one accumulate/synthesize design |
