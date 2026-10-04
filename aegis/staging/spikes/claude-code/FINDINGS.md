# Spike: Claude Code ↔ Aegis integration (empirical)

Run 2026-10-03 against real `api.anthropic.com` with a claude.ai **Team subscription (OAuth)**.
- PATH `claude` = **2.1.271**; the Claude desktop app bundles **2.1.286** (used for hint-header checks).
- Model `--model haiku` → `claude-haiku-4-5-20251001`.
- Isolation for every run: `env -i`, `--settings settings/*.json --setting-sources project --strict-mcp-config --no-session-persistence`, `-p --output-format stream-json`, `cwd=project/` (contains a FAKE `.env`). No user or managed settings were touched. ~20 runs ≈ $0.12 notional quota.

## TL;DR

| # | Assumption | Result |
|---|---|---|
| 1 | Passthrough via `ANTHROPIC_BASE_URL` with subscription OAuth | **Works** if `Authorization: Bearer sk-ant-oat…` and `anthropic-beta: oauth-2025-04-20,…` are forwarded verbatim; SSE relayed byte-for-byte. Only `HEAD /api/hello` (no auth) and `POST /v1/messages?beta=true` are seen. |
| 1b | Session / hint headers | `x-claude-code-session-id` on both versions = hook `session_id` = `metadata.user_id.session_id`. `x-claude-code-request-class: main` and `x-claude-code-prompt-id` (= hook `prompt_id`) **only on 2.1.286** → run `claude update` on the demo machine. |
| 2 | Rewrite user text (PAN → `[CARD_1]`) | **Works.** Answer was `[CARD_1]`; the next request replays signed `thinking` + `tool_use` plus the rewritten user turn → 200, no signature error, full cache hit (`cache_read 10379`). |
| 2b | Non-deterministic placeholder | No API error, but the prompt cache is lost (re-created tokens). **Placeholders must be deterministic per session.** |
| 3 | Fail-closed PreToolUse hook | `curl … \| sh` and `Read .env` both denied; the reason reaches Claude **verbatim** as a `tool_result` with `is_error: true`; deny beats `--allowedTools`; endpoint down → deny; slow gateway (script timeout 2 s < settings timeout 5 s) → deny. |
| 3b | Hook fail-OPEN cases | Missing hook executable (exit 127) → **tool ran**; settings `timeout` firing before the script's own timeout → **tool ran**. |
| 4 | Budget stop | One attempt then clean exit for `429` + `retry-after: 3600`; `429` + `x-should-retry: false`; `402`; `403`; `400`. Plain `429` → **11 attempts over 175 s**. A synthetic `200` SSE message ends the run with exit 0. |

## Working settings (`settings/spike.json`)

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:18787",
    "ANTHROPIC_CUSTOM_HEADERS": "X-Aegis-Team: blue\nX-Aegis-Agent: claude-code",
    "CLAUDE_CODE_GATEWAY_HINT_HEADERS": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
  },
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python3 /ABS/hook.py http://127.0.0.1:18787/hook", "timeout": 5 }] }],
    "PreToolUse": [{ "matcher": "*", "hooks": [{ "type": "command", "command": "python3 /ABS/hook.py http://127.0.0.1:18787/hook", "timeout": 5 }] }]
  }
}
```
`--settings` `env.ANTHROPIC_BASE_URL` wins over an inherited env var (the desktop app exports `ANTHROPIC_BASE_URL=https://api.anthropic.com`; traffic still hit the proxy).

## Hook (`hook.py`, stdlib-only, ~60 ms p50)
- POSTs stdin to `/hook` with an internal 2 s timeout, ignores proxy env vars.
- 2xx → print the returned JSON, exit 0 (empty `{}` = no decision).
- **Any failure → reason on stderr, exit 2** (the only blocking non-zero code).
- Gateway deny response:
  ```json
  {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"AEGIS-DENY CC-010 pipe-to-shell: …"}}
  ```
- PreToolUse input (2.1.271): `cwd, hook_event_name, permission_mode, prompt_id, session_id, tool_input, tool_name, tool_use_id, transcript_path`; `file_path` arrives absolute. `UserPromptSubmit` receives the raw `prompt` (including PANs) — it can block but not rewrite.
- After exit 2 the model sees `PreToolUse:Bash hook error: [<full hook command>]: <stderr>` → never put tokens in hook command args.

## Headers on `/v1/messages`
- Request (2.1.271): `authorization`, `anthropic-version: 2023-06-01`, `anthropic-beta: oauth-2025-04-20,interleaved-thinking-2025-05-14,thinking-token-count-2026-05-13,context-management-2025-06-27,prompt-caching-scope-2026-01-05,claude-code-20250219,extended-cache-ttl-2025-04-11`, `anthropic-dangerous-direct-browser-access: true`, `x-app: cli`, `user-agent: claude-cli/2.1.271 (external, sdk-cli)`, `x-claude-code-session-id`, `x-stainless-*` (retry-count stays 0), custom `x-aegis-*`, `accept-encoding: gzip, deflate, br, zstd`.
- 2.1.286 adds `x-claude-code-prompt-id`, `x-claude-code-request-class`. In the 2.1.286 binary but not observed: `agent-id`, `parent-agent-id`, `agent-type`, `compaction`, `prev-tool-durations`.
- Response headers to forward: `content-type: text/event-stream; charset=utf-8`, `cache-control`, `request-id`, `anthropic-organization-id`, `anthropic-workspace-id` (redact in logs), `anthropic-ratelimit-unified-{status,reset,representative-claim,fallback-percentage,5h-status,5h-utilization,5h-reset,overage-*}`.
- Body: `thinking: {enabled, budget 31999}`, `max_tokens 32000` even on Haiku; `metadata.user_id` is a JSON string `{device_id, account_uuid, session_id}`; the first user message holds 7–8 `system-reminder` text blocks (cwd, git user/status, CLAUDE.md contents, email, date, model) with the prompt last.

## Budget-stop behaviour (Anthropic error bodies)

| Mode | Attempts | Exit | User sees |
|---|---|---|---|
| 429 + retry-after 3600 (± x-should-retry false) | 1 | 1 | `API Error: Server is temporarily limiting requests (not your usage limit) · <msg>` |
| 429 + x-should-retry false only | 1 | 1 | same |
| 429 plain | 11 (≈175 s of backoff) | 1 | same; `api_retry` events in stream-json |
| 402 billing_error | 1 | 1 | `API Error: 402 <msg>` |
| 403 permission_error | 1 | 1 | `Failed to authenticate. API Error: 403 <msg>` (avoid) |
| 400 | 1 | 1 | `API Error: 400 <msg>` |
| 200 synthetic SSE | 1 | 0 | `<msg>` as the assistant reply |

**Recommendation:** hard budget stop = `429` + `retry-after: 3600` + `x-should-retry: false` (or `402`); policy blocks shown to the user = synthetic `200` assistant message.

## Gotchas
1. Hooks fail OPEN when the hook executable is missing (exit 127) or Claude Code's hook `timeout` fires first → keep script timeout < settings timeout, absolute paths, a SessionStart self-check, `permissions.deny` backstops, managed settings only in a hardened demo profile.
2. 2.1.271 has no hint headers → key the vault and budgets on `x-claude-code-session-id`.
3. Exit-2 stderr exposes the full hook command line to the model.
4. Plain 429 retries for ~3 minutes.
5. Keep redaction deterministic to preserve the prompt cache.
6. Metadata leaks (cwd, git user, CLAUDE.md, email, account IDs) travel in user-role text blocks and `metadata` → scrub in logs; great material for the data-minimization demo.
7. `cache_control` positions move every request → strip before hashing for any scan cache.
8. Haiku refuses "echo my card back" prompts → phrase the demo as a masking check.
9. Use `env -i` for nested runs (the desktop app leaks `CLAUDECODE` / `CLAUDE_CODE_*` into children).
10. `-p` without stdin waits 3 s → redirect `< /dev/null`.
11. Force `accept-encoding: identity` upstream.
12. Invalid tool input never reaches PreToolUse (Claude Code rejects it with `InputValidationError` first).

## Files in this folder
- `proxy.py` — spike proxy; runtime switches via `POST /_spike/config` (`redact`, `redact_nondeterministic`, budget modes, `hook_delay_s`).
- `hook.py` — fail-closed hook client.
- `settings/` — `spike.json` (working profile), `spike-preonly.json`, `spike-hookdown.json`, `spike-hookmissing.json`, `spike-hooktimeout.json`.
- `run.sh` — isolated non-interactive runner; `restart_proxy.sh` — starts the proxy on 127.0.0.1:18787.
- `project/` — throwaway cwd with a FAKE `.env`; `logs/`, `runs/` — scrubbed evidence (git-ignored).
