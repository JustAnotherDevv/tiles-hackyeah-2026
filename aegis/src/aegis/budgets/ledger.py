"""Budget ledger service (`rt.ledger`, CONTRACTS sections 3.2 / 3.3).

In-memory counters keyed `(scope, window, window_start, dimension)` with atomic check-and-reserve
across the whole scope chain (AND semantics; no `await` between check and commit), reserve ->
settle/release, write-behind SQLite persistence, threshold events and the shared state used by
the BUD-01 / BUD-02 / EXE-04 controls (loops, rate counters, runtime kills, enforcement log).

Scale path (documented, not built): the same multi-key reserve as a Redis Lua script.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aegis.core.policy_schema import KillSwitch, PolicyDoc, PolicySnapshot
from aegis.core.types import (
    BudgetDenial,
    BudgetStatus,
    Identity,
    RequestContext,
    Reservation,
    Usage,
    new_id,
)

from . import demo_seed, store, windows
from .enforcement import EnforcementLog
from .events import (
    DEFAULT_LEVELS,
    ThresholdTracker,
    UpdateCoalescer,
    audit_event,
    publish,
    set_gauge,
    spawn,
)
from .killswitch import RuntimeKills, any_active, as_dict, diff, kill_switch_of
from .ladder import SOFT_SEVERITY, format_message
from .limits import DIMENSIONS, LimitEntry, LimitIndex, counter_scope, scope_id, scope_type
from .loops import BurnRate, LoopRegistry
from .pricing import PricingTable, load_pricing
from .ratelimit import LocalSlots, SlidingCounter
from .schemas import DEFAULT_MESSAGE

log = logging.getLogger(__name__)

Key = tuple[str, str, str, str]  # (scope, window, window_start, dimension)
SAMPLE_DIMS = ("usd", "tokens", "compute_s")
SAMPLE_WINDOWS = ("day", "month", "session")
SAMPLE_EVERY_S = 5.0
SESSION_ACTIVE_S = 3600.0
SESSION_PRUNE_S = 24 * 3600.0
STATE_RANK = {"ok": 0, "soft": 1, "hard": 2, "killed": 3}
HISTORY_SPANS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


class BudgetStatusView(BudgetStatus):
    """`BudgetStatus` + the additive `soft_pct` field (Addendum A-36)."""

    soft_pct: float | None = None


def usage_dims(u: Usage) -> dict[str, float]:
    """Budget dimensions carried by a Usage (only positive amounts)."""
    d = {
        "usd": float(u.cost_usd or 0.0),
        "tokens": float((u.input_tokens or 0) + (u.output_tokens or 0)),
        "compute_s": float(u.compute_s or 0.0),
        "requests": float(u.requests or 0),
        "tool_calls": float(u.tool_calls or 0),
        "spend_usd": float(u.spend_usd or 0.0),
    }
    return {k: v for k, v in d.items() if v > 0}


def is_human(identity: Identity) -> bool:
    return not identity.agent_id and bool(identity.member_id)


@dataclass
class _Res:
    reservation: Reservation
    identity: Identity
    session_id: str
    scopes: list[str]
    amounts: dict[Key, float]
    expires: float


@dataclass
class Check:
    """Detailed outcome of a budget check (used by the BUD-01 control)."""

    denial: BudgetDenial | None = None
    denial_entry: LimitEntry | None = None
    denial_pct: float = 0.0
    soft: dict[str, Any] | None = None
    soft_entry: LimitEntry | None = None
    remaining: dict[str, Any] | None = None
    keys: dict[Key, float] = field(default_factory=dict)
    scopes: list[str] = field(default_factory=list)


class Ledger:
    """Implements `BudgetLedger` (+ extras used by budgets-ledger's controls and routes)."""

    def __init__(self, rt: Any = None, *, persist: bool = True) -> None:
        self.rt = rt
        settings = getattr(rt, "settings", None)
        if settings is None:
            try:
                from aegis.settings import get_settings

                settings = get_settings()
            except Exception:  # pragma: no cover - settings always importable
                settings = None
        self.settings = settings
        self.test_mode = bool(getattr(settings, "test_mode", False))
        self.demo_mode = bool(getattr(settings, "demo_mode", True))
        self.persist = persist
        self.pricing: PricingTable = PricingTable.default()
        self._used: dict[Key, float] = {}
        self._reserved: dict[Key, float] = {}
        self._res: dict[str, _Res] = {}
        self._dirty: set[Key] = set()
        self._sessions: dict[str, tuple[datetime, Identity]] = {}
        self._scope_ident: dict[str, Identity] = {}
        self._ws_cache: dict[tuple[str, str], tuple[str, datetime, datetime]] = {}
        self._last_sample: dict[tuple[str, str, str], float] = {}
        self._announced: set[tuple[str, bool]] = set()
        self._last_ks: KillSwitch | None = None
        self._empty_snapshot: PolicySnapshot | None = None
        self._conn: sqlite3.Connection | None = None
        self._db_lock: asyncio.Lock | None = None
        self._tasks: list[asyncio.Task[Any]] = []
        self._started = False
        self.thresholds = ThresholdTracker()
        self.coalescer = UpdateCoalescer(self._publish_updates, immediate=self.test_mode)
        self.enforcement = EnforcementLog()
        self.kills = RuntimeKills()
        self.loops = LoopRegistry()
        self.burn = BurnRate()
        self.rates = SlidingCounter()
        self.slots = LocalSlots()

    # ================================================================ protocol surface
    def scopes_for(self, identity: Identity, session_id: str) -> list[str]:
        out = [f"org:{identity.org_id or 'default'}"]
        if identity.team_id:
            out.append(f"team:{identity.team_id}")
        if identity.agent_id:
            out.append(f"agent:{identity.agent_id}")
        elif identity.member_id:
            out.append(f"member:{identity.member_id}")
        out.append(f"session:{session_id or 'default'}")
        return out

    async def reserve(
        self, ctx: RequestContext, estimate: Usage, scopes: list[str] | None = None
    ) -> Reservation | BudgetDenial:
        result, _ = self.evaluate(ctx, estimate, scopes, commit=True)
        return result

    async def check(
        self,
        ctx: RequestContext,
        estimate: Usage,
        scopes: list[str] | None = None,
        *,
        zero_usage: bool = False,
    ) -> Reservation | BudgetDenial:
        """Like reserve() but never commits (dry runs, previews, self-tests)."""
        result, _ = self.evaluate(ctx, estimate, scopes, commit=False, zero_usage=zero_usage)
        return result

    async def settle(self, reservation: Reservation, actual: Usage) -> list[BudgetStatus]:
        r = self._res.pop(reservation.id, None)
        if r is None:
            ident = Identity()
            scopes = list(reservation.scopes)
            session_id = next((scope_id(s) for s in scopes if s.startswith("session:")), "")
        else:
            self._unreserve(r.amounts)
            ident, scopes, session_id = r.identity, r.scopes, r.session_id
            est = r.reservation.estimate.cost_usd
            if est > 0 and actual.cost_usd > est * 1.5 + 0.001:
                log.info(
                    "budget settle overshoot res=%s estimate=%.4f actual=%.4f",
                    reservation.id,
                    est,
                    actual.cost_usd,
                )
        return await self._post(scopes, ident, session_id, usage_dims(actual), actual.cost_usd)

    async def release(self, reservation: Reservation) -> None:
        r = self._res.pop(reservation.id, None)
        if r is not None:
            self._unreserve(r.amounts)
            self.coalescer.mark(set(r.scopes))

    async def status(self, scope: str | None = None) -> list[BudgetStatus]:
        """Statuses of every known scope, or of one scope. For one scope the `usd`/`day` row is
        always present (limit 0, label "no limit" when unconfigured) - A-36, org-rbac's
        `/api/agents` `spend_today_usd`."""
        if not scope:
            return self.statuses(None)
        rows = self.statuses({scope})
        if not any(r.dimension == "usd" and r.window == "day" for r in rows):
            snap = self.snapshot()
            at = windows.now()
            tz = windows.zone(snap)
            used = self._used.get((scope, "day", self._ws("day", at, tz), "usd"), 0.0)
            rows.append(
                BudgetStatusView(
                    scope=scope,
                    scope_type=scope_type(scope),
                    dimension="usd",  # type: ignore[arg-type]
                    window="day",
                    limit=0.0,
                    used=round(used, 6),
                    reserved=0.0,
                    pct=0.0,
                    state="ok",
                    resets_at=windows.resets_at("day", at, tz),
                    label="no limit",
                )
            )
        return rows

    async def reset(self, scope: str | None = None, *, reseed: bool | None = None) -> None:
        if scope:
            for store_ in (self._used, self._reserved):
                for k in [k for k in store_ if k[0] == scope]:
                    store_.pop(k, None)
            self._dirty = {k for k in self._dirty if k[0] != scope}
            self.thresholds.clear(scope)
            if scope.startswith("session:"):
                sid = scope_id(scope)
                self._sessions.pop(sid, None)
                self.kills.discard(sid)
            await self._db_call(store.wipe, scope)
        else:
            self._used.clear()
            self._reserved.clear()
            self._res.clear()
            self._dirty.clear()
            self._sessions.clear()
            self._last_sample.clear()
            self.thresholds.clear()
            self.loops.reset()
            self.kills.clear()
            self.rates.reset()
            self.burn.reset()
            self.slots.reset()
            self.enforcement.clear()
            await self._db_call(store.wipe, None)
            if reseed if reseed is not None else self.demo_mode:
                await self.seed_demo()
        self.coalescer.mark(None)

    def price(self, model: str | None, usage: Usage) -> float:
        return self.pricing.price(model, usage)

    # ================================================================ core
    def snapshot(self, ctx: Any = None) -> PolicySnapshot:
        snap = getattr(ctx, "policy", None) if ctx is not None else None
        if snap is not None:
            return snap
        pol = getattr(self.rt, "policy", None)
        if pol is not None:
            try:
                snap = pol.snapshot()
                if snap is not None:
                    return snap
            except Exception:
                log.debug("policy snapshot unavailable", exc_info=True)
        if self._empty_snapshot is None:
            self._empty_snapshot = PolicySnapshot(version=0, sha256="", doc=PolicyDoc())
        return self._empty_snapshot

    def index(self, snap: Any = None) -> LimitIndex:
        return LimitIndex.compile(snap if snap is not None else self.snapshot())

    def _ws(self, window: str, at: datetime, tz: Any) -> str:
        if window in ("session", "total"):
            return window
        ck = (window, str(tz))
        hit = self._ws_cache.get(ck)
        if hit is not None and hit[1] <= at < hit[2]:
            return hit[0]
        start = windows.window_start_dt(window, at, tz)
        end = windows.resets_at(window, at, tz)
        if start is None or end is None:
            return "total"
        s = windows.iso(start)
        self._ws_cache[ck] = (s, start, end)
        return s

    def _counter_keys(
        self, scope: str, identity: Identity | None, index: LimitIndex, at: datetime, tz: Any
    ) -> list[tuple[str, str, str]]:
        st = scope_type(scope)
        out = [(scope, w, self._ws(w, at, tz)) for w in windows.windows_for(st)]
        for e in index.aggregated_entries_for(scope, identity):
            out.append((e.scope, e.window, self._ws(e.window, at, tz)))
        return out

    def _level(self, k: Key, zero_usage: bool = False) -> float:
        if zero_usage:
            return 0.0
        return self._used.get(k, 0.0) + self._reserved.get(k, 0.0)

    def evaluate(
        self,
        ctx: RequestContext,
        estimate: Usage,
        scopes: list[str] | None = None,
        *,
        commit: bool = True,
        zero_usage: bool = False,
    ) -> tuple[Reservation | BudgetDenial, Check]:
        """Atomic check (and reserve when `commit`) across every level of the chain."""
        snap = self.snapshot(ctx)
        index = LimitIndex.compile(snap)
        tz = windows.zone(snap)
        at = windows.now()
        ident = ctx.identity
        scopes = list(scopes or self.scopes_for(ident, ctx.session_id))
        amounts = usage_dims(estimate)
        chk = Check(scopes=scopes)
        best_rem: tuple[int, float] | None = None
        soft_rank = -1
        for scope in scopes:
            for cscope, w, ws in self._counter_keys(scope, ident, index, at, tz):
                for dim, amt in amounts.items():
                    chk.keys[(cscope, w, ws, dim)] = amt
            for (w, dim), entry in index.resolve(scope, ident).items():
                limit = entry.dims[dim]
                cscope = counter_scope(entry, scope)
                k = (cscope, w, self._ws(w, at, tz), dim)
                level = self._level(k, zero_usage)
                req = amounts.get(dim, 0.0)
                after = level + req
                pct = 100.0 if limit <= 0 else after / limit * 100.0
                if w == "day" and dim in ("usd", "tokens"):
                    rank = 0 if dim == "usd" else 1
                    head = limit - after
                    if best_rem is None or (rank, head) < best_rem:
                        best_rem = (rank, head)
                        chk.remaining = {dim: round(max(0.0, head), 4), "scope": cscope}
                if req <= 0:
                    continue
                if limit <= 0 or after > limit + 1e-9:
                    if chk.denial is None or pct > chk.denial_pct:
                        chk.denial_pct = pct
                        chk.denial_entry = entry
                        on_hard = index.on_hard(entry)
                        chk.denial = BudgetDenial(
                            scope=cscope,
                            dimension=dim,
                            window=w,
                            limit=limit,  # type: ignore[arg-type]
                            used=round(level, 6),
                            requested=round(req, 6),
                            action=on_hard
                            if on_hard in ("block", "require_approval", "downgrade")
                            else "block",
                            message=format_message(
                                DEFAULT_MESSAGE,
                                scope=cscope,
                                window=w,
                                dimension=dim,
                                used=level,
                                limit=limit,
                            ),
                            resets_at=windows.resets_at(w, at, tz),
                        )
                elif pct >= index.soft_pct(entry):
                    action = index.on_soft(entry)
                    rank = SOFT_SEVERITY.get(action, 0)
                    if rank > soft_rank or (
                        rank == soft_rank and chk.soft and pct > chk.soft["pct"]
                    ):
                        soft_rank = rank
                        chk.soft_entry = entry
                        chk.soft = {
                            "action": action,
                            "scope": cscope,
                            "dimension": dim,
                            "window": w,
                            "pct": round(pct, 2),
                            "limit": limit,
                            "used": round(level, 6),
                        }
        if chk.denial is not None:
            return chk.denial, chk
        res = Reservation(
            id=new_id("res") if commit else "res_check",
            scopes=scopes,
            estimate=estimate,
            meta={
                "soft": chk.soft,
                "remaining": chk.remaining,
                "pricing_version": self.pricing.version,
            },
        )
        if commit:
            for k, amt in chk.keys.items():
                self._reserved[k] = self._reserved.get(k, 0.0) + amt
            ttl = 600.0
            with contextlib.suppress(Exception):
                cfg = snap.controls.get("BUD-01")
                if cfg is not None:
                    ttl = float(cfg.params.get("reservation_ttl_s", ttl))
            self._res[res.id] = _Res(
                reservation=res,
                identity=ident,
                session_id=ctx.session_id,
                scopes=scopes,
                amounts=dict(chk.keys),
                expires=windows.monotonic() + ttl,
            )
            self._touch_session(ctx.session_id, ident, at)
        return res, chk

    def _unreserve(self, amounts: dict[Key, float]) -> None:
        for k, amt in amounts.items():
            v = self._reserved.get(k, 0.0) - amt
            if v <= 1e-12:
                self._reserved.pop(k, None)
            else:
                self._reserved[k] = v

    def _touch_session(self, session_id: str, ident: Identity, at: datetime) -> None:
        if session_id:
            self._sessions[session_id] = (at, ident)
            self._scope_ident[f"session:{session_id}"] = ident

    def _apply(
        self,
        scopes: list[str],
        ident: Identity,
        amounts: dict[str, float],
        at: datetime | None = None,
        *,
        window: str | None = None,
    ) -> set[Key]:
        """Add usage to every counter of the chain (sync, atomic)."""
        if not amounts:
            return set()
        snap = self.snapshot()
        index = LimitIndex.compile(snap)
        tz = windows.zone(snap)
        at = at or windows.now()
        changed: set[Key] = set()
        for scope in scopes:
            for cscope, w, ws in self._counter_keys(scope, ident, index, at, tz):
                if window is not None and w != window:
                    continue
                for dim, amt in amounts.items():
                    k = (cscope, w, ws, dim)
                    self._used[k] = self._used.get(k, 0.0) + amt
                    changed.add(k)
        self._dirty |= changed
        return changed

    async def _post(
        self,
        scopes: list[str],
        ident: Identity,
        session_id: str,
        amounts: dict[str, float],
        cost_usd: float = 0.0,
    ) -> list[BudgetStatus]:
        at = windows.now()
        self._apply(scopes, ident, amounts, at)
        self._touch_session(session_id, ident, at)
        if cost_usd > 0:
            self.burn.update(ident.principal, cost_usd)
        self._check_thresholds(scopes, ident, at)
        self.coalescer.mark(set(scopes) | self._aggregated_for(scopes, ident))
        if self.test_mode:
            await self.flush()
        return self.statuses(set(scopes), ident)

    async def commit(
        self, ctx: RequestContext, usage: Usage, scopes: list[str] | None = None
    ) -> list[BudgetStatus]:
        """Post usage without a reservation (pre-approved hops, externally settled calls)."""
        scopes = list(scopes or self.scopes_for(ctx.identity, ctx.session_id))
        return await self._post(
            scopes, ctx.identity, ctx.session_id, usage_dims(usage), usage.cost_usd
        )

    async def import_usage(
        self, scope: str, dimension: str, amount: float, window: str | None = None
    ) -> list[BudgetStatus]:
        """Manual usage import (vendor invoice / demo fast-forward) for one scope."""
        ident = self._scope_ident.get(scope) or self._identity_for_scope(scope)
        at = windows.now()
        self._apply([scope], ident, {dimension: float(amount)}, at, window=window)
        self._check_thresholds([scope], ident, at)
        self.coalescer.mark({scope})
        if self.test_mode:
            await self.flush()
        return self.statuses({scope}, ident)

    def _identity_for_scope(self, scope: str) -> Identity:
        st, sid = scope_type(scope), scope_id(scope)
        if st == "agent":
            return Identity(agent_id=sid)
        if st == "member":
            return Identity(member_id=sid, role="member")
        if st == "team":
            return Identity(team_id=sid)
        return Identity()

    def _aggregated_for(self, scopes: list[str], ident: Identity) -> set[str]:
        index = self.index()
        out: set[str] = set()
        for s in scopes:
            for e in index.aggregated_entries_for(s, ident):
                out.add(e.scope)
        return out

    def session_usage(self, session_id: str) -> dict[str, float]:
        scope = f"session:{session_id}"
        return {dim: self._used.get((scope, "session", "session", dim), 0.0) for dim in DIMENSIONS}

    def used(self, scope: str, window: str, dimension: str) -> float:
        snap = self.snapshot()
        k = (scope, window, self._ws(window, windows.now(), windows.zone(snap)), dimension)
        return self._used.get(k, 0.0)

    # ================================================================ thresholds & statuses
    def _levels(self, snap: Any) -> tuple[float, ...]:
        levels = set(DEFAULT_LEVELS)
        with contextlib.suppress(Exception):
            cfg = snap.controls.get("BUD-01")
            for x in (cfg.params.get("warn_pct") or []) if cfg is not None else []:
                levels.add(float(x))
        return tuple(sorted(levels))

    def _check_thresholds(self, scopes: list[str], ident: Identity, at: datetime) -> None:
        snap = self.snapshot()
        index = LimitIndex.compile(snap)
        tz = windows.zone(snap)
        levels = self._levels(snap)
        for scope in scopes:
            for (w, dim), entry in index.resolve(scope, ident).items():
                limit = entry.dims[dim]
                cscope = counter_scope(entry, scope)
                ws = self._ws(w, at, tz)
                k = (cscope, w, ws, dim)
                level = self._level(k)
                if level <= 0 and limit > 0:
                    continue
                pct = 100.0 if limit <= 0 else level / limit * 100.0
                for lvl in self.thresholds.crossings(k, pct, levels):
                    state = (
                        "hard" if pct >= 100 else ("soft" if pct >= index.soft_pct(entry) else "ok")
                    )
                    data = {
                        "scope": cscope,
                        "dimension": dim,
                        "window": w,
                        "pct": round(pct, 2),
                        "state": state,
                    }
                    publish(self.rt, "budget.threshold", data)
                    spawn(
                        audit_event(
                            self.rt,
                            "budget.threshold",
                            data={**data, "level": lvl, "limit": limit, "used": round(level, 6)},
                            reason=f"{cscope} {w} {dim} crossed {lvl:.0f}%",
                            control_id="BUD-01",
                            policy_version=snap.version,
                        )
                    )

    def _status_rows(
        self, scope: str, ident: Identity | None, index: LimitIndex, at: datetime, tz: Any
    ) -> list[BudgetStatus]:
        rows: list[BudgetStatus] = []
        for (w, dim), entry in sorted(
            index.resolve(scope, ident).items(),
            key=lambda kv: (DIMENSIONS.index(kv[0][1]), kv[0][0]),
        ):
            limit = entry.dims[dim]
            cscope = counter_scope(entry, scope)
            if cscope != scope:
                continue  # aggregated entries are reported under their own scope string
            k = (cscope, w, self._ws(w, at, tz), dim)
            used = self._used.get(k, 0.0)
            reserved = self._reserved.get(k, 0.0)
            pct = 100.0 if limit <= 0 else (used + reserved) / limit * 100.0
            state = "hard" if pct >= 100.0 else ("soft" if pct >= index.soft_pct(entry) else "ok")
            rows.append(
                BudgetStatusView(
                    scope=scope,
                    scope_type=scope_type(scope),
                    dimension=dim,  # type: ignore[arg-type]
                    window=w,
                    limit=limit,
                    used=round(used, 6),  # type: ignore[arg-type]
                    reserved=round(reserved, 6),
                    pct=round(pct, 2),
                    state=state,
                    resets_at=windows.resets_at(w, at, tz),
                    label=entry.label,
                    soft_pct=index.soft_pct(entry),
                )
            )
        return rows

    def known_scopes(self) -> list[str]:
        index = self.index()
        seen: dict[str, None] = {}
        for s in index.exact_scopes():
            seen[s] = None
        for e in index.entries:
            if e.aggregated:
                seen[e.scope] = None
        cutoff = windows.now() - timedelta(seconds=SESSION_ACTIVE_S)
        for k in list(self._used) + list(self._reserved):
            s = k[0]
            if s.startswith("session:"):
                last = self._sessions.get(scope_id(s))
                if last is None or last[0] < cutoff:
                    continue
            seen[s] = None
        return list(seen)

    def statuses(
        self, scopes: set[str] | None = None, ident: Identity | None = None
    ) -> list[BudgetStatus]:
        snap = self.snapshot()
        index = LimitIndex.compile(snap)
        tz = windows.zone(snap)
        at = windows.now()
        out: list[BudgetStatus] = []
        for scope in sorted(scopes) if scopes is not None else self.known_scopes():
            who = (
                (ident if ident is not None and scope.startswith("session:") else None)
                or self._scope_ident.get(scope)
                or self._identity_for_scope(scope)
            )
            out.extend(self._status_rows(scope, who, index, at, tz))
        return out

    def _publish_updates(self, scopes: set[str] | None) -> None:
        statuses = self.statuses(scopes)
        publish(
            self.rt, "budget.updated", {"statuses": [s.model_dump(mode="json") for s in statuses]}
        )
        best: dict[tuple[str, str], BudgetStatus] = {}
        for s in statuses:
            if s.scope_type == "session":
                continue
            k = (s.scope, s.dimension)
            if k not in best or s.pct > best[k].pct:
                best[k] = s
        for (scope, dim), s in best.items():
            set_gauge(
                self.rt,
                "aegis_budget_utilization_ratio",
                round(s.pct / 100.0, 4),
                {"scope_type": s.scope_type, "scope": scope, "dimension": dim},
            )

    # ================================================================ kill switch
    def kill_switch(self, snap: Any = None) -> KillSwitch:
        return kill_switch_of(snap if snap is not None else self.snapshot())

    def kill_switch_view(self, snap: Any = None) -> dict[str, Any]:
        return as_dict(self.kill_switch(snap), self.kills.sessions())

    def killswitch_gauge(self, snap: Any = None) -> None:
        active = any_active(self.kill_switch(snap)) or bool(self.kills.sessions())
        set_gauge(self.rt, "aegis_killswitch_active", 1.0 if active else 0.0)

    def announce_kill(
        self,
        scope: str,
        active: bool,
        *,
        actor: Identity | None = None,
        source: str = "budgets-ledger",
        reason: str | None = None,
    ) -> None:
        """Publish an immediate `killswitch` event (ladder kills) and skip its later echo."""
        self._announced.add((scope, active))
        publish(
            self.rt,
            "killswitch",
            {
                "scope": scope,
                "active": active,
                "actor": actor.model_dump(mode="json") if actor else None,
            },
        )
        spawn(
            audit_event(
                self.rt,
                "killswitch.toggled",
                actor=actor,
                reason=reason,
                control_id="EXE-04",
                data={
                    "scope": scope,
                    "active": active,
                    "source": source,
                    "policy_version": self.snapshot().version,
                },
            )
        )
        self.killswitch_gauge()

    def _on_policy(self, snap: Any) -> None:
        """rt.policy.on_change callback: rescale gauges, diff the kill switch."""
        try:
            new = kill_switch_of(snap)
            old = self._last_ks
            self._last_ks = new
            self.kills.drop_present(new)
            self.coalescer.mark(None)
            changes = diff(old, new) if old is not None else []
            fresh = []
            for scope, active in changes:
                if (scope, active) in self._announced:
                    self._announced.discard((scope, active))
                    continue
                fresh.append((scope, active))
            if fresh:
                spawn(self._announce_policy_kills(fresh, snap))
            self.killswitch_gauge(snap)
        except Exception:
            log.exception("budgets policy on_change failed")

    async def _announce_policy_kills(self, changes: list[tuple[str, bool]], snap: Any) -> None:
        actor = await self._actor(getattr(snap, "applied_by", None))
        for scope, active in changes:
            publish(
                self.rt,
                "killswitch",
                {
                    "scope": scope,
                    "active": active,
                    "actor": actor.model_dump(mode="json") if actor else None,
                },
            )
            await audit_event(
                self.rt,
                "killswitch.toggled",
                actor=actor,
                reason=f"kill switch {'on' if active else 'off'} for {scope}",
                control_id="EXE-04",
                policy_version=getattr(snap, "version", None),
                data={
                    "scope": scope,
                    "active": active,
                    "source": getattr(snap, "source", None),
                    "policy_version": getattr(snap, "version", None),
                },
            )
            if active:
                self.enforcement.record("kill", scope, "EXE-04", "kill switch engaged (policy)")
            log.info(
                "killswitch %s scope=%s version=%s",
                "on" if active else "off",
                scope,
                getattr(snap, "version", None),
            )

    async def _actor(self, member_id: str | None) -> Identity | None:
        if not member_id:
            return None
        org = getattr(self.rt, "org", None)
        try:
            m = await org.get_member(member_id) if org is not None else None
        except Exception:
            m = None
        if m is None:
            return Identity(member_id=member_id, role="member")
        return Identity(
            org_id=m.org_id,
            team_id=m.team_id,
            member_id=m.id,
            role=m.role,
            display_name=m.name,
            authenticated=True,
        )

    # ================================================================ persistence
    async def _open_db(self) -> None:
        if not self.persist or self._conn is not None:
            return
        conn = None
        db = getattr(self.rt, "db", None)
        if callable(db):
            try:
                conn = db()
            except Exception:
                conn = None
        if conn is None and self.settings is not None:
            try:
                conn = await asyncio.to_thread(_connect, Path(self.settings.data_dir))
            except Exception:
                log.warning("budget store unavailable - counters stay in memory", exc_info=True)
                conn = None
        if conn is None:
            return
        try:
            await asyncio.to_thread(store.ensure_schema, conn)
        except Exception:
            log.warning("budget store DDL failed - counters stay in memory", exc_info=True)
            return
        self._conn = conn

    async def _db_call(self, fn: Any, *args: Any) -> Any:
        if self._conn is None:
            return None
        if self._db_lock is None:
            self._db_lock = asyncio.Lock()
        async with self._db_lock:
            try:
                return await asyncio.to_thread(fn, self._conn, *args)
            except Exception:
                log.warning(
                    "budget store call failed fn=%s", getattr(fn, "__name__", fn), exc_info=True
                )
                return None

    async def _load_current(self) -> bool:
        """Load the current windows from SQLite; True when the table was empty."""
        if self._conn is None:
            return True
        snap = self.snapshot()
        tz = windows.zone(snap)
        at = windows.now()
        starts = [self._ws(w, at, tz) for w in ("hour", "day", "week", "month")]
        since = windows.iso(at - timedelta(seconds=SESSION_PRUNE_S))
        empty = await self._db_call(store.is_empty)
        rows = await self._db_call(store.load_current, starts, since) or []
        for scope, w, ws, dim, used, updated in rows:
            self._used[(scope, w, ws, dim)] = used
            if scope.startswith("session:"):
                with contextlib.suppress(Exception):
                    ts = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
                    self._sessions.setdefault(scope_id(scope), (ts, Identity()))
        return bool(empty) if empty is not None else not rows

    def _limit_for(self, scope: str, window: str, dim: str) -> float | None:
        index = self.index()
        ident = self._scope_ident.get(scope) or self._identity_for_scope(scope)
        entry = index.resolve(scope, ident).get((window, dim))
        if entry is None:
            # aggregated entries report under their own scope string
            for e in index.entries:
                if e.scope == scope and e.window == window and dim in e.dims:
                    return e.dims[dim]
            return None
        return entry.dims[dim]

    async def flush(self) -> None:
        """Write-behind: dirty counters -> budget_usage, burn-down samples (<= 1 per 5 s)."""
        if self._conn is None or not self._dirty:
            self._dirty.clear() if self._conn is None else None
            return
        keys = list(self._dirty)
        self._dirty.clear()
        ts = windows.iso(windows.now())
        rows = [
            (s, w, ws, d, round(self._used.get((s, w, ws, d), 0.0), 9), ts)
            for (s, w, ws, d) in keys
        ]
        mono = windows.monotonic()
        samples = []
        for s, w, _ws, d in keys:
            if d not in SAMPLE_DIMS or w not in SAMPLE_WINDOWS:
                continue
            sk = (s, d, w)
            if mono - self._last_sample.get(sk, -1e9) < SAMPLE_EVERY_S:
                continue
            self._last_sample[sk] = mono
            samples.append(
                (
                    ts,
                    s,
                    d,
                    w,
                    round(self._used.get((s, w, _ws, d), 0.0), 9),
                    self._limit_for(s, w, d),
                )
            )
        await self._db_call(store.flush, rows)
        if samples:
            await self._db_call(store.insert_samples, samples)

    async def seed_demo(self) -> int:
        """Counters + synthetic samples from `demo_state.budget_usage` (org seed, read-only)."""
        path = getattr(self.settings, "org_seed", None) if self.settings is not None else None
        seed = demo_seed.read_seed(path)
        counters = demo_seed.seed_counters(seed)
        if not counters:
            return 0
        snap = self.snapshot()
        tz = windows.zone(snap)
        at = windows.now()
        for scope, w, dim, used in counters:
            k = (scope, w, self._ws(w, at, tz), dim)
            self._used[k] = used
            self._dirty.add(k)
        samples = demo_seed.synthetic_samples(counters, at, tz, self._limit_for)
        await self.flush()
        if samples:
            await self._db_call(store.insert_samples, samples)
        self.coalescer.mark(None)
        log.info("budget demo state seeded counters=%d samples=%d", len(counters), len(samples))
        return len(counters)

    # ================================================================ history & tree
    async def history(
        self, scope: str, dimension: str = "usd", range_: str = "24h"
    ) -> dict[str, Any]:
        span = HISTORY_SPANS.get(range_, HISTORY_SPANS["24h"])
        st = scope_type(scope)
        window = (
            "session" if st == "session" else ("day" if span <= HISTORY_SPANS["24h"] else "month")
        )
        at = windows.now()
        snap = self.snapshot()
        tz = windows.zone(snap)
        since = at - span
        limit = self._limit_for(scope, window, dimension)
        k = (scope, window, self._ws(window, at, tz), dimension)
        used_now = self._used.get(k, 0.0)
        rows = (
            await self._db_call(store.query_samples, scope, dimension, window, windows.iso(since))
            or []
        )
        points = [
            {"ts": ts, "used": round(u, 6), "limit": lim if lim is not None else (limit or 0)}
            for ts, u, lim in rows
        ]
        if not points:
            start = windows.window_start_dt(window, at, tz)
            t0 = max(start, since) if start is not None else since
            points.append({"ts": windows.iso(t0), "used": 0.0, "limit": limit or 0})
        points.append({"ts": windows.iso(at), "used": round(used_now, 6), "limit": limit or 0})
        return {
            "scope": scope,
            "dimension": dimension,
            "points": points,
            "forecast": self.forecast(scope, dimension),
        }

    def forecast(self, scope: str, dimension: str = "usd") -> dict[str, Any] | None:
        """Linear month-end projection of the month counter."""
        if scope_type(scope) == "session":
            return None
        snap = self.snapshot()
        tz = windows.zone(snap)
        at = windows.now()
        start = windows.window_start_dt("month", at, tz)
        end = windows.resets_at("month", at, tz)
        if start is None or end is None:
            return None
        used = self._used.get((scope, "month", self._ws("month", at, tz), dimension), 0.0)
        elapsed = max((at - start).total_seconds(), 3600.0)
        total = (end - start).total_seconds()
        projected = used * total / elapsed
        return {
            "at": windows.iso(end),
            "used": round(projected, 4),
            "limit": self._limit_for(scope, "month", dimension),
        }

    async def tree(self) -> dict[str, Any]:
        """`BudgetsResponse` dict: org -> teams -> members/agents -> recent sessions + model/tool."""
        snap = self.snapshot()
        index = LimitIndex.compile(snap)
        tz = windows.zone(snap)
        at = windows.now()
        ks = self.kill_switch(snap)
        org = getattr(self.rt, "org", None)
        org_obj, teams, members, agents = None, [], [], []
        if org is not None:
            for name in ("org", "list_teams", "list_members", "list_agents"):
                try:
                    val = await getattr(org, name)()
                except Exception:
                    val = None if name == "org" else []
                if name == "org":
                    org_obj = val
                elif name == "list_teams":
                    teams = list(val or [])
                elif name == "list_members":
                    members = list(val or [])
                else:
                    agents = list(val or [])
        known = self.known_scopes()
        org_ids = [s for s in known if s.startswith("org:")]
        org_scope = (
            f"org:{org_obj.id}"
            if org_obj is not None
            else (org_ids[0] if org_ids else "org:default")
        )
        views: dict[str, dict[str, Any]] = {}

        def add(scope: str, name: str, parent: str | None, ident: Identity | None = None) -> None:
            if scope in views:
                return
            views[scope] = {
                "scope": scope,
                "scope_type": scope_type(scope),
                "name": name,
                "parent": parent,
                "ident": ident,
            }

        add(org_scope, org_obj.name if org_obj is not None else scope_id(org_scope), None)
        for s in org_ids:
            add(s, scope_id(s), None)
        for t in teams:
            add(f"team:{t.id}", t.name, org_scope, Identity(org_id=t.org_id, team_id=t.id))
        for m in members:
            parent = f"team:{m.team_id}" if m.team_id else org_scope
            add(
                f"member:{m.id}",
                m.name,
                parent,
                Identity(org_id=m.org_id, team_id=m.team_id, member_id=m.id, role=m.role),
            )
        for a in agents:
            parent = f"team:{a.team_id}" if a.team_id else org_scope
            add(
                f"agent:{a.id}",
                a.name,
                parent,
                Identity(
                    org_id=a.org_id, team_id=a.team_id, agent_id=a.id, member_id=a.owner_member_id
                ),
            )
        recent = sorted(self._sessions.items(), key=lambda kv: kv[1][0], reverse=True)
        cutoff = at - timedelta(seconds=SESSION_ACTIVE_S)
        n_sessions = 0
        for sid, (seen, ident) in recent:
            if seen < cutoff or n_sessions >= 20:
                break
            parent = (
                f"agent:{ident.agent_id}"
                if ident.agent_id
                else f"member:{ident.member_id}"
                if ident.member_id
                else org_scope
            )
            add(f"session:{sid}", sid, parent, ident)
            n_sessions += 1
        for s in known:
            st = scope_type(s)
            if st == "session":
                continue
            parent = (
                org_scope
                if st in ("team", "model", "tool")
                else (
                    f"team:{self._scope_ident[s].team_id}"
                    if s in self._scope_ident and self._scope_ident[s].team_id
                    else org_scope
                )
            )
            add(s, scope_id(s), None if st == "org" else parent)
        runtime = set(self.kills.sessions())
        out = []
        for scope, v in views.items():
            ident = (
                v.pop("ident") or self._scope_ident.get(scope) or self._identity_for_scope(scope)
            )
            limits = self._status_rows(scope, ident, index, at, tz)
            killed = self._killed_scope(scope, ks, runtime)
            if killed:
                state = "killed"
                limits = [lim.model_copy(update={"state": "killed"}) for lim in limits]
            else:
                state = max(
                    (lim.state for lim in limits), key=lambda s: STATE_RANK[s], default="ok"
                )
            out.append(
                {**v, "state": state, "limits": [lim.model_dump(mode="json") for lim in limits]}
            )
        order = {"org": 0, "team": 1, "member": 2, "agent": 3, "session": 4, "model": 5, "tool": 6}
        out.sort(key=lambda x: (order.get(x["scope_type"], 9), x["parent"] or "", x["scope"]))
        return {
            "generated_at": windows.iso(at),
            "currency": "USD",
            "pricing_version": self.pricing.version,
            "scopes": out,
            "kill_switch": as_dict(ks, sorted(runtime)),
        }

    @staticmethod
    def _killed_scope(scope: str, ks: KillSwitch, runtime: set[str]) -> bool:
        from fnmatch import fnmatchcase

        if ks.global_:
            return True
        st, sid = scope_type(scope), scope_id(scope)
        lists = {"team": ks.teams, "member": ks.members, "agent": ks.agents, "session": ks.sessions}
        if st == "session" and sid in runtime:
            return True
        return any(p == sid or fnmatchcase(sid, p) for p in lists.get(st, []))

    # ================================================================ lifecycle
    def _load_pricing(self) -> bool:
        path = getattr(self.settings, "pricing", None) if self.settings is not None else None
        try:
            self.pricing = load_pricing(path)
            return True
        except Exception as exc:
            log.warning("pricing load failed path=%s error=%s - keeping last good", path, exc)
            return False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._load_pricing()
        snap = self.snapshot()
        self._last_ks = kill_switch_of(snap)
        pol = getattr(self.rt, "policy", None)
        if pol is not None:
            try:
                pol.on_change(self._on_policy)
            except Exception:
                log.warning("policy.on_change unavailable - limits read per request")
        await self._open_db()
        empty = await self._load_current()
        if empty and self.demo_mode:
            await self.seed_demo()
        self.killswitch_gauge(snap)
        if not self.test_mode:
            self._tasks = [
                asyncio.create_task(self._flush_loop(), name="budgets-flush"),
                asyncio.create_task(self._sweep_loop(), name="budgets-sweep"),
                asyncio.create_task(self._pricing_watch(), name="budgets-pricing"),
            ]
        log.info(
            "budget ledger started pricing=%s persist=%s test_mode=%s",
            self.pricing.version,
            self._conn is not None,
            self.test_mode,
        )

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks = []
        self.coalescer.cancel()
        with contextlib.suppress(Exception):
            await self.flush()
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()
            self._conn = None
        self._started = False

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            try:
                await self.flush()
            except Exception:
                log.exception("budget flush failed")

    async def sweep(self) -> int:
        """Settle expired reservations at their estimate; prune idle sessions."""
        now = windows.monotonic()
        expired = [r for r in self._res.values() if r.expires < now]
        for r in expired:
            log.info("reservation expired res=%s - settling at estimate", r.reservation.id)
            await self.settle(r.reservation, r.reservation.estimate)
        cutoff = windows.now() - timedelta(seconds=SESSION_PRUNE_S)
        stale = [sid for sid, (seen, _) in self._sessions.items() if seen < cutoff]
        for sid in stale:
            self._sessions.pop(sid, None)
            self._scope_ident.pop(f"session:{sid}", None)
            scope = f"session:{sid}"
            for k in [k for k in self._used if k[0] == scope]:
                self._used.pop(k, None)
        return len(expired)

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(5.0)
            try:
                await self.sweep()
            except Exception:
                log.exception("budget sweep failed")

    async def _pricing_watch(self) -> None:
        path = getattr(self.settings, "pricing", None) if self.settings is not None else None
        if not path:
            return
        p = Path(path)
        try:
            from watchfiles import awatch
        except ImportError:
            return
        if not p.parent.exists():
            return
        async for changes in awatch(p.parent, debounce=200, recursive=False):
            if not any(Path(c[1]).name == p.name for c in changes):
                continue
            ok = self._load_pricing()
            level = "info" if ok else "warning"
            msg = (
                f"pricing reloaded version={self.pricing.version}"
                if ok
                else "pricing reload failed - keeping last good prices"
            )
            publish(self.rt, "system", {"level": level, "component": "budgets", "message": msg})
            await audit_event(
                self.rt,
                "system",
                reason=msg,
                data={"component": "budgets", "pricing_version": self.pricing.version, "ok": ok},
            )


def _connect(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(data_dir / "aegis.db"), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def create(rt: Any) -> Ledger:
    """Service factory for `rt.ledger` (cheap, no I/O)."""
    return Ledger(rt)


def utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC)


__all__ = ["BudgetStatusView", "Check", "Ledger", "create", "is_human", "usage_dims"]
