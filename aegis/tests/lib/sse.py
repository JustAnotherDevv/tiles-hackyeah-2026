"""Bounded SSE reader for `GET /api/events?replay=N` (never blocks longer than `max_s`)."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx


def read_events(
    gw: Any,
    names: list[str] | None = None,
    replay: int = 200,
    max_s: float = 2.0,
    view_as: str = "u_katarzyna",
) -> list[tuple[str, Any]]:
    params: dict[str, Any] = {"replay": replay, "view_as": view_as}
    if names:
        params["events"] = ",".join(names)
    out: list[tuple[str, Any]] = []
    deadline = time.monotonic() + max_s
    timeout = httpx.Timeout(max_s, read=max(0.2, max_s / 2))
    try:
        with gw.http.stream("GET", "/api/events", params=params, timeout=timeout) as r:
            if r.status_code != 200:
                return out
            event, data = "message", []
            for line in r.iter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].strip())
                elif line == "":
                    if data:
                        raw = "\n".join(data)
                        try:
                            payload: Any = json.loads(raw)
                        except ValueError:
                            payload = raw
                        if not names or event in names:
                            out.append((event, payload))
                    event, data = "message", []
                if time.monotonic() > deadline:
                    break
    except (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ReadError):
        pass
    return out


__all__ = ["read_events"]
