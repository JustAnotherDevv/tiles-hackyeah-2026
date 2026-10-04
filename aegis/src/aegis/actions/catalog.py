"""Resource catalog: databases/tables (sensitivity), vendors/plans (prices), external hosts.

Live source: ``await rt.org.resources()`` (org-rbac, seed ``resources:``), cached 5 s.
Fallback: ``FALLBACK_RESOURCES`` (a port of the corrected seed) with ``source="fallback"``
and one ``system`` warning. ACT-02 ``params.tables`` overrides are applied on top.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from aegis.actions import runtime as art
from aegis.actions.net import domain_match

log = logging.getLogger(__name__)

SENSITIVITY_RANK: dict[str, int] = {
    "PUBLIC": 0,
    "INTERNAL": 1,
    "CONFIDENTIAL": 2,
    "RESTRICTED": 3,
    "SECRET": 4,
}

# Port of docs/seed-fixes/org.seed.yaml `resources:` + org.internal_domains (fallback only).
FALLBACK_RESOURCES: dict[str, Any] = {
    "databases": [
        {
            "id": "acme-prod-pg",
            "environment": "prod",
            "mcp_server": "acme-db",
            "tables": [
                {
                    "name": "customers",
                    "sensitivity": "CONFIDENTIAL",
                    "categories": ["pii"],
                    "contains": ["PERSON", "EMAIL", "PHONE", "PESEL", "IBAN", "ADDRESS", "DOB"],
                },
                {
                    "name": "payment_cards",
                    "sensitivity": "RESTRICTED",
                    "categories": ["pci"],
                    "contains": ["PAN", "CARD_EXPIRY"],
                },
                {
                    "name": "trades",
                    "sensitivity": "CONFIDENTIAL",
                    "categories": ["mnpi"],
                    "contains": [],
                },
                {
                    "name": "positions",
                    "sensitivity": "CONFIDENTIAL",
                    "categories": ["mnpi"],
                    "contains": [],
                },
                {
                    "name": "research_notes",
                    "sensitivity": "INTERNAL",
                    "categories": [],
                    "contains": [],
                },
                {
                    "name": "market_prices",
                    "sensitivity": "PUBLIC",
                    "categories": [],
                    "contains": [],
                },
            ],
        },
        {
            "id": "acme-staging-pg",
            "environment": "staging",
            "mcp_server": "acme-db",
            "schema": "staging",
            "tables": [
                {
                    "name": "customers_synthetic",
                    "sensitivity": "INTERNAL",
                    "categories": ["synthetic"],
                    "contains": [],
                },
                {
                    "name": "trades_synthetic",
                    "sensitivity": "INTERNAL",
                    "categories": ["synthetic"],
                    "contains": [],
                },
                {
                    "name": "market_prices",
                    "sensitivity": "PUBLIC",
                    "categories": [],
                    "contains": [],
                },
            ],
        },
    ],
    "vendors": [
        {
            "id": "marketpulse",
            "name": "MarketPulse Pro",
            "approved": True,
            "host": "api.marketpulse.example",
            "mcp_server": "marketpulse",
            "plans": [
                {"id": "mp-pro-monthly", "usd": 50.0, "recurring": "monthly"},
                {"id": "mp-enterprise-annual", "usd": 4800.0, "recurring": "yearly"},
            ],
        },
        {
            "id": "opendata-shop",
            "name": "OpenData Shop",
            "approved": True,
            "host": "shop.opendata.example",
            "plans": [{"id": "eu-equities-2025-csv", "usd": 12.0, "recurring": "none"}],
        },
        {
            "id": "gpucloud",
            "name": "BurstGPU Cloud",
            "approved": True,
            "host": "api.burstgpu.example",
            "plans": [
                {"id": "a100-24h-reservation", "usd": 480.0, "recurring": "none"},
                {"id": "a100-cluster-week", "usd": 1500.0, "recurring": "none"},
            ],
        },
        {
            "id": "shady-signals",
            "name": "Shady Signals Ltd",
            "approved": False,
            "host": "signals.shady.example",
            "plans": [{"id": "alpha-signals", "usd": 15.0, "recurring": "monthly"}],
        },
    ],
    "external_hosts": [
        {"host": "smtp.acme-capital.example", "dest_class": "local"},
        {"host": "docs.acme-capital.example", "dest_class": "local"},
        {"host": "assets.acme-capital.example", "dest_class": "local"},
        {"host": "api.marketpulse.example", "dest_class": "third_party"},
        {"host": "hooks.slack.example", "dest_class": "third_party"},
        {"host": "client-portal.example", "dest_class": "third_party"},
        {"host": "pay.saas.test", "dest_class": "third_party"},
        {"host": "crm.saas.test", "dest_class": "third_party"},
        {"host": "paste.test", "dest_class": "third_party", "denylisted": True},
        {"host": "exfil.test", "dest_class": "third_party", "denylisted": True},
        {"host": "paste.exfil.example", "dest_class": "third_party", "denylisted": True},
    ],
    "internal_domains": ["acme-capital.example", "corp.acme-capital.example"],
}


@dataclass
class Table:
    name: str
    database: str
    sensitivity: str = "CONFIDENTIAL"
    categories: list[str] = field(default_factory=list)
    contains: list[str] = field(default_factory=list)
    overridden: bool = False


@dataclass
class Database:
    id: str
    environment: str = "prod"
    mcp_server: str | None = None
    schema: str | None = None
    tables: dict[str, Table] = field(default_factory=dict)


@dataclass
class Plan:
    id: str
    usd: float | None
    recurring: str = "none"


@dataclass
class Vendor:
    id: str
    name: str
    approved: bool = False
    host: str | None = None
    mcp_server: str | None = None
    plans: dict[str, Plan] = field(default_factory=dict)


@dataclass
class ResourceCatalog:
    databases: dict[str, Database] = field(default_factory=dict)
    vendors: dict[str, Vendor] = field(default_factory=dict)
    external_hosts: dict[str, dict[str, Any]] = field(default_factory=dict)
    internal_domains: list[str] = field(default_factory=list)
    source: str = "org"  # org | fallback

    # ---- lookups
    def database(self, db_id: str | None) -> Database | None:
        return self.databases.get(db_id) if db_id else None

    def table(self, db_id: str | None, name: str) -> Table | None:
        db = self.database(db_id)
        if db is None:
            return None
        key = name.lower().strip('"`[]')
        if key in db.tables:
            return db.tables[key]
        short = key.rsplit(".", 1)[-1]
        return db.tables.get(short)

    def vendor(self, ref: Any) -> Vendor | None:
        if not isinstance(ref, str) or not ref.strip():
            return None
        r = ref.strip().lower()
        r = r.removeprefix("vendor:")
        if r in self.vendors:
            return self.vendors[r]
        for v in self.vendors.values():
            if v.name.lower() == r or (v.host and domain_match(v.host, r)):
                return v
        return None

    def vendor_for_server(self, server: str | None) -> Vendor | None:
        if not server:
            return None
        for v in self.vendors.values():
            if v.mcp_server == server or v.id == server:
                return v
        return None

    def vendor_for_host(self, host: str | None) -> Vendor | None:
        if not host:
            return None
        for v in self.vendors.values():
            if v.host and domain_match(v.host, host):
                return v
        return None

    def plan(
        self, plan_ref: Any, vendor: Vendor | None = None
    ) -> tuple[Vendor | None, Plan | None]:
        if not isinstance(plan_ref, str) or not plan_ref.strip():
            return vendor, None
        p = plan_ref.strip().lower()
        if vendor is not None:
            return vendor, vendor.plans.get(p)
        for v in self.vendors.values():
            if p in v.plans:
                return v, v.plans[p]
        return None, None

    def denylisted(self, host: str | None) -> bool:
        if not host:
            return False
        return any(
            meta.get("denylisted") and domain_match(h, host)
            for h, meta in self.external_hosts.items()
        )


def _norm_plans(raw: Any) -> dict[str, Plan]:
    out: dict[str, Plan] = {}
    if isinstance(raw, dict):
        items = [{"id": k, **(v if isinstance(v, dict) else {"usd": v})} for k, v in raw.items()]
    elif isinstance(raw, list):
        items = [x for x in raw if isinstance(x, dict)]
    else:
        items = []
    for it in items:
        pid = str(it.get("id", "")).lower()
        if not pid:
            continue
        usd = it.get("usd", it.get("price_usd", it.get("price")))
        try:
            usd_f = float(usd) if usd is not None else None
        except (TypeError, ValueError):
            usd_f = None
        out[pid] = Plan(id=pid, usd=usd_f, recurring=str(it.get("recurring", "none") or "none"))
    return out


def build_catalog(
    resources: dict[str, Any] | None,
    *,
    source: str = "org",
    overrides: dict[str, Any] | None = None,
) -> ResourceCatalog:
    """Normalize ``rt.org.resources()`` (lists or dicts) into a :class:`ResourceCatalog`."""
    res = resources or {}
    cat = ResourceCatalog(source=source)
    dbs = res.get("databases") or []
    if isinstance(dbs, dict):
        dbs = [{"id": k, **v} for k, v in dbs.items() if isinstance(v, dict)]
    for d in dbs:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        db = Database(
            id=str(d["id"]),
            environment=str(d.get("environment", d.get("env", "prod"))),
            mcp_server=d.get("mcp_server"),
            schema=d.get("schema"),
        )
        tables = d.get("tables") or []
        if isinstance(tables, dict):
            tables = [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in tables.items()]
        for t in tables:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            name = str(t["name"]).lower()
            db.tables[name] = Table(
                name=name,
                database=db.id,
                sensitivity=str(t.get("sensitivity", "CONFIDENTIAL")).upper(),
                categories=list(t.get("categories") or []),
                contains=list(t.get("contains") or []),
            )
        cat.databases[db.id] = db
    vendors = res.get("vendors") or []
    if isinstance(vendors, dict):
        vendors = [{"id": k, **v} for k, v in vendors.items() if isinstance(v, dict)]
    for v in vendors:
        if not isinstance(v, dict) or not v.get("id"):
            continue
        vid = str(v["id"]).lower()
        cat.vendors[vid] = Vendor(
            id=vid,
            name=str(v.get("name", vid)),
            approved=bool(v.get("approved", False)),
            host=v.get("host"),
            mcp_server=v.get("mcp_server"),
            plans=_norm_plans(v.get("plans")),
        )
    hosts = res.get("external_hosts") or []
    if isinstance(hosts, dict):
        hosts = [{"host": k, **v} for k, v in hosts.items() if isinstance(v, dict)]
    for h in hosts:
        if isinstance(h, dict) and h.get("host"):
            cat.external_hosts[str(h["host"]).lower()] = dict(h)
    cat.internal_domains = [str(x) for x in (res.get("internal_domains") or [])]
    # ACT-02 params.tables overrides (judge lever), keyed "table" or "database.table"
    for key, ov in (overrides or {}).items():
        ovd = ov.model_dump(exclude_none=True) if hasattr(ov, "model_dump") else dict(ov or {})
        db_part, _, tname = str(key).lower().rpartition(".")
        for db in cat.databases.values():
            if db_part and db.id != db_part:
                continue
            tbl = db.tables.get(tname)
            if tbl is None:
                if db_part or db.id == next(iter(cat.databases), None):
                    tbl = db.tables[tname] = Table(name=tname, database=db.id)
                else:
                    continue
            if "sensitivity" in ovd:
                tbl.sensitivity = str(ovd["sensitivity"]).upper()
            if "categories" in ovd:
                tbl.categories = list(ovd["categories"])
            tbl.overridden = True
    return cat


# ------------------------------------------------------------------ cached access
_CACHE: dict[str, Any] = {}
CATALOG_TTL_S = 5.0


def clear_cache() -> None:
    _CACHE.clear()


async def _resources(rt: Any) -> tuple[dict[str, Any] | None, str]:
    now = time.monotonic()
    key = f"res:{id(rt)}"
    hit = _CACHE.get(key)
    if hit is not None and now - hit[0] < CATALOG_TTL_S:
        return hit[1], hit[2]
    res: dict[str, Any] | None = None
    source = "fallback"
    org = getattr(rt, "org", None) if rt is not None else None
    if org is not None:
        try:
            got = await org.resources()
            if isinstance(got, dict) and (got.get("databases") or got.get("vendors")):
                res, source = got, "org"
        except Exception as exc:
            log.warning("rt.org.resources() failed, using fallback catalog error=%s", exc)
    if res is None:
        art.warn_once(
            "catalog-fallback", "resource catalog unavailable; using built-in fallback (degraded)"
        )
        res = FALLBACK_RESOURCES
    _CACHE[key] = (now, res, source)
    return res, source


async def get_catalog(rt: Any = None, overrides: dict[str, Any] | None = None) -> ResourceCatalog:
    """Catalog from ``rt.org.resources()`` (5 s cache) + overrides; fallback when unavailable."""
    if rt is None:
        rt = art.current_rt()
    res, source = await _resources(rt)
    ov_key = repr(sorted((k, repr(v)) for k, v in (overrides or {}).items()))
    key = f"cat:{id(res)}:{ov_key}"
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    cat = build_catalog(res, source=source, overrides=overrides)
    if len(_CACHE) > 64:
        _CACHE.clear()
    _CACHE[key] = cat
    return cat


def internal_domains(
    snap: Any, cat: ResourceCatalog | None, extra: list[str] | None = None
) -> list[str]:
    """``destinations.internal_domains`` ∪ catalog ``internal_domains`` ∪ ``extra``."""
    out: list[str] = []
    try:
        out.extend(snap.doc.destinations.internal_domains)
    except Exception:
        pass
    if cat is not None:
        out.extend(cat.internal_domains)
    out.extend(extra or [])
    seen: list[str] = []
    for d in out:
        if d and d not in seen:
            seen.append(d)
    return seen


__all__ = [
    "FALLBACK_RESOURCES",
    "SENSITIVITY_RANK",
    "Database",
    "Plan",
    "ResourceCatalog",
    "Table",
    "Vendor",
    "build_catalog",
    "clear_cache",
    "domain_match",
    "get_catalog",
    "internal_domains",
]
