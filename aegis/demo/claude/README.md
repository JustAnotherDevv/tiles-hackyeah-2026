# Claude Code × Aegis (flow F3)

A **real, unmodified Claude Code** session governed by Aegis on three layers, one pipeline:

| Layer | How | What Aegis does |
|---|---|---|
| Model traffic | `ANTHROPIC_BASE_URL=http://127.0.0.1:8787` (OAuth passes through; agent key in `X-Aegis-Agent-Key` via `ANTHROPIC_CUSTOM_HEADERS`) | redaction, budgets, model allowlist, injection in tool results; keyed on `x-claude-code-session-id` |
| Every tool call | `PreToolUse` / `PostToolUse` / `UserPromptSubmit` / `ConfigChange` command hooks → `scripts/aegis-hook` (bash + curl) → `POST /v1/hooks/claude-code` | allow / **deny with reason** / approval hold / `updatedInput` (local rehydration) / `updatedToolOutput` (neutralised output) |
| MCP | `mcp.json` routes all 9 demo servers via `http://127.0.0.1:8787/mcp/<name>`, `--strict-mcp-config` | tool pinning, spend/data approvals, poisoned-tool removal |

The hook `session_id` equals `x-claude-code-session-id`, so vault placeholders, budgets and loop
windows are shared between the model hop and the hook hop.

## Run it

```sh
make up                              # gateway + feed + mocks (or: make gateway)
demo/claude/check.sh                 # preflight: claude version, /healthz, hook round trip, guards, profile
demo/claude/run.sh                   # interactive Claude Code in demo/claude/project (= make claude)
demo/claude/demo.sh pipe-to-shell    # scripted live scene with `claude -p` (haiku, a few cents)
python3 demo/claude/replay.py all    # deterministic replay, no model, same live-feed rows
```

Prompts to paste: [`PROMPTS.md`](PROMPTS.md). Scenes for `demo.sh`: `pipe-to-shell`, `dotenv`,
`injection`, `gpu-480`, `failclosed`, `rehydrate`. `reset.sh` regenerates the fake `.env` and the
invisible Unicode-tag-character injection in `project/docs/SETUP.md` at runtime (`reset.sh --clean`
removes them again before a commit - they are never committed).

## Fail-closed by construction

- Gateway down / slow / 5xx / garbage → `scripts/aegis-hook` exits **2** for `PreToolUse`,
  `UserPromptSubmit`, `ConfigChange` (the action is blocked, the reason is shown to Claude);
  `PermissionRequest` gets a deny JSON; `SessionStart` shows "AEGIS GATEWAY UNREACHABLE".
- Missing or crashing hook script → the generated command is `… || exit 2` (a bare exit 127 would
  fail open).
- Timeout ordering, asserted by the generator and tests: settings `timeout` 120 s > curl
  `--max-time` 110 s > approval hold `hold_s.hook` 60 s (else Claude Code times out and fails open).
- Gateway-side errors → `[Aegis] FAIL-CLOSED: …` deny (`internal_error: deny`).
- The model cannot edit its own guardrails: **GOV-06** "Agent harness integrity" blocks writes to
  `demo/claude/settings*.json`, `mcp.json`, `.agent_key`, `.claude/settings*.json`,
  `scripts/aegis-hook` and blocks `ConfigChange` events that drop hooks or move
  `ANTHROPIC_BASE_URL`; EXE-02 `fs_deny` covers the same paths for reads/shell.
- `AEGIS_PROFILE=failclosed demo/claude/run.sh` (or `demo.sh failclosed`) points the hooks at a dead
  port while model traffic still flows, so Claude explains the denial live.

## What Claude Code shows

| Situation | Hook path (tool call / prompt) | Model path (`/v1/messages`) |
|---|---|---|
| Policy block | `[Aegis] EXE-01: Blocked by …` tool error, not retried | synthetic 200 assistant reply `[Aegis] Blocked by …` |
| Approval pending | held ≤ 60 s, then `[Aegis] ACT-01: Approval apr_… pending (needs owner: u_katarzyna) — approve at …/ui/governance/approvals?id=apr_…, then retry` (never `ask`) | synthetic 200 with link |
| Budget exhausted | prompt blocked up front: `[Aegis] GOV-06: Budget exhausted for agent:claude-code@platform …` | **402** + `x-should-retry: false` → one attempt, `API Error: 402 …`, exit 1 |
| Kill switch | `[Aegis] EXE-04: Kill switch active for …` | **429** `killed` + `retry-after: 3600`, `x-should-retry: false` (never 403: Claude shows "Failed to authenticate") |
| Loop / rate limit | `[Aegis] EXE-04: Loop/rate limit: …` | 429 + `retry-after` (plain 429 would retry 11× over ~3 min) |

Hook responses carry `X-Aegis-Decision-Id`; every hook decision lands in the Live Feed with
source `hook` and agent `claude-code@platform`.

## Profile (never machine-wide)

`uv run --frozen python -m aegis.integrations.claude_code.profile [--gateway-url URL] [--check]`
writes `settings.json` (demo), `settings.failclosed.json`, `settings.hardened.json`, `mcp.json`,
`.agent_key` (seed demo key, mode 600) - only under `demo/claude/`. The three `settings*.json` files contain
absolute paths of your checkout, so they are **generated, not committed** (gitignored); `run.sh` and
`demo.sh` regenerate them on every launch
(`uv run --frozen python -m aegis.integrations.claude_code.profile --if-stale`). `settings.example.json` shows
the shape with an `${AEGIS_ROOT}` placeholder for reference only. It refuses `~/.claude`,
`.claude/` dirs and managed-settings paths. `run.sh` launches
`claude --settings demo/claude/settings.json --setting-sources project --mcp-config demo/claude/mcp.json --strict-mcp-config`,
so user-level hooks/MCP servers cannot bypass or interfere. The production equivalent (managed
settings with `allowManagedHooksOnly`) is printed as text only: `… profile --print-managed`.

## `claude update` note

The demo Mac has Claude Code **2.1.271** on PATH (desktop app bundles 2.1.286). Missing below
2.1.286: gateway hint headers (2.1.273), `mcp_server` in hook input (2.1.274),
`x-claude-code-prompt-id` (2.1.283). The integration degrades gracefully (session id keying, MCP
server from the tool name), but **a human** should run `claude update` before the event and then
re-run `demo.sh pipe-to-shell` + `replay.py all`. Agents must not run `claude update`.

## Troubleshooting

- Every tool call denied "gateway unreachable" → `make up`; `check.sh`.
- Hooks seem ignored → you launched plain `claude`; use `run.sh` (needs `--settings`).
- Nested inside another Claude Code session → `demo.sh` uses `env -i`; `run.sh` unsets
  `CLAUDECODE`/`ANTHROPIC_BASE_URL`.
- Approval hold feels like a hang → the dashboard toast appears immediately; lower
  `approvals.defaults.hold_s.hook` live (0 = immediate deny with link).
- Network / Anthropic flaky → `python3 demo/claude/replay.py <scene>`.
