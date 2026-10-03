"""Hot reload: watch config/policy.yaml + config/profiles/*.yaml and apply on save (< 1 s).

Directory watch (handles editors' rename-saves), 200 ms debounce, own API writes ignored by
sha256, empty/partial reads retried once after 100 ms. Off when AEGIS_TEST_MODE=1 (the route's
on_startup does not start it); `POST /api/policy/reload` is the manual fallback.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class PolicyWatcher:
    def __init__(self, store: Any):
        self.store = store
        self._task: asyncio.Task[Any] | None = None
        self._stop: asyncio.Event | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _paths(self) -> tuple[Path, Path]:
        policy = Path(self.store.policy_path).resolve()
        profiles_dir = policy.parent / "profiles"
        return policy, profiles_dir

    def start(self) -> None:
        if self.running:
            return
        self._stop = asyncio.Event()
        self._task = asyncio.get_running_loop().create_task(self._run(), name="aegis-policy-watcher")

    async def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._task = None

    async def _run(self) -> None:
        try:
            from watchfiles import awatch
        except Exception:  # pragma: no cover
            log.warning("watchfiles unavailable - policy hot reload disabled (use POST /api/policy/reload)")
            return
        while self._stop is not None and not self._stop.is_set():
            policy, profiles_dir = self._paths()
            dirs = [str(policy.parent)]
            policy_name = policy.name

            def keep(_change: Any, path: str) -> bool:
                p = Path(path)
                if p.name == policy_name and p.parent == policy.parent:
                    return True
                return p.suffix == ".yaml" and p.parent == profiles_dir

            try:
                log.info("policy watcher started path=%s", policy)
                async for changes in awatch(*dirs, watch_filter=keep, debounce=200, step=50,
                                            stop_event=self._stop, recursive=True):
                    files = {Path(p) for _c, p in changes}
                    profile_changed = [f for f in files if f.parent == profiles_dir]
                    policy_changed = any(f.name == policy_name for f in files)
                    await self._handle(policy, policy_changed, profile_changed)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("policy watcher crashed - restarting in 1 s")
                await asyncio.sleep(1.0)

    async def _read(self, path: Path) -> str | None:
        for attempt in range(2):
            try:
                text = await asyncio.to_thread(path.read_text, encoding="utf-8")
                if text.strip():
                    return text
            except OSError:
                pass
            if attempt == 0:
                await asyncio.sleep(0.1)
        return None

    async def _handle(self, policy: Path, policy_changed: bool, profile_changed: list[Path]) -> None:
        text = await self._read(policy)
        if text is None:
            if policy_changed:
                log.warning("policy file empty or unreadable after change - keeping current version")
                from aegis.core.policy_schema import ValidationIssue

                await self.store.publish_rejected(
                    "file", [ValidationIssue(message=f"{policy.name} is empty or unreadable")], None)
            return
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cur = self.store.snapshot()
        if self.store.is_own_write(sha) and sha == cur.sha256:
            return
        if sha == cur.sha256 and not profile_changed:
            return
        reason = None
        if profile_changed and not policy_changed:
            reason = "profile " + ", ".join(sorted(p.name for p in profile_changed)) + " changed"
        res = await self.store.apply_yaml(text, actor=None, source="file", reason=reason)
        log.info("policy file change handled status=%s version=%s", res.status, res.version)
