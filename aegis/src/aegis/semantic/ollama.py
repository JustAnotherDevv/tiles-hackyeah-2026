"""Async Ollama client for the guard / judge (direct to AEGIS_OLLAMA_URL, never via /ollama).

Internal traffic: unbudgeted, unaudited, never logged with content. One ``httpx.AsyncClient``
(timeout=None, every call passes its own timeout) and one ``asyncio.Semaphore(1)`` per model:
acquiring waits at most ``queue_wait_s`` and then raises ``QueueTimeout`` (-> ``fallback:queue``).
We never restart or reconfigure the user's Ollama and never pull models.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import httpx


class QueueTimeout(Exception):
    """The per-model semaphore could not be acquired within ``queue_wait_s``."""


class OllamaError(Exception):
    """Non-2xx answer or malformed body from Ollama."""


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", *, transport: Any = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._sems: dict[str, asyncio.Semaphore] = {}
        self.waiting: dict[str, int] = {}

    # ------------------------------------------------------------ plumbing
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            kw: dict[str, Any] = {"base_url": self.base_url, "timeout": None}
            if self._transport is not None:
                kw["transport"] = self._transport
            self._client = httpx.AsyncClient(**kw)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    def _sem(self, model: str) -> asyncio.Semaphore:
        sem = self._sems.get(model)
        if sem is None:
            sem = self._sems[model] = asyncio.Semaphore(1)
        return sem

    @contextlib.asynccontextmanager
    async def slot(self, model: str, queue_wait_s: float | None) -> AsyncIterator[None]:
        sem = self._sem(model)
        self.waiting[model] = self.waiting.get(model, 0) + 1
        try:
            if queue_wait_s is None:
                await sem.acquire()
            else:
                try:
                    await asyncio.wait_for(sem.acquire(), timeout=max(0.001, queue_wait_s))
                except TimeoutError as exc:
                    raise QueueTimeout(model) from exc
        finally:
            self.waiting[model] -= 1
        try:
            yield
        finally:
            sem.release()

    async def _get(self, path: str, timeout_s: float) -> dict[str, Any]:
        r = await self.client.get(path, timeout=httpx.Timeout(timeout_s))
        if r.status_code >= 400:
            raise OllamaError(f"GET {path} -> {r.status_code}")
        return r.json()

    async def _post(self, path: str, body: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        r = await self.client.post(path, json=body, timeout=httpx.Timeout(timeout_s))
        if r.status_code >= 400:
            raise OllamaError(f"POST {path} -> {r.status_code}")
        try:
            return r.json()
        except ValueError as exc:
            raise OllamaError(f"POST {path}: invalid JSON") from exc

    # ------------------------------------------------------------ API
    async def version(self, timeout_s: float = 1.0) -> str | None:
        return (await self._get("/api/version", timeout_s)).get("version")

    async def tags(self, timeout_s: float = 2.0) -> list[str]:
        """Model names, e.g. ['aegis-guard:latest', ...]."""
        return [
            m.get("name", "") for m in (await self._get("/api/tags", timeout_s)).get("models", [])
        ]

    async def ps(self, timeout_s: float = 1.0) -> list[dict[str, Any]]:
        """Loaded models: [{name, size_mb, expires_at}]."""
        out = []
        for m in (await self._get("/api/ps", timeout_s)).get("models", []):
            out.append(
                {
                    "name": m.get("name") or m.get("model", ""),
                    "size_mb": round((m.get("size") or 0) / 1e6),
                    "expires_at": m.get("expires_at"),
                }
            )
        return out

    async def has_model(self, tag: str, timeout_s: float = 2.0) -> bool:
        names = await self.tags(timeout_s)
        return any(n == tag or n.split(":", 1)[0] == tag for n in names)

    async def generate_raw(
        self,
        body: dict[str, Any],
        *,
        timeout_s: float,
        queue_wait_s: float | None = None,
    ) -> dict[str, Any]:
        """POST /api/generate with a prepared (raw-mode) payload under the model's semaphore."""
        async with self.slot(str(body.get("model", "")), queue_wait_s):
            return await self._post("/api/generate", body, timeout_s)

    async def chat(
        self,
        body: dict[str, Any],
        *,
        timeout_s: float,
        queue_wait_s: float | None = None,
    ) -> dict[str, Any]:
        async with self.slot(str(body.get("model", "")), queue_wait_s):
            return await self._post("/api/chat", body, timeout_s)

    async def warm(self, model: str, keep_alive: str = "30m", timeout_s: float = 30.0) -> float:
        """Load / keep a model resident; returns Ollama's load_duration in ms."""
        resp = await self._post(
            "/api/generate", {"model": model, "prompt": "", "keep_alive": keep_alive}, timeout_s
        )
        return float(resp.get("load_duration") or 0) / 1e6

    async def unload(self, model: str, timeout_s: float = 5.0) -> None:
        await self._post(
            "/api/generate", {"model": model, "prompt": "", "keep_alive": 0}, timeout_s
        )


__all__ = ["OllamaClient", "OllamaError", "QueueTimeout"]
