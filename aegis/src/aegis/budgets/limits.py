"""Limit index: compiles `budgets.limits` and resolves the most specific entry per
(concrete scope, window, dimension).

Specificity: exact scope > glob with the longest literal prefix > `*`; an entry with
`match_agents` beats one without. AND semantics apply across *levels* of the scope chain, not
across duplicate entries for the same level (so raising `member:u_piotr` above `member:*` works).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

from aegis.core.types import Identity

DIMENSIONS: tuple[str, ...] = ("usd", "tokens", "compute_s", "requests", "tool_calls", "spend_usd")
SCOPE_TYPES: tuple[str, ...] = ("org", "team", "member", "agent", "session", "model", "tool")
AGGREGATED_TYPES = ("model", "tool")
GLOB_CHARS = set("*?[")
CACHE_KEY = "budgets-ledger:limits"


def scope_type(scope: str) -> str:
    kind = scope.split(":", 1)[0] if ":" in scope else scope
    return kind if kind in SCOPE_TYPES else "org"


def scope_id(scope: str) -> str:
    return scope.split(":", 1)[1] if ":" in scope else scope


def is_glob(pattern: str) -> bool:
    return any(c in GLOB_CHARS for c in pattern)


def _literal_prefix_len(pattern: str) -> int:
    for i, c in enumerate(pattern):
        if c in GLOB_CHARS:
            return i
    return len(pattern)


@dataclass(frozen=True)
class LimitEntry:
    scope: str
    scope_type: str
    window: str
    dims: dict[str, float]
    index: int
    soft_pct: float | None = None
    on_soft: str | None = None
    on_hard: str | None = None
    label: str | None = None
    match_agents: tuple[str, ...] = ()
    exact: bool = True
    specificity: tuple[int, int, int] = (0, 0, 0)

    def matches(self, concrete: str, identity: Identity | None) -> bool:
        if scope_type(concrete) != self.scope_type:
            return False
        if self.exact:
            ok = concrete == self.scope
        else:
            ok = fnmatchcase(concrete, self.scope)
        if not ok:
            return False
        if self.match_agents:
            agent = identity.agent_id if identity else None
            if not agent or not any(fnmatchcase(agent, g) for g in self.match_agents):
                return False
        return True

    @property
    def aggregated(self) -> bool:
        """model:/tool: glob entries keep ONE counter keyed by the entry's scope string."""
        return self.scope_type in AGGREGATED_TYPES and not self.exact


def counter_scope(entry: LimitEntry, concrete: str) -> str:
    """Scope string whose counter backs `entry` for `concrete` (per-instance vs aggregated)."""
    return entry.scope if entry.aggregated else concrete


@dataclass
class LimitIndex:
    entries: list[LimitEntry] = field(default_factory=list)
    by_type: dict[str, list[LimitEntry]] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    _resolve_cache: dict[tuple[str, str | None], dict[tuple[str, str], LimitEntry]] = field(
        default_factory=dict
    )

    @classmethod
    def compile_doc(cls, doc: Any) -> LimitIndex:
        budgets = getattr(doc, "budgets", None)
        limits = list(getattr(budgets, "limits", None) or [])
        d = getattr(budgets, "defaults", None)
        defaults = {
            "soft_pct": float(getattr(d, "soft_pct", 80.0) or 80.0),
            "on_soft": getattr(d, "on_soft", "warn") or "warn",
            "on_hard": getattr(d, "on_hard", "block") or "block",
            "max_output_tokens": getattr(d, "max_output_tokens", 4096),
            "local_concurrency": int(getattr(d, "local_concurrency", 1) or 1),
        }
        entries: list[LimitEntry] = []
        for i, lim in enumerate(limits):
            raw_scope = str(getattr(lim, "scope", "") or "").strip()
            if not raw_scope:
                continue
            st = scope_type(raw_scope)
            dims: dict[str, float] = {}
            for dim in DIMENSIONS:
                val = getattr(lim, dim, None)
                if val is not None:
                    dims[dim] = float(val)
            extra = getattr(lim, "model_extra", None) or {}
            ma = extra.get("match_agents") or ()
            if isinstance(ma, str):
                ma = (ma,)
            exact = not is_glob(raw_scope)
            spec = (1 if exact else 0, 1 if ma else 0, _literal_prefix_len(raw_scope))
            entries.append(
                LimitEntry(
                    scope=raw_scope,
                    scope_type=st,
                    window=str(getattr(lim, "window", "day") or "day"),
                    dims=dims,
                    index=i,
                    soft_pct=getattr(lim, "soft_pct", None),
                    on_soft=getattr(lim, "on_soft", None),
                    on_hard=getattr(lim, "on_hard", None),
                    label=getattr(lim, "label", None),
                    match_agents=tuple(str(x) for x in ma),
                    exact=exact,
                    specificity=spec,
                )
            )
        by_type: dict[str, list[LimitEntry]] = {}
        for e in entries:
            by_type.setdefault(e.scope_type, []).append(e)
        return cls(entries=entries, by_type=by_type, defaults=defaults)

    @classmethod
    def compile(cls, snapshot: Any) -> LimitIndex:
        """Compile (memoised in `snapshot.compiled["budgets-ledger:limits"]`)."""
        if snapshot is None:
            return cls()
        compiled = getattr(snapshot, "compiled", None)
        if isinstance(compiled, dict):
            hit = compiled.get(CACHE_KEY)
            if isinstance(hit, LimitIndex):
                return hit
        idx = cls.compile_doc(getattr(snapshot, "doc", snapshot))
        if isinstance(compiled, dict):
            compiled[CACHE_KEY] = idx
        return idx

    def resolve(
        self, concrete: str, identity: Identity | None = None
    ) -> dict[tuple[str, str], LimitEntry]:
        """{(window, dimension): most specific entry} for a concrete scope."""
        agent = identity.agent_id if identity else None
        key = (concrete, agent)
        hit = self._resolve_cache.get(key)
        if hit is not None:
            return hit
        out: dict[tuple[str, str], LimitEntry] = {}
        for e in self.by_type.get(scope_type(concrete), ()):
            if not e.matches(concrete, identity):
                continue
            for dim in e.dims:
                k = (e.window, dim)
                cur = out.get(k)
                if cur is None or e.specificity > cur.specificity:
                    out[k] = e
        if len(self._resolve_cache) > 5000:
            self._resolve_cache.clear()
        self._resolve_cache[key] = out
        return out

    def soft_pct(self, entry: LimitEntry) -> float:
        return float(
            entry.soft_pct if entry.soft_pct is not None else self.defaults.get("soft_pct", 80.0)
        )

    def on_soft(self, entry: LimitEntry) -> str:
        return entry.on_soft or self.defaults.get("on_soft", "warn")

    def on_hard(self, entry: LimitEntry) -> str:
        return entry.on_hard or self.defaults.get("on_hard", "block")

    def exact_scopes(self) -> list[str]:
        return [e.scope for e in self.entries if e.exact]

    def aggregated_entries_for(self, concrete: str, identity: Identity | None) -> list[LimitEntry]:
        """model:/tool: glob entries matching a concrete model/tool scope."""
        st = scope_type(concrete)
        if st not in AGGREGATED_TYPES:
            return []
        return [
            e for e in self.by_type.get(st, ()) if e.aggregated and e.matches(concrete, identity)
        ]

    def find(
        self, scope: str, window: str, match_agents: tuple[str, ...] | None = None
    ) -> LimitEntry | None:
        for e in self.entries:
            if (
                e.scope == scope
                and e.window == window
                and (match_agents is None or e.match_agents == match_agents)
            ):
                return e
        return None


__all__ = [
    "AGGREGATED_TYPES",
    "CACHE_KEY",
    "DIMENSIONS",
    "LimitEntry",
    "LimitIndex",
    "counter_scope",
    "is_glob",
    "scope_id",
    "scope_type",
]
