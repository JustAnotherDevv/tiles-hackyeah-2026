#!/usr/bin/env bash
# (re)start the spike proxy on 127.0.0.1:18787 in the background
D="$(cd "$(dirname "$0")" && pwd)"
pkill -f "proxy.py --port 18787" 2>/dev/null; sleep 1
cd "$D" && nohup uv run --python 3.13 --with fastapi --with uvicorn --with httpx \
  python proxy.py --port 18787 >> logs/proxy.stdout 2>&1 &
for i in $(seq 1 20); do curl -sf localhost:18787/_spike/config >/dev/null && { echo "proxy up"; exit 0; }; sleep 0.5; done
echo "proxy failed to start"; exit 1
