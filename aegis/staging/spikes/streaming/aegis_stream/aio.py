"""Async adapter: drive a sans-IO transformer from an async byte iterator.

Designed for ``StreamingResponse(stream_transform(resp.aiter_bytes(), tr, ...))``
in FastAPI/Starlette with an ``httpx`` streaming upstream response.

* keep-alives while the upstream is silent (Claude Code aborts after 5 min of
  no bytes; we hold back a few chars at most, but slow upstreams exist),
* external abort (kill switch / budget) via :class:`StreamController`,
* upstream is closed as soon as the client-facing stream is finished (stop
  paying for tokens nobody reads) or the client disconnects,
* ``on_complete(report)`` always runs (settle the budget ledger, write audit).
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from typing import Any

from .base import StreamReport, StreamTransformer

__all__ = ["StreamController", "stream_transform"]

log = logging.getLogger("aegis.stream")


class StreamController:
    """Handle the gateway keeps per active stream (e.g. for the kill switch)."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self.reason: str | None = None
        self.control: str = "KILL-SWITCH"

    def abort(self, reason: str, control: str = "KILL-SWITCH") -> None:
        self.reason, self.control = reason, control
        self._event.set()

    @property
    def aborted(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


async def stream_transform(
    upstream: AsyncIterable[bytes],
    transformer: StreamTransformer,
    *,
    keepalive_interval: float | None = 15.0,
    controller: StreamController | None = None,
    on_complete: Callable[[StreamReport], Any] | None = None,
    aclose: Callable[[], Awaitable[Any]] | None = None,
) -> AsyncIterator[bytes]:
    it = upstream.__aiter__()
    pending: asyncio.Task | None = None
    abort_wait: asyncio.Task | None = None
    completed = False
    try:
        while not transformer.finished:
            if controller is not None and controller.aborted:
                out = transformer.abort(controller.reason or "aborted", controller.control)
                if out:
                    yield out
                break
            if pending is None:
                pending = asyncio.ensure_future(it.__anext__())
            waiters: set[asyncio.Future] = {pending}
            if controller is not None:
                if abort_wait is None:
                    abort_wait = asyncio.ensure_future(controller.wait())
                waiters.add(abort_wait)
            done, _ = await asyncio.wait(waiters, timeout=keepalive_interval,
                                         return_when=asyncio.FIRST_COMPLETED)
            if not done:
                ka = transformer.keepalive()
                if ka:
                    yield ka
                continue
            if pending not in done:
                continue  # controller fired: handled at the top of the loop
            task, pending = pending, None
            try:
                chunk = task.result()
            except StopAsyncIteration:
                out = transformer.close()
                if out:
                    yield out
                break
            except Exception as exc:  # upstream network error mid-stream
                log.warning("upstream read failed: %r", exc)
                transformer.report.upstream_error = transformer.report.upstream_error or repr(exc)
                out = transformer.close()
                if out:
                    yield out
                break
            out = transformer.feed(chunk)
            if out:
                yield out
        completed = True
    finally:
        if not completed and not transformer.finished:
            transformer.report.client_disconnected = True
        for t in (pending, abort_wait):
            if t is not None and not t.done():
                t.cancel()
                with contextlib.suppress(BaseException):
                    await t
        with contextlib.suppress(Exception):
            if aclose is not None:
                await aclose()
            else:
                closer = getattr(upstream, "aclose", None)
                if closer is not None:
                    await closer()
        if on_complete is not None:
            try:
                r = on_complete(transformer.report)
                if inspect.isawaitable(r):
                    await r
            except Exception:
                log.exception("on_complete callback failed")
