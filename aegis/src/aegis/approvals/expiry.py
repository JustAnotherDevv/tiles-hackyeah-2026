"""Background sweeper: expires pending requests on time (SSE + audit visible on stage) and keeps
the org cache fresh. Never started when AEGIS_TEST_MODE=1 (lazy expiry on every read still works).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)


async def sweeper_loop(service: Any) -> None:
    while True:
        try:
            interval = float(service.defaults().get("sweep_interval_s") or 1.0)
        except Exception:
            interval = 1.0
        await asyncio.sleep(max(0.2, interval))
        try:
            await service.sweep()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("approvals sweep failed", exc_info=True)


__all__ = ["sweeper_loop"]
