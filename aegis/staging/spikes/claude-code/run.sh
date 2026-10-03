#!/usr/bin/env bash
# Run Claude Code non-interactively against the spike proxy, isolated from user config.
#   run.sh <run-name> <settings-file> "<prompt>" [extra claude args...]
# Env: CLAUDE_BIN (default: claude on PATH), SPIKE_EXTRA_ENV="K=V K2=V2", RUN_TIMEOUT (s, default 120)
# Output: runs/<run-name>.jsonl (stream-json), runs/<run-name>.meta (exit code, wall time)
set -u
D="$(cd "$(dirname "$0")" && pwd)"
NAME="$1"; SETTINGS="$2"; PROMPT="$3"; shift 3
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
OUT="$D/runs/$NAME.jsonl"
curl -s -X POST localhost:18787/_spike/config -H 'content-type: application/json' \
  -d "{\"tag\":\"$NAME\"}" >/dev/null || true
START=$(python3 -c 'import time;print(time.time())')
cd "$D/project"
# env -i: drop everything inherited from the parent Claude session (CLAUDECODE, ANTHROPIC_BASE_URL, ...)
# shellcheck disable=SC2086
env -i HOME="$HOME" USER="$USER" LOGNAME="$USER" PATH="/Users/$USER/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  TMPDIR="$TMPDIR" SHELL=/bin/zsh LANG=en_US.UTF-8 ${SPIKE_EXTRA_ENV:-} \
  perl -e 'alarm shift; exec @ARGV' "${RUN_TIMEOUT:-120}" \
  "$CLAUDE_BIN" -p "$PROMPT" \
    --settings "$SETTINGS" \
    --setting-sources project \
    --strict-mcp-config \
    --no-session-persistence \
    --output-format stream-json --verbose \
    --model "${SPIKE_MODEL:-haiku}" \
    --max-turns "${SPIKE_MAX_TURNS:-4}" \
    "$@" < /dev/null > "$OUT" 2> "$D/runs/$NAME.stderr"
RC=$?
END=$(python3 -c 'import time;print(time.time())')
python3 - "$OUT" "$RC" "$START" "$END" > "$D/runs/$NAME.meta" <<'PY'
import json, sys
out, rc, s, e = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
res = None
for line in open(out):
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("type") == "result":
        res = d
print(json.dumps({"exit_code": rc, "wall_s": round(e - s, 1),
                  "result": {k: res.get(k) for k in ("subtype", "is_error", "result", "num_turns",
                                                      "total_cost_usd", "duration_api_ms", "api_error_status")} if res else None},
                 indent=1))
PY
cat "$D/runs/$NAME.meta"
