"""`rt.org` - OrgService implementation (factory `aegis.org.service:create`).

SQLite is the source of truth (seeded from `config/org.seed.yaml` when empty); every read and
the identity hot path use an in-memory `OrgCache` rebuilt after each write. This service is the
only writer of the org-rbac tables (writes serialized by an asyncio.Lock, run in threads).
"""

from __future__ import annotations

import asyncio
import hmac as _hmac
import logging
import re
import secrets
import sqlite3
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from aegis.core.types import (
    ROLE_RANK,
    Agent,
    AuditEvent,
    Identity,
    Member,
    Org,
    Role,
    Team,
    new_id,
    utcnow,
)
from aegis.org import compat, identity, store
from aegis.org.models import KeyRecord, OrgCache, OrgChange, SeedBundle
from aegis.org.seed import SeedError, load_bundle, resolve_seed_path

log = logging.getLogger(__name__)

LAST_SEEN_FLUSH_S = 30.0
MINIMAL_SEED = {
    "org": Org(id="acme-capital", name="Acme Capital"),
    "owner": Member(
        id="u_katarzyna",
        org_id="acme-capital",
        name="Katarzyna Wiśniewska",
        role="owner",
        title="Owner (fallback org)",
        meta={"teams": []},
    ),
}


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def public_dict(obj: Member | Agent | None) -> dict[str, Any]:
    """JSON dict for audit / approval payloads (emails masked)."""
    if obj is None:
        return {}
    d = obj.model_dump(mode="json")
    if "email" in d:
        d["email"] = mask_email(d["email"])
    return d


class OrgServiceImpl:
    """Implements `aegis.core.protocols.OrgService` + org-rbac private helpers."""

    def __init__(self, rt: Any) -> None:
        self.rt = rt
        self.cache = OrgCache(org=MINIMAL_SEED["org"])
        self._health = "starting"
        self._health_reason: str | None = None
        self._lock: asyncio.Lock | None = None
        self._exec_lock: asyncio.Lock | None = None
        self._hmac: Callable[..., str] = compat.hmac_hex
        self._last_flush: dict[str, float] = {}
        self._seen_dirty: dict[str, datetime] = {}
        self._flush_task: asyncio.Task[Any] | None = None
        self.pending: dict[str, OrgChange] = {}
        self.listener_task: asyncio.Task[Any] | None = None
        self.test_mode = bool(compat.setting(rt, "test_mode", False))

    # ---------------------------------------------------------------- lifecycle

    @property
    def lock(self) -> asyncio.Lock:
        """Serializes DB writes + cache rebuilds."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def exec_lock(self) -> asyncio.Lock:
        """Serializes governed-change state transitions (pending -> applied/denied)."""
        if self._exec_lock is None:
            self._exec_lock = asyncio.Lock()
        return self._exec_lock

    def seed_path(self) -> Path:
        return resolve_seed_path(compat.setting(self.rt, "org_seed", None))

    def _connect(self) -> sqlite3.Connection:
        db = getattr(self.rt, "db", None)
        if callable(db):
            try:
                conn = db()
                conn.execute("PRAGMA busy_timeout=5000")
                return conn
            except Exception:
                log.warning("rt.db() failed; opening data dir database directly", exc_info=True)
        data_dir = Path(compat.setting(self.rt, "data_dir", "data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        return store.connect(data_dir / "aegis.db")

    def _with_conn(self, fn: Callable[..., Any], *args: Any) -> Any:
        conn = self._connect()
        try:
            result = fn(conn, *args)
            conn.commit()
            return result
        finally:
            conn.close()

    async def db(self, fn: Callable[..., Any], *args: Any) -> Any:
        return await asyncio.to_thread(self._with_conn, fn, *args)

    async def start(self) -> None:
        """Create tables, seed when empty, check HMAC canary, build the cache."""
        try:
            from aegis.core.crypto import hmac_hex as core_hmac

            self._hmac = core_hmac
        except ImportError:  # pragma: no cover
            self._hmac = compat.hmac_hex
        from aegis.org import changes

        changes.bind_service(self)
        seeded = await asyncio.to_thread(self._with_conn, self._start_sync)
        if seeded is not None:
            await self.audit(
                "seed",
                target=f"org:{self.cache.org.id}",
                reason=seeded,
                data={
                    "op": "seed",
                    "counts": self.counts(),
                    "seed_version": self.cache.org_meta.get("seed_version"),
                },
            )
        log.info(
            "org ready org=%s members=%d agents=%d keys=%d health=%s",
            self.cache.org.id,
            len(self.cache.members),
            len(self.cache.agents),
            len(self.cache.keys_by_id),
            self._health,
        )

    def _start_sync(self, conn: sqlite3.Connection) -> str | None:
        store.create_tables(conn)
        bundle: SeedBundle | None = None
        seed_error: str | None = None
        try:
            bundle = load_bundle(self.seed_path())
        except SeedError as exc:
            seed_error = str(exc)
        seeded: str | None = None
        self._health, self._health_reason = "ok", None
        if store.org_count(conn) == 0:
            if bundle is not None:
                store.apply_seed(conn, bundle, hmac_fn=self._hmac)
                seeded = f"seeded org from {self.seed_path().name}: {bundle.summary()}"
                log.info("org %s", seeded)
            else:
                log.error("org seed invalid and database empty; minimal org error=%s", seed_error)
                self._seed_minimal(conn)
                self._health, self._health_reason = "degraded", f"seed invalid: {seed_error}"
                seeded = "seeded minimal fallback org (seed invalid)"
        else:
            meta = store.get_meta(conn)
            if bundle is not None and meta.get("seed_sha256") not in (None, bundle.sha256):
                log.info(
                    "org seed changed on disk since last seed; run `python -m aegis seed "
                    "--reset` to apply it (runtime changes are kept)"
                )
            canary = self._hmac("aegis-org-canary", purpose="apikey")
            if meta.get("hmac_canary") not in (None, canary):
                self._rehash_seed_keys(conn, bundle, meta)
                store.set_meta(conn, "hmac_canary", canary)
            if seed_error:
                log.warning("org seed invalid (database kept) error=%s", seed_error)
        conn.commit()
        self._rebuild(conn, bundle)
        return seeded

    def _seed_minimal(self, conn: sqlite3.Connection) -> None:
        bundle = SeedBundle(
            org=MINIMAL_SEED["org"],
            org_meta={},
            teams=[],
            members=[MINIMAL_SEED["owner"]],
            agents=[],
            keys=[],
            resources={},
            view_as_aliases={},
            default_viewer=None,
            admin_token=None,
            seed_version="minimal",
        )
        store.apply_seed(conn, bundle, hmac_fn=self._hmac)

    def _rehash_seed_keys(
        self, conn: sqlite3.Connection, bundle: SeedBundle | None, meta: dict[str, Any]
    ) -> None:
        """HMAC key rotated without a DB wipe: re-hash seed keys; runtime keys become invalid."""
        seed_ids = set(meta.get("seed_key_ids") or [])
        rehashed = 0
        if bundle is not None:
            for k in bundle.keys:
                store.set_key_hmac(conn, k.key_id, self._hmac(k.plaintext, purpose="apikey"))
                rehashed += 1
                seed_ids.discard(k.key_id)
        rows = conn.execute("SELECT key_id FROM api_keys").fetchall()
        lost = [r[0] for r in rows if bundle is None or r[0] not in {k.key_id for k in bundle.keys}]
        log.warning(
            "hmac key changed: re-hashed %d seed keys; %d runtime keys are now invalid",
            rehashed,
            len(lost),
        )

    def _rebuild(self, conn: sqlite3.Connection, bundle: SeedBundle | None = None) -> None:
        """Rebuild the in-memory cache from SQLite (+ seed-file extras: resources, aliases)."""
        data = store.load_all(conn)
        if bundle is None:
            try:
                bundle = load_bundle(self.seed_path())
            except SeedError:
                bundle = None
        old = self.cache
        org = data["org"] or MINIMAL_SEED["org"]
        cache = OrgCache(org=org)
        cache.org_meta = dict(bundle.org_meta) if bundle else dict(old.org_meta)
        db_meta = data["meta"]
        if db_meta.get("seed_version"):
            cache.org_meta["seed_version"] = db_meta["seed_version"]
        cache.teams = {t.id: t for t in data["teams"]}
        cache.members = {m.id: m for m in data["members"]}
        cache.agents = {a.id: a for a in data["agents"]}
        for a in cache.agents.values():  # keep in-memory last_seen (newer than the DB)
            prev = old.agents.get(a.id)
            if (
                prev is not None
                and prev.last_seen
                and (not a.last_seen or prev.last_seen > a.last_seen)
            ):
                a.last_seen = prev.last_seen
        for k in data["keys"]:
            cache.keys_by_hmac[k.key_hmac] = k
            cache.keys_by_id[k.key_id] = k
        for a in cache.agents.values():
            if a.owner_member_id:
                cache.sponsored.setdefault(a.owner_member_id, []).append(a.id)
        cache.resources = bundle.resources if bundle else old.resources
        cache.admin_token = bundle.admin_token if bundle else old.admin_token
        cache.default_viewer = bundle.default_viewer if bundle else old.default_viewer
        roles: dict[str, str] = {}
        for role in ("owner", "admin", "member"):
            first = next(
                (m.id for m in cache.members.values() if m.role == role and m.active), None
            )
            if first:
                roles[role] = first
        if bundle:
            for alias, mid in bundle.view_as_aliases.items():
                if mid in cache.members:
                    roles[alias] = mid
        cache.role_aliases = roles
        identity.build_aliases(cache)
        self.cache = cache
        self.pending = {c.id: c for c in store.list_changes(conn, "pending")}

    async def reload(self) -> None:
        await self.db(self._rebuild)

    async def stop(self) -> None:
        if self.listener_task is not None:
            self.listener_task.cancel()
            self.listener_task = None
        if self._seen_dirty:
            items = list(self._seen_dirty.items())
            self._seen_dirty.clear()
            try:
                await self.db(store.touch_last_seen, items)
            except Exception:  # pragma: no cover
                log.warning("last_seen flush failed", exc_info=True)

    def health(self) -> str:
        return self._health if self._health != "starting" else "ok"

    def health_reason(self) -> str | None:
        return self._health_reason

    def counts(self) -> dict[str, int]:
        return {
            "members": len(self.cache.members),
            "agents": len(self.cache.agents),
            "teams": len(self.cache.teams),
            "keys": len(self.cache.keys_by_id),
        }

    # ---------------------------------------------------------------- data plane

    async def resolve_identity(
        self, headers: Mapping[str, str], *, hints: Mapping[str, str] | None = None
    ) -> Identity:
        now = utcnow()
        ident = identity.resolve(self.cache, headers, hints, now, self._hmac)
        if ident.known and ident.agent_id:
            self._touch(ident.agent_id, now)
        return ident

    def _touch(self, agent_id: str, now: datetime) -> None:
        agent = self.cache.agents.get(agent_id)
        if agent is None:
            return
        agent.last_seen = now
        if self.test_mode:
            return
        self._seen_dirty[agent_id] = now
        mono = time.monotonic()
        if mono - self._last_flush.get(agent_id, 0.0) < LAST_SEEN_FLUSH_S:
            return
        self._last_flush[agent_id] = mono
        if self._flush_task is not None and not self._flush_task.done():
            return
        items = list(self._seen_dirty.items())
        self._seen_dirty.clear()
        try:
            self._flush_task = asyncio.get_running_loop().create_task(
                self.db(store.touch_last_seen, items)
            )
        except RuntimeError:  # pragma: no cover - no loop
            pass

    # ---------------------------------------------------------------- dashboard viewer

    async def resolve_viewer(
        self, headers: Mapping[str, str], query: Mapping[str, str] | None = None
    ) -> Identity:
        demo = compat.setting(self.rt, "demo_mode", True)
        configured = compat.setting(self.rt, "default_viewer", None)
        if demo:
            return identity.resolve_viewer(
                self.cache, headers, query, configured_default=configured
            )
        # Non-demo (ORG-14): view-as honoured only with the admin token.
        token = compat.setting(self.rt, "admin_token", None) or self.cache.admin_token
        h = identity.lower_headers(headers)
        auth = (h.get("authorization") or "").strip()
        presented = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if token and presented and _hmac.compare_digest(presented.encode(), token.encode()):
            value, _ = identity.view_as_value(headers, query)
            mid = identity.resolve_alias(self.cache, value) if value else None
            if value and mid is None:  # unknown / agent id -> anonymous, never the default
                return identity.viewer_identity(self.cache, None)
            mid = mid or identity.default_viewer_id(self.cache, configured)
            return identity.viewer_identity(self.cache, mid, authenticated=True)
        return identity.viewer_identity(self.cache, None)

    # ---------------------------------------------------------------- reads (protocol)

    async def org(self) -> Org:
        return self.cache.org.model_copy(deep=True)

    async def list_teams(self) -> list[Team]:
        return [t.model_copy(deep=True) for t in self.cache.teams.values()]

    async def list_members(self) -> list[Member]:
        return [m.model_copy(deep=True) for m in self.cache.members.values()]

    async def list_agents(self) -> list[Agent]:
        return [a.model_copy(deep=True) for a in self.cache.agents.values()]

    async def get_member(self, member_id: str) -> Member | None:
        m = self.cache.members.get(member_id)
        return m.model_copy(deep=True) if m else None

    async def get_agent(self, agent_id: str) -> Agent | None:
        a = self.cache.agents.get(agent_id)
        if a is None:
            alias = identity.resolve_agent_alias(self.cache, agent_id) if agent_id else None
            a = self.cache.agents.get(alias) if alias else None
        return a.model_copy(deep=True) if a else None

    async def members_with_role(self, min_role: Role, team_id: str | None = None) -> list[Member]:
        need = ROLE_RANK.get(min_role, 1)
        out = []
        for m in self.cache.members.values():
            if not m.active or ROLE_RANK.get(m.role, 0) < need:
                continue
            if team_id and m.role != "owner":
                teams = m.meta.get("teams") or []
                if team_id != m.team_id and team_id not in teams:
                    continue
            out.append(m.model_copy(deep=True))
        return out

    async def resources(self) -> dict[str, Any]:
        import copy

        return copy.deepcopy(self.cache.resources)

    # ---------------------------------------------------------------- private fast paths

    def peek_agent(self, agent_id: str | None) -> Agent | None:
        """Hot path (no copy; do not mutate)."""
        if not agent_id:
            return None
        a = self.cache.agents.get(agent_id)
        if a is None:
            alias = self.cache.agent_aliases.get(agent_id.lower())
            a = self.cache.agents.get(alias) if alias else None
        return a

    def peek_member(self, member_id: str | None) -> Member | None:
        return self.cache.members.get(member_id) if member_id else None

    def sponsored(self, member_id: str) -> list[str]:
        return list(self.cache.sponsored.get(member_id, []))

    # ---------------------------------------------------------------- audit / bus

    async def audit(
        self,
        op: str,
        *,
        actor: Identity | None = None,
        target: str | None = None,
        reason: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        audit = getattr(self.rt, "audit", None)
        if audit is None:
            return
        try:
            await audit.record(
                AuditEvent(
                    event_id=new_id("evt"),
                    event_type="org.changed",
                    actor=actor,
                    resource=target,
                    reason=reason,
                    data={"op": op, **(data or {})},
                )
            )
        except Exception:
            log.warning("audit org.changed failed op=%s", op, exc_info=True)

    def publish(self, *, member: Member | None = None, agent: Agent | None = None) -> None:
        bus = getattr(self.rt, "bus", None)
        if bus is None:
            return
        payload: dict[str, Any] = {}
        if member is not None:
            payload["member"] = member.model_dump(mode="json")
        if agent is not None:
            payload["agent"] = agent.model_dump(mode="json")
        try:
            bus.publish("org.updated", payload)
        except Exception:
            log.warning("bus publish org.updated failed", exc_info=True)

    # ---------------------------------------------------------------- writes (direct)

    async def write_member(self, member: Member) -> Member:
        async with self.lock:

            def _w(conn: sqlite3.Connection) -> None:
                store.upsert_member(conn, member)
                conn.commit()
                self._rebuild(conn)

            await self.db(_w)
        return self.cache.members[member.id].model_copy(deep=True)

    async def write_agent(self, agent: Agent) -> Agent:
        async with self.lock:

            def _w(conn: sqlite3.Connection) -> None:
                store.upsert_agent(conn, agent)
                conn.commit()
                self._rebuild(conn)

            await self.db(_w)
        return self.cache.agents[agent.id].model_copy(deep=True)

    def new_member_id(self, name: str) -> str:
        first = (name or "member").split()[0].lower()
        slug = re.sub(r"[^a-z0-9]+", "", _ascii(first)) or "member"
        base = f"u_{slug}"
        candidate, n = base, 2
        while candidate in self.cache.members:
            candidate, n = f"{base}{n}", n + 1
        return candidate

    # ---------------------------------------------------------------- keys (ORG-12)

    def list_keys(self, agent_id: str | None = None) -> list[KeyRecord]:
        keys = list(self.cache.keys_by_id.values())
        if agent_id:
            keys = [k for k in keys if k.principal == f"agent:{agent_id}"]
        return [k.model_copy(deep=True) for k in keys]

    async def issue_key(
        self,
        agent_id: str,
        *,
        actor: Identity,
        scopes: list[str] | None = None,
        expires_at: datetime | None = None,
    ) -> tuple[KeyRecord, str]:
        plaintext = "aegis_" + secrets.token_urlsafe(32)
        short = re.sub(r"[^a-z0-9]+", "_", agent_id.split("@", 1)[0].lower()).strip("_")
        rec = KeyRecord(
            key_id=f"key_{short}_{secrets.token_hex(3)}",
            principal=f"agent:{agent_id}",
            key_hmac=self._hmac(plaintext, purpose="apikey"),
            scopes=list(scopes or ["openai.chat", "anthropic.messages", "mcp", "guard"]),
            created_by=actor.member_id,
            created_at=utcnow(),
            expires_at=expires_at,
        )
        async with self.lock:

            def _w(conn: sqlite3.Connection) -> None:
                store.insert_key(conn, rec)
                conn.commit()
                self._rebuild(conn)

            await self.db(_w)
        await self.audit(
            "key.issue",
            actor=actor,
            target=f"agent:{agent_id}",
            reason=f"API key {rec.key_id} issued for {agent_id}",
            data={"key_id": rec.key_id, "scopes": rec.scopes, "via": "direct"},
        )
        agent = self.cache.agents.get(agent_id)
        if agent is not None:
            self.publish(agent=agent)
        return rec, plaintext

    async def revoke_key(self, key_id: str, *, actor: Identity) -> KeyRecord | None:
        rec = self.cache.keys_by_id.get(key_id)
        if rec is None:
            return None
        if rec.revoked_at is None:
            async with self.lock:

                def _w(conn: sqlite3.Connection) -> None:
                    store.revoke_key(conn, key_id, utcnow())
                    conn.commit()
                    self._rebuild(conn)

                await self.db(_w)
            await self.audit(
                "key.revoke",
                actor=actor,
                target=rec.principal,
                reason=f"API key {key_id} revoked",
                data={"key_id": key_id, "via": "direct"},
            )
            agent_id = rec.principal.partition(":")[2]
            agent = self.cache.agents.get(agent_id)
            if agent is not None:
                self.publish(agent=agent)
        return self.cache.keys_by_id[key_id].model_copy(deep=True)

    # ---------------------------------------------------------------- governed changes

    async def list_changes(self, status: str | None = None, limit: int = 200) -> list[OrgChange]:
        return await self.db(store.list_changes, status, limit)

    async def reconcile(self, approval_id: str | None = None) -> int:
        from aegis.org import changes

        return await changes.reconcile(self, approval_id)


def _ascii(text: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def create(rt: Any) -> OrgServiceImpl:
    """Service factory (CONTRACTS section 3.3). Cheap; DB + seed work happens in start()."""
    return OrgServiceImpl(rt)


__all__ = ["OrgServiceImpl", "create", "mask_email", "public_dict"]
