"""Gateway FeedManager (factory `aegis.feed.manager:create`; implements protocols.FeedManager).

Pulls the signed threat-intel feed (SSE push + poll), verifies it against the pinned Ed25519
key, enforces anti-rollback, self-tests every signature (failures are quarantined), swaps the
compiled snapshot atomically and keeps the last-known-good on any failure. Emits `feed.updated`
/ `feed.rejected` (SSE + audit), `aegis_feed_serial` / `aegis_feed_reloads_total` metrics.

`FeedStatus.last_error` and `feed.rejected.reason` start with a machine token (Addendum A-49):
`bad_signature`, `sha256_mismatch`, `rollback`, `schema`, `expired`, `unreachable`, `wrong_key`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import Counter, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aegis.core.types import AuditEvent, FeedStatus, Identity, new_id, utcnow
from aegis.feed.compile import CompiledFeed, compile_bundle, diff
from aegis.feed.matchers import event_from_interaction
from aegis.feed.schema import FeedPointer
from aegis.feed.verify import FeedRejected, key_id, load_pubkey, sha256_hex, verify_detached

log = logging.getLogger(__name__)

MAX_POINTER_BYTES = 64 * 1024
MAX_BUNDLE_BYTES = 5 * 1024 * 1024
KEEP_CACHE = 5
HISTORY_MAX = 20
HIT_WINDOW_S = 24 * 3600
SSE_BACKOFF = (1.0, 2.0, 5.0, 10.0)
FEED_ID = "aegis-threat-intel"

DDL = """
CREATE TABLE IF NOT EXISTS feed_state (feed_id TEXT PRIMARY KEY, serial INTEGER, version TEXT,
  sha256 TEXT, applied_at TEXT, status TEXT, last_error TEXT, history_json TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS signature_hits (ts TEXT NOT NULL, signature_id TEXT NOT NULL,
  surface TEXT, action TEXT, decision_id TEXT);
"""


def _iso(d: datetime | None) -> str | None:
    return d.astimezone(UTC).isoformat().replace("+00:00", "Z") if d else None


class FeedManager:
    """Threat-feed state for the gateway. All public methods are safe to call any time."""

    def __init__(self, rt: Any = None, *, transport: Any = None, settings: Any = None) -> None:
        self.rt = rt
        self._settings = settings
        self._transport = transport
        self.active: CompiledFeed | None = None
        self.previous: CompiledFeed | None = None
        self.pinned = False
        self._status = "disabled"
        self._last_error: str | None = None
        self._last_check: datetime | None = None
        self._last_update: datetime | None = None
        self._history: list[dict] = []
        self._high_water = 0
        self._pub: bytes | None = None
        self._pub_text: str | None = None
        self._reported: set[tuple[str, str]] = set()
        self._lock: asyncio.Lock | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._stopping = False
        self._hits: deque[tuple[float, str]] = deque()
        self._hit_counts: Counter[str] = Counter()
        self._pending_rows: list[tuple[str, str, str | None, str | None]] = []
        self._db_ok = False
        self._wake = None  # asyncio.Event set by SSE pushes
        self.pending_serial: int | None = None
        self._started = False
        self._bg: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------ config
    @property
    def settings(self) -> Any:
        if self._settings is None:
            s = getattr(self.rt, "settings", None)
            if s is None:
                from aegis.settings import get_settings

                s = get_settings()
            self._settings = s
        return self._settings

    def _source(self) -> Any:
        from aegis.core.policy_schema import FeedSource

        try:
            snap = self.rt.policy.snapshot()
            sources = snap.doc.feeds.sources
            if sources:
                return sources[0]
        except Exception:
            pass
        return FeedSource()

    def _root(self) -> Path:
        try:
            from aegis.settings import ROOT

            return Path(ROOT)
        except Exception:
            return Path.cwd()

    @property
    def url(self) -> str | None:
        raw = str(getattr(self.settings, "feed_url", "") or "").strip()
        if raw.lower() in ("", "disabled", "off", "none"):
            return None
        src = self._source()
        if raw == "http://127.0.0.1:8790" and getattr(src, "url", None):
            raw = str(src.url)
        return raw.rstrip("/")

    def _pubkey_path(self) -> Path:
        p = Path(getattr(self.settings, "feed_pubkey", "config/feeds/feed_pubkey.b64"))
        return p if p.is_absolute() else self._root() / p

    def _seed_path(self) -> Path | None:
        """The committed seed bundle lives next to the pinned key (config/feeds/)."""
        alt = self._pubkey_path().parent / "seed_bundle.json"
        if alt.exists():
            return alt
        seed = getattr(self._source(), "seed_bundle", None)
        if not seed:
            return None
        p = Path(seed)
        return p if p.is_absolute() else self._root() / p

    def _cache_dir(self) -> Path:
        return Path(getattr(self.settings, "data_dir", "data")) / "feed"

    def _test_mode(self) -> bool:
        return bool(getattr(self.settings, "test_mode", False))

    def _source_id(self) -> str:
        return str(getattr(self._source(), "id", FEED_ID) or FEED_ID)

    # ------------------------------------------------------------------ protocol
    @property
    def serial(self) -> int | None:
        a = self.active
        return a.serial if a is not None and a.serial > 0 else None

    def status(self) -> FeedStatus:
        a = self.active
        st = self._status
        if (
            a is not None
            and a.expires is not None
            and a.expires < utcnow()
            and st in ("ok", "seed")
        ):
            st = "stale"
        monitor = 0
        active = 0
        overrides = self._overrides()
        if a is not None:
            for sid in a.active_ids():
                ov = overrides.get(sid)
                if ov is not None and (ov.enabled is False or ov.mode == "off"):
                    continue
                mode = (
                    "monitor"
                    if (a.sigs[sid].mode == "monitor" or (ov is not None and ov.mode == "monitor"))
                    else "enforce"
                )
                if mode == "monitor":
                    monitor += 1
                else:
                    active += 1
        return FeedStatus(
            feed_id=self._source_id(),
            url=self.url,
            status=st,  # type: ignore[arg-type]
            serial=self.serial,
            version=a.version if a and a.serial else None,
            published=a.published if a else None,
            expires=a.expires if a else None,
            key_id=(a.key_id if a and a.key_id else (key_id(self._pub) if self._pub else None)),
            signatures_total=len(a.sigs) if a else 0,
            signatures_active=active,
            signatures_monitor=monitor,
            signatures_quarantined=len(a.quarantined) if a else 0,
            last_check=self._last_check,
            last_update=self._last_update,
            last_error=self._last_error,
            history=list(self._history),
        )

    async def refresh(self, trigger: str = "api") -> FeedStatus:
        """Pull + verify + activate. Never raises. `trigger="api"` clears an operator pin."""
        if trigger == "api":
            self.pinned = False
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            try:
                await self._refresh_locked(trigger)
            except Exception as e:  # last line of defence: never raise to callers
                log.exception("feed refresh failed trigger=%s", trigger)
                self._last_error = f"unreachable: {type(e).__name__}"
        return self.status()

    def signatures(self) -> list[dict[str, Any]]:
        a = self.active
        if a is None:
            return []
        self._expire_hits()
        overrides = self._overrides()
        out = []
        for sid, c in sorted(a.sigs.items()):
            s = c.sig
            ov = overrides.get(sid)
            status = "quarantined" if sid in a.quarantined else str(s.get("status", "stable"))
            mode = c.mode
            action = str(s.get("action", "block"))
            if ov is not None:
                if ov.enabled is False or ov.mode == "off":
                    mode = "off"
                elif ov.mode == "monitor":
                    mode = "monitor"
                if ov.action:
                    action = str(ov.action)
            aliases = list(s.get("aliases") or [])
            out.append(
                {
                    "id": sid,
                    "title": s.get("title", sid),
                    "severity": s.get("severity", "medium"),
                    "status": status,
                    "aliases": aliases,
                    "tags": list(s.get("tags") or []),
                    "surfaces": sorted(c.surfaces),
                    "action": action,
                    "hits_24h": int(self._hit_counts.get(sid, 0)),
                    "message": s.get("message"),
                    "references": list(s.get("references") or []),
                    "quarantine_reason": a.quarantined.get(sid),
                    "mode": mode,
                    "cves": [x for x in aliases if str(x).startswith("CVE-")],
                    "action_overrides": dict(s.get("action_overrides") or {}),
                    "override": ov.model_dump(exclude_none=True) if ov is not None else None,
                }
            )
        return out

    # ------------------------------------------------------------------ extras
    def lists(self) -> dict[str, Any]:
        a = self.active
        return dict(a.lists) if a is not None else {}

    def signature_detail(self, sid: str) -> dict[str, Any] | None:
        a = self.active
        if a is None or sid not in a.sigs:
            return None
        view = next((v for v in self.signatures() if v["id"] == sid), {})
        return {
            **view,
            "signature": a.sigs[sid].sig,
            "sha256": a.sig_sha.get(sid),
            "selftest": a.selftest.get(sid),
            "feed_serial": a.serial,
        }

    def snapshot_for(self, ctx: Any = None) -> CompiledFeed | None:
        """Pin the feed snapshot to the request (one request never sees two feed versions)."""
        a, p = self.active, self.previous
        want = getattr(ctx, "feed_serial", None) if ctx is not None else None
        if want is not None and p is not None and a is not None and want == p.serial != a.serial:
            return p
        return a

    def scan(
        self,
        interaction: Any,
        *,
        ctx: Any = None,
        segments: Any = None,
        snapshot: CompiledFeed | None = None,
        artifact_roots: Any = None,
    ) -> list[dict]:
        """Evaluate the active signatures for this interaction's surface; per-signature errors
        are isolated (logged, `degraded` hit) and never raised."""
        snap = snapshot or self.snapshot_for(ctx)
        if snap is None:
            return []
        surface = str(getattr(interaction, "surface", "") or "")
        sigs = snap.by_surface.get(surface) or ()
        if not sigs:
            return []
        ev = event_from_interaction(
            interaction, segments=segments, artifact_roots=artifact_roots, base_dir=self._root()
        )
        hits: list[dict] = []
        for c in sigs:
            try:
                h = c.evaluate(ev)
            except Exception as e:
                log.warning("signature evaluation failed id=%s error=%s", c.id, type(e).__name__)
                hits.append({"signature_id": c.id, "degraded": True, "error": type(e).__name__})
                continue
            if h is not None:
                hits.append(h)
        return hits

    def record_hits(
        self, hits: list[dict], *, surface: str, decision_id: str | None = None
    ) -> None:
        """24 h counters + batched `signature_hits` rows + `aegis_signature_hits_total`."""
        now = time.time()
        ts = _iso(datetime.now(UTC))
        for h in hits:
            sid = h.get("signature_id")
            if not sid or h.get("degraded"):
                continue
            self._hits.append((now, sid))
            self._hit_counts[sid] += 1
            self._pending_rows.append((ts or "", sid, surface, h.get("action")))
            self._metric_inc("aegis_signature_hits_total", {"signature_id": sid})
        self._expire_hits()
        if self._pending_rows and self._db_ok:
            rows, self._pending_rows = self._pending_rows, []
            try:
                loop = asyncio.get_running_loop()
                t = loop.create_task(asyncio.to_thread(self._insert_hits, rows, decision_id))
                self._bg.add(t)
                t.add_done_callback(self._bg.discard)
            except RuntimeError:
                self._insert_hits(rows, decision_id)

    def _insert_hits(
        self, rows: list[tuple[str, str, str | None, str | None]], decision_id: str | None
    ) -> None:
        try:
            con = self.rt.db()
            try:
                con.executemany(
                    "INSERT INTO signature_hits (ts, signature_id, surface, action, decision_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [(*r, decision_id) for r in rows],
                )
                con.commit()
            finally:
                con.close()
        except Exception:
            log.debug("signature_hits insert failed", exc_info=True)

    def _expire_hits(self) -> None:
        cutoff = time.time() - HIT_WINDOW_S
        while self._hits and self._hits[0][0] < cutoff:
            _, sid = self._hits.popleft()
            self._hit_counts[sid] -= 1
            if self._hit_counts[sid] <= 0:
                del self._hit_counts[sid]

    def _overrides(self) -> dict[str, Any]:
        try:
            return dict(self.rt.policy.snapshot().doc.feeds.overrides or {})
        except Exception:
            return {}

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        await asyncio.to_thread(self._init_db)
        self._load_pubkey()
        if self._pub is None:
            self._status = "disabled"
            self._last_error = f"wrong_key: no pinned public key at {self._pubkey_path()}"
            log.warning("feed disabled: pinned public key missing path=%s", self._pubkey_path())
        else:
            await asyncio.to_thread(self._activate_local)
        if self.active is not None and self.active.serial:
            self._metric_gauge("aegis_feed_serial", self.active.serial)
        if not self._test_mode() and self.url and self._pub is not None:
            self._tasks.append(asyncio.create_task(self._loop(), name="feed-loop"))
        log.info(
            "feed manager started status=%s serial=%s url=%s",
            self._status,
            self.serial,
            self.url or "disabled",
        )

    async def stop(self) -> None:
        self._stopping = True
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks.clear()

    def _init_db(self) -> None:
        rt = self.rt
        if rt is None or not hasattr(rt, "db"):
            return
        try:
            con = rt.db()
            try:
                con.executescript(DDL)
                row = con.execute(
                    "SELECT serial, history_json FROM feed_state WHERE feed_id = ?",
                    (self._source_id(),),
                ).fetchone()
                if row is not None:
                    self._high_water = max(self._high_water, int(row[0] or 0))
                    try:
                        self._history = list(json.loads(row[1] or "[]"))[-HISTORY_MAX:]
                    except ValueError:
                        self._history = []
                cutoff = _iso(datetime.now(UTC) - timedelta(seconds=HIT_WINDOW_S))
                now = time.time()
                for sid, n in con.execute(
                    "SELECT signature_id, COUNT(*) FROM signature_hits WHERE ts >= ? GROUP BY signature_id",
                    (cutoff,),
                ).fetchall():
                    self._hit_counts[sid] += int(n)
                    for _ in range(min(int(n), 10_000)):
                        self._hits.append((now, sid))
                con.commit()
            finally:
                con.close()
            self._db_ok = True
        except Exception:
            log.warning("feed tables unavailable (hits/high-water in memory only)", exc_info=True)

    def _load_pubkey(self) -> bool:
        """(Re)load the pinned key; True when it changed."""
        p = self._pubkey_path()
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            self._pub = None
            return False
        if text == self._pub_text and self._pub is not None:
            return False
        try:
            self._pub = load_pubkey(p)
        except ValueError:
            log.error("pinned feed public key is invalid path=%s", p)
            self._pub = None
            return False
        changed = self._pub_text is not None
        self._pub_text = text
        return changed

    def _activate_local(self) -> None:
        """(a) highest verified cached bundle, (b) the committed seed bundle, (c) nothing."""
        cache = self._cache_dir()
        candidates = sorted(cache.glob("bundle-*.json"), reverse=True) if cache.exists() else []
        for p in candidates:
            try:
                feed = self._load_verified_file(p, source="cache")
            except (FeedRejected, OSError, ValueError) as e:
                log.warning("cached feed bundle ignored path=%s reason=%s", p.name, e)
                continue
            self.active = feed
            self._status = "ok"
            self._high_water = max(self._high_water, feed.serial)
            self._last_update = utcnow()
            return
        seed = self._seed_path()
        if seed is not None and seed.exists():
            try:
                feed = self._load_verified_file(seed, source="seed")
                self.active = feed
                self._status = "seed"
                self._last_update = utcnow()
                if not self._history:
                    self._history.append(
                        self._history_item(
                            feed,
                            {"added": sorted(feed.sigs), "removed": [], "modified": []},
                            verify_ms=0.0,
                        )
                    )
                return
            except (FeedRejected, OSError, ValueError) as e:
                self._last_error = getattr(e, "reason", None) or f"bad_signature: seed bundle: {e}"
                log.error("seed feed bundle rejected reason=%s", self._last_error)
        self._status = "disabled" if not self.url else self._status
        log.warning("no verified feed bundle available; SIG-01 has 0 signatures")

    def _load_verified_file(self, path: Path, *, source: str) -> CompiledFeed:
        data = path.read_bytes()
        sig = Path(str(path) + ".sig").read_text(encoding="utf-8")
        if self._pub is None:
            raise FeedRejected("wrong_key: no pinned key")
        verify_detached(data, sig, self._pub, what=path.name)
        doc = json.loads(data)
        hdr_kid = (doc.get("feed") or {}).get("key_id")
        if hdr_kid and hdr_kid != key_id(self._pub):
            raise FeedRejected(
                f"wrong_key: {path.name} key_id {hdr_kid} != pinned {key_id(self._pub)}"
            )
        return compile_bundle(doc, sha256=sha256_hex(data), source=source)

    # ------------------------------------------------------------------ network loop
    async def _loop(self) -> None:
        await self.refresh("startup")
        tasks = [asyncio.create_task(self._poll_loop(), name="feed-poll")]
        if getattr(self._source(), "sse", True):
            tasks.append(asyncio.create_task(self._sse_loop(), name="feed-sse"))
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()

    async def _poll_loop(self) -> None:
        while not self._stopping:
            src = self._source()
            if not getattr(src, "enabled", True):
                await asyncio.sleep(5)
                continue
            await asyncio.sleep(max(1.0, float(getattr(src, "poll_s", 10.0) or 10.0)))
            await self.refresh("poll")

    def _client(self, timeout: float) -> Any:
        import httpx

        kw: dict[str, Any] = {"timeout": timeout}
        if self._transport is not None:
            kw["transport"] = self._transport
        return httpx.AsyncClient(**kw)

    async def _sse_loop(self) -> None:
        import httpx

        attempt = 0
        while not self._stopping:
            url = self.url
            if not url:
                await asyncio.sleep(5)
                continue
            try:
                async with self._client(timeout=None) as client:  # type: ignore[arg-type]
                    async with client.stream(
                        "GET", f"{url}/feed/events", headers={"accept": "text/event-stream"}
                    ) as resp:
                        if resp.status_code != 200:
                            raise httpx.HTTPError(f"HTTP {resp.status_code}")
                        attempt = 0
                        event = None
                        async for line in resp.aiter_lines():
                            if line.startswith("event:"):
                                event = line[6:].strip()
                            elif line == "":
                                event = None
                            elif line.startswith("data:") and event == "published":
                                log.info("feed sse published %s", line[5:].strip()[:80])
                                await self.refresh("sse")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug("feed sse disconnected error=%s", e)
            delay = SSE_BACKOFF[min(attempt, len(SSE_BACKOFF) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    # ------------------------------------------------------------------ refresh
    async def _fetch(self, client: Any, url: str, cap: int) -> bytes:
        async with client.stream("GET", url) as r:
            if r.status_code != 200:
                raise FeedRejected(
                    f"unreachable: GET {url.rsplit('/', 1)[-1]} -> HTTP {r.status_code}"
                )
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > cap:
                    raise FeedRejected(f"schema: {url.rsplit('/', 1)[-1]} larger than {cap} bytes")
            return bytes(buf)

    async def _pull_pointer(self, client: Any, url: str) -> tuple[bytes, str, FeedPointer, str]:
        """GET + verify latest.json. Returns (bytes, sig, pointer, sha256 of pointer bytes)."""
        ptr_bytes = await self._fetch(client, f"{url}/feed/latest.json", MAX_POINTER_BYTES)
        ptr_sig = (await self._fetch(client, f"{url}/feed/latest.json.sig", 4096)).decode(
            "ascii", "replace"
        )
        ptr_sha = sha256_hex(ptr_bytes)
        if self._status == "unreachable":
            self._status = "seed" if (self.active and self.active.source == "seed") else "ok"
            self._last_error = None
            self._system("info", f"threat feed reachable again at {url}")
        try:
            ptr_raw = json.loads(ptr_bytes)
        except ValueError:
            raise FeedRejected("schema: latest.json is not JSON") from None
        if not isinstance(ptr_raw, dict):
            raise FeedRejected("schema: latest.json is not an object")
        assert self._pub is not None
        pinned = key_id(self._pub)
        kid = ptr_raw.get("key_id")
        serial_hint = ptr_raw.get("serial") if isinstance(ptr_raw.get("serial"), int) else None
        if kid and kid != pinned and self._load_pubkey():
            log.warning(
                "pinned feed key changed on disk; reloaded old=%s new=%s", pinned, key_id(self._pub)
            )
            pinned = key_id(self._pub)
            self._system("warning", f"threat feed public key reloaded from disk (key {pinned})")
        if kid and kid != pinned:
            raise FeedRejected(
                f"wrong_key: key_id {kid} ≠ pinned {pinned}", serial_attempted=serial_hint
            )
        try:
            verify_detached(ptr_bytes, ptr_sig, self._pub, what="latest.json")
        except FeedRejected as e:
            raise FeedRejected(e.reason, serial_attempted=serial_hint) from None
        try:
            ptr = FeedPointer.model_validate(ptr_raw)
        except Exception:
            raise FeedRejected(
                "schema: latest.json pointer", serial_attempted=serial_hint
            ) from None
        if ptr.feed != self._source_id():
            raise FeedRejected(
                f"schema: feed {ptr.feed!r} != {self._source_id()!r}", serial_attempted=ptr.serial
            )
        return ptr_bytes, ptr_sig, ptr, ptr_sha

    async def _refresh_locked(self, trigger: str) -> None:
        import httpx

        url = self.url
        self._last_check = utcnow()
        if self._pub is None:
            self._load_pubkey()
        if url is None or self._pub is None or not getattr(self._source(), "enabled", True):
            return
        t0 = time.perf_counter()
        ptr_sha: str | None = None
        serial_attempted: int | None = None
        try:
            async with self._client(timeout=3.0) as client:
                ptr_bytes, ptr_sig, ptr, ptr_sha = await self._pull_pointer(client, url)
                serial_attempted = ptr.serial
                a = self.active
                if a is not None and ptr.serial == a.serial and ptr.sha256 == a.sha256:
                    if self._status in ("seed", "rejected", "unreachable", "disabled"):
                        self._status = "ok"
                        self._last_error = None
                    self.pending_serial = None
                    return
                cur = a.serial if a is not None else 0
                if ptr.serial <= cur:
                    raise FeedRejected(f"rollback: serial {ptr.serial} <= current {cur}")
                cached = self._cache_dir() / f"bundle-{ptr.serial:06d}.json"
                cached_ok = cached.exists() and sha256_hex(cached.read_bytes()) == ptr.sha256
                if ptr.serial <= self._high_water and not cached_ok:
                    raise FeedRejected(
                        f"rollback: serial {ptr.serial} <= high-water {self._high_water}"
                    )
                if self.pinned:
                    self.pending_serial = ptr.serial
                    log.info("feed serial %s available; operator pin holds %s", ptr.serial, cur)
                    return
                name = (
                    ptr.bundle
                    if ptr.bundle.startswith("bundle-")
                    else f"bundle-{ptr.serial:06d}.json"
                )
                b_bytes = await self._fetch(client, f"{url}/feed/bundle/{name}", MAX_BUNDLE_BYTES)
                if sha256_hex(b_bytes) != ptr.sha256:
                    raise FeedRejected("sha256_mismatch: bundle sha256 does not match latest.json")
                b_sig = (await self._fetch(client, f"{url}/feed/bundle/{name}.sig", 4096)).decode(
                    "ascii", "replace"
                )
            verify_t0 = time.perf_counter()
            verify_detached(b_bytes, b_sig, self._pub, what=name)
            verify_ms = (time.perf_counter() - verify_t0) * 1000
            try:
                doc = json.loads(b_bytes)
            except ValueError:
                raise FeedRejected("schema: bundle is not JSON") from None
            hdr = doc.get("feed") if isinstance(doc, dict) else None
            if (
                not isinstance(hdr, dict)
                or hdr.get("serial") != ptr.serial
                or hdr.get("name", self._source_id()) != self._source_id()
            ):
                raise FeedRejected("schema: bundle header does not match latest.json")
            new = await asyncio.to_thread(compile_bundle, doc, sha256=ptr.sha256, source=trigger)
            if new.expires is not None and new.expires < utcnow():
                raise FeedRejected(f"expired: bundle expired at {_iso(new.expires)}")
        except httpx.HTTPError as e:
            self._on_rejected(FeedRejected(f"unreachable: {type(e).__name__}"), trigger, url, None)
            return
        except FeedRejected as e:
            if e.serial_attempted is None:
                e.serial_attempted = serial_attempted
            self._on_rejected(e, trigger, url, ptr_sha)
            return
        await self._activate(
            new, b_bytes, b_sig, ptr_bytes, ptr_sig, trigger=trigger, verify_ms=verify_ms, t0=t0
        )

    def _history_item(self, feed: CompiledFeed, d: dict, *, verify_ms: float) -> dict:
        return {
            "serial": feed.serial,
            "version": feed.version,
            "applied_at": _iso(utcnow()),
            "added": len(d["added"]),
            "removed": len(d["removed"]),
            "modified": len(d["modified"]),
            "sha256": feed.sha256,
            "quarantined": len(feed.quarantined),
            "vectors": feed.vectors,
            "verify_ms": round(verify_ms, 2),
            "compile_ms": feed.compile_ms,
            "source": feed.source,
        }

    async def _activate(
        self,
        new: CompiledFeed,
        b_bytes: bytes,
        b_sig: str,
        ptr_bytes: bytes,
        ptr_sig: str,
        *,
        trigger: str,
        verify_ms: float,
        t0: float,
        actor: Identity | None = None,
        reason: str | None = None,
        rollback: bool = False,
    ) -> None:
        old = self.active
        d = diff(old, new)
        # atomic swap: one reference assignment; in-flight requests keep their snapshot
        self.previous, self.active = old, new
        self._high_water = max(self._high_water, new.serial)
        self._status = "ok"
        self._last_error = None
        self._last_update = utcnow()
        self.pending_serial = None
        self._reported.clear()
        item = self._history_item(new, d, verify_ms=verify_ms)
        if rollback:
            item["source"] = "rollback"
        self._history = ([*self._history, item])[-HISTORY_MAX:]
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        await asyncio.to_thread(self._persist, new, b_bytes, b_sig, ptr_bytes, ptr_sig)
        st = self.status()
        payload = st.model_dump(mode="json") | {
            "added": len(d["added"]),
            "removed": len(d["removed"]),
            "modified": len(d["modified"]),
            "added_ids": d["added"],
            "removed_ids": d["removed"],
            "modified_ids": d["modified"],
            "quarantined_ids": sorted(new.quarantined),
            "trigger": trigger,
            "latency_ms": latency_ms,
            "from_serial": old.serial if old else None,
            "rollback": rollback,
        }
        await self._audit(
            "feed.updated",
            new.serial,
            {
                "from": old.serial if old else None,
                "to": new.serial,
                "version": new.version,
                "sha256": new.sha256,
                "key_id": new.key_id,
                "added": d["added"],
                "removed": d["removed"],
                "modified": d["modified"],
                "quarantined": new.quarantined,
                "vectors": new.vectors,
                "latency_ms": latency_ms,
                "trigger": trigger,
                **({"rollback": True, "reason": reason} if rollback else {}),
            },
            actor=actor,
        )
        self._publish("feed.updated", payload)
        self._metric_gauge("aegis_feed_serial", new.serial)
        self._metric_inc("aegis_feed_reloads_total", {"result": "ok"})
        log.info(
            "feed applied serial=%s added=%s removed=%s modified=%s quarantined=%s ms=%.1f trigger=%s",
            new.serial,
            len(d["added"]),
            len(d["removed"]),
            len(d["modified"]),
            len(new.quarantined),
            latency_ms,
            trigger,
        )

    def _persist(
        self, new: CompiledFeed, b_bytes: bytes, b_sig: str, ptr_bytes: bytes, ptr_sig: str
    ) -> None:
        cache = self._cache_dir()
        try:
            cache.mkdir(parents=True, exist_ok=True)
            name = f"bundle-{new.serial:06d}.json"
            (cache / name).write_bytes(b_bytes)
            (cache / f"{name}.sig").write_text(b_sig, encoding="utf-8")
            (cache / "latest.json").write_bytes(ptr_bytes)
            (cache / "latest.json.sig").write_text(ptr_sig, encoding="utf-8")
            for p in sorted(cache.glob("bundle-*.json"))[:-KEEP_CACHE]:
                p.unlink(missing_ok=True)
                Path(str(p) + ".sig").unlink(missing_ok=True)
        except OSError:
            log.warning("feed cache write failed dir=%s", cache, exc_info=True)
        self._save_state(new)

    def _save_state(self, feed: CompiledFeed | None) -> None:
        if not self._db_ok:
            return
        try:
            con = self.rt.db()
            try:
                con.execute(
                    "INSERT INTO feed_state (feed_id, serial, version, sha256, applied_at, status, "
                    "last_error, history_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(feed_id) DO UPDATE SET serial=excluded.serial, version=excluded.version, "
                    "sha256=excluded.sha256, applied_at=excluded.applied_at, status=excluded.status, "
                    "last_error=excluded.last_error, history_json=excluded.history_json",
                    (
                        self._source_id(),
                        max(self._high_water, feed.serial if feed else 0),
                        feed.version if feed else None,
                        feed.sha256 if feed else None,
                        _iso(utcnow()),
                        self._status,
                        self._last_error,
                        json.dumps(self._history),
                    ),
                )
                con.commit()
            finally:
                con.close()
        except Exception:
            log.warning("feed_state write failed", exc_info=True)

    def _on_rejected(
        self, e: FeedRejected, trigger: str, url: str | None, ptr_sha: str | None
    ) -> None:
        reason = e.reason
        if reason.startswith("unreachable"):
            was = self._status
            self._status = "unreachable"
            self._last_error = reason
            if was != "unreachable":
                log.warning(
                    "threat feed unreachable url=%s (%s); enforcing serial %s",
                    url,
                    reason,
                    self.serial,
                )
                self._system(
                    "warning", f"threat feed unreachable ({url}); enforcing #{self.serial}"
                )
                self._metric_inc("aegis_feed_reloads_total", {"result": "unreachable"})
            return
        self._status = "rejected"
        self._last_error = reason
        key = (ptr_sha or "", reason)
        if key in self._reported:
            return
        self._reported.add(key)
        kept = self.serial
        log.warning(
            "feed bundle rejected reason=%s serial_attempted=%s kept_serial=%s trigger=%s",
            reason,
            e.serial_attempted,
            kept,
            trigger,
        )
        data = {
            "reason": reason,
            "serial_attempted": e.serial_attempted,
            "kept_serial": kept,
            "url": url,
            "trigger": trigger,
        }
        self._spawn(self._audit("feed.rejected", kept, data))
        self._publish(
            "feed.rejected",
            {"reason": reason, "serial_attempted": e.serial_attempted, "kept_serial": kept},
        )
        self._metric_inc("aegis_feed_reloads_total", {"result": "rejected"})
        with contextlib.suppress(Exception):
            self._save_state(self.active)

    def _rollback_files(self, serial: int) -> tuple[CompiledFeed, bytes, str, bytes, str]:
        cache = self._cache_dir()
        p = cache / f"bundle-{serial:06d}.json"
        if not p.exists():
            seed = self._seed_path()
            if (
                seed is not None
                and seed.exists()
                and json.loads(seed.read_bytes()).get("feed", {}).get("serial") == serial
            ):
                p = seed
            else:
                raise LookupError(f"no cached bundle for serial {serial} (last {KEEP_CACHE} kept)")
        feed = self._load_verified_file(p, source="rollback")
        data = p.read_bytes()
        sig = Path(str(p) + ".sig").read_text(encoding="utf-8")
        lp = cache / "latest.json"
        ptr = lp.read_bytes() if lp.exists() else b""
        ps = cache / "latest.json.sig"
        ptr_sig = ps.read_text(encoding="utf-8") if ps.exists() else ""
        return feed, data, sig, ptr, ptr_sig

    # ------------------------------------------------------------------ operator rollback
    async def rollback(
        self, serial: int, actor: Identity | None = None, reason: str | None = None
    ) -> FeedStatus:
        """Re-verify the cached bundle for `serial`, activate it and pin it (A-49)."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            t0 = time.perf_counter()
            feed, data, sig, ptr, ptr_sig = await asyncio.to_thread(
                self._rollback_files, int(serial)
            )
            self.pinned = True
            await self._activate(
                feed,
                data,
                sig,
                ptr,
                ptr_sig,
                trigger="rollback",
                verify_ms=0.0,
                t0=t0,
                actor=actor,
                reason=reason,
                rollback=True,
            )
        return self.status()

    # ------------------------------------------------------------------ services (guarded)
    def _publish(self, event: str, data: dict) -> None:
        bus = getattr(self.rt, "bus", None)
        if bus is None:
            return
        try:
            bus.publish(event, data)
        except Exception:
            log.debug("bus publish failed event=%s", event, exc_info=True)

    def _system(self, level: str, message: str) -> None:
        self._publish("system", {"level": level, "message": message, "component": "feed"})

    async def _audit(
        self, event_type: str, serial: int | None, data: dict, actor: Identity | None = None
    ) -> None:
        audit = getattr(self.rt, "audit", None)
        if audit is None:
            return
        try:
            await audit.record(
                AuditEvent(
                    event_id=new_id("evt"),
                    event_type=event_type,  # type: ignore[arg-type]
                    feed_serial=serial,
                    actor=actor,
                    data=data,
                )
            )
        except Exception:
            log.debug("audit record failed event=%s", event_type, exc_info=True)

    def _spawn(self, coro: Any) -> None:
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()

    def _metric_inc(self, name: str, labels: dict[str, str]) -> None:
        m = getattr(self.rt, "metrics", None)
        if m is not None:
            with contextlib.suppress(Exception):
                m.inc(name, labels)

    def _metric_gauge(self, name: str, value: float) -> None:
        m = getattr(self.rt, "metrics", None)
        if m is not None:
            with contextlib.suppress(Exception):
                m.set_gauge(name, value)


def create(rt: Any = None) -> FeedManager:
    """Service factory for `rt.feed` (cheap, no I/O; heavy work happens in start())."""
    return FeedManager(rt)
