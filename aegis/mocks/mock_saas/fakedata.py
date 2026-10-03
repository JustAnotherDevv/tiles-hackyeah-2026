"""Vendor catalog (org seed, docs/seed-fixes/org.seed.yaml `resources.vendors`) and deterministic
fake CRM contacts (seeded RNG; checksum-valid PESEL / PL IBAN generated at runtime, never committed).
"""

from __future__ import annotations

import random
from typing import Any

from mocks.mock_llm import fakegen

#: vendor id -> {name, approved, host, plans: {plan id: {usd, recurring}}} (seed alignment A-56)
VENDORS: dict[str, dict[str, Any]] = {
    "marketpulse": {
        "name": "MarketPulse Pro",
        "category": "market_data_saas",
        "approved": True,
        "host": "api.marketpulse.example",
        "plans": {
            "mp-pro-monthly": {"usd": 50.00, "recurring": "monthly"},
            "mp-enterprise-annual": {"usd": 4800.00, "recurring": "yearly"},
        },
    },
    "opendata-shop": {
        "name": "OpenData Shop",
        "category": "dataset",
        "approved": True,
        "host": "shop.opendata.example",
        "plans": {"eu-equities-2025-csv": {"usd": 12.00, "recurring": "none"}},
    },
    "gpucloud": {
        "name": "BurstGPU Cloud",
        "category": "compute",
        "approved": True,
        "host": "api.burstgpu.example",
        "plans": {
            "a100-24h-reservation": {"usd": 480.00, "recurring": "none"},
            "a100-cluster-week": {"usd": 1500.00, "recurring": "none"},
        },
    },
    "shady-signals": {
        "name": "Shady Signals Ltd",
        "category": "market_data_saas",
        "approved": False,
        "host": "signals.shady.example",
        "plans": {"alpha-signals": {"usd": 15.00, "recurring": "monthly"}},
    },
}

CITIES = ["Warszawa", "Kraków", "Gdańsk", "Wrocław", "Poznań", "Łódź", "London", "Berlin"]
TIERS = ["retail", "premium", "private-banking", "institutional"]


def plans() -> list[dict[str, Any]]:
    out = []
    for vid, v in VENDORS.items():
        for pid, p in v["plans"].items():
            out.append(
                {
                    "vendor": vid,
                    "vendor_name": v["name"],
                    "approved_vendor": v["approved"],
                    "plan": pid,
                    "amount_usd": p["usd"],
                    "currency": "USD",
                    "recurring": p["recurring"],
                }
            )
    return out


def plan_price(vendor: str, plan: str) -> float | None:
    p = VENDORS.get(vendor, {}).get("plans", {}).get(plan)
    return None if p is None else float(p["usd"])


def contacts(seed: int = 7, n: int = 12) -> list[dict[str, Any]]:
    """Deterministic per seed: same seed -> same contacts (with PII coming BACK from a third party)."""
    rng = random.Random(seed)
    out = []
    for i in range(1, n + 1):
        name = fakegen.person(rng)
        out.append(
            {
                "id": f"C-{1000 + i}",
                "name": name,
                "email": fakegen.email(rng, name, domain="client.example"),
                "phone": fakegen.phone(rng),
                "pesel": fakegen.pesel(rng),
                "iban": fakegen.pl_iban(rng),
                "city": rng.choice(CITIES),
                "tier": rng.choice(TIERS),
                "aum_usd": rng.randint(20, 5000) * 1000,
            }
        )
    return out


__all__ = ["VENDORS", "contacts", "plan_price", "plans"]
