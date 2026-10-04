#!/usr/bin/env bash
# Streaming demo: fake Anthropic upstream -> aegis_stream (rehydrate + leak scan) -> curl.
# Starts two local servers (127.0.0.1), runs the scenarios, stops the servers on exit.
set -euo pipefail
cd "$(dirname "$0")/.."

export AEGIS_DEMO_UPSTREAM_PORT=${AEGIS_DEMO_UPSTREAM_PORT:-8798}
export AEGIS_DEMO_GATEWAY_PORT=${AEGIS_DEMO_GATEWAY_PORT:-8799}
UP=http://127.0.0.1:$AEGIS_DEMO_UPSTREAM_PORT
GW=http://127.0.0.1:$AEGIS_DEMO_GATEWAY_PORT
RUN=(uv run --quiet --python 3.13 --with fastapi --with uvicorn --with httpx)

"${RUN[@]}" python demo/fake_upstream.py & UP_PID=$!
"${RUN[@]}" python demo/gateway.py & GW_PID=$!
cleanup() { kill "$UP_PID" "$GW_PID" 2>/dev/null || true; wait "$UP_PID" "$GW_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

for url in "$UP" "$GW"; do
  for _ in $(seq 1 150); do curl -sf "$url/healthz" >/dev/null && break; sleep 0.2; done
done

say() { printf '\n\033[1;36m━━ %s ━━\033[0m\n' "$*"; sleep 0.3; }
REQ='{"model":"claude-sonnet-4-5","max_tokens":512,"stream":true,"messages":[{"role":"user","content":"Email Jan Kowalski (jan.kowalski@bank.pl, PESEL 44051401359) his statement."}]}'
post() { curl -sN "$1/v1/messages" -H 'content-type: application/json' -H "x-demo-scenario: $2" -d "$REQ"; }
pretty() { "${RUN[@]}" python demo/pretty.py; }

say "1a. Raw stream from the remote model (only placeholders ever left the machine)"
post "$UP" rehydrate | grep -E '^data: .*"(text_delta|input_json_delta)"' | cut -c1-140
say "1b. Same stream through aegis: raw SSE as the client receives it"
post "$GW" rehydrate | grep -E '^data: .*"(text_delta|input_json_delta|thinking_delta)"' | cut -c1-160
say "1c. Client view through aegis (thinking untouched, text + tool input rehydrated)"
post "$GW" rehydrate | pretty
say "2. Model leaks a cloud key mid-stream: blocked, stream closed cleanly (no client retry)"
post "$GW" leak | pretty
say "2b. ...the raw tail of that stream: valid closing events"
post "$GW" leak | tail -n 12
say "3. Markdown image exfiltration beacon: never rendered"
post "$GW" exfil | pretty
sleep 0.3
