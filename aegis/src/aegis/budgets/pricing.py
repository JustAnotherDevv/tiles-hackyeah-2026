"""Model / tool pricing from `config/pricing.yaml` (CONTRACTS section 4.6)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from aegis.core.types import Usage

log = logging.getLogger(__name__)

PROVIDER_PREFIXES = ("anthropic/", "ollama/", "openai/", "local/")


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD per 1M tokens (in/out/cache_*) and USD per local compute second."""

    in_: float = 0.0
    out: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    compute_s: float = 0.0

    def as_dict(self, match: str) -> dict[str, Any]:
        return {
            "match": match,
            "in": self.in_,
            "out": self.out,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            "compute_s": self.compute_s,
        }


DEFAULT_MODELS: list[tuple[str, dict[str, float]]] = [
    ("claude-opus-*", {"in": 15.0, "out": 75.0, "cache_read": 1.5, "cache_write": 18.75}),
    ("claude-sonnet-*", {"in": 3.0, "out": 15.0, "cache_read": 0.3, "cache_write": 3.75}),
    ("claude-haiku-*", {"in": 1.0, "out": 5.0, "cache_read": 0.1, "cache_write": 1.25}),
    ("gpt-4.1-mini", {"in": 0.40, "out": 1.60}),
    ("meta-llama/*", {"in": 0.15, "out": 0.40}),
    ("mock-*", {"in": 3.0, "out": 15.0}),
    ("aegis-*", {"compute_s": 0.0002}),
    ("qwen*", {"compute_s": 0.0002}),
    ("hf.co/*", {"compute_s": 0.0002}),
    ("*", {"in": 5.0, "out": 15.0}),
]
DEFAULT_TOOLS: list[tuple[str, float]] = [("web.fetch", 0.002), ("web.fetch_url", 0.002)]
DEFAULT_VERSION = "builtin-2026-10-03"


def _price_from(raw: dict[str, Any]) -> ModelPrice:
    p_in = float(raw.get("in", raw.get("in_", 0.0)) or 0.0)
    cr = raw.get("cache_read")
    cw = raw.get("cache_write")
    return ModelPrice(
        in_=p_in,
        out=float(raw.get("out", 0.0) or 0.0),
        cache_read=float(cr) if cr is not None else round(0.1 * p_in, 10),
        cache_write=float(cw) if cw is not None else round(1.25 * p_in, 10),
        compute_s=float(raw.get("compute_s", 0.0) or 0.0),
    )


def normalize_model(model: str | None) -> str:
    m = (model or "").strip()
    low = m.lower()
    for prefix in PROVIDER_PREFIXES:
        if low.startswith(prefix):
            return m[len(prefix) :]
    return m


@dataclass
class PricingTable:
    version: str = DEFAULT_VERSION
    currency: str = "USD"
    unit: str = "per_1m_tokens"
    models: list[tuple[str, ModelPrice]] = field(default_factory=list)
    tools: list[tuple[str, float]] = field(default_factory=list)
    source: str = "builtin"

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str = "dict") -> PricingTable:
        if not isinstance(data, dict):
            raise ValueError("pricing file must be a mapping")
        models_raw = data.get("models") or {}
        if isinstance(models_raw, dict):
            items = list(models_raw.items())
        else:  # list form [{match: ..., in: ...}]
            items = [(m.get("match", "*"), m) for m in models_raw]
        models = [(str(k), _price_from(v or {})) for k, v in items]
        tools_raw = data.get("tools") or {}
        if isinstance(tools_raw, dict):
            tools = [(str(k), float(v or 0.0)) for k, v in tools_raw.items()]
        else:
            tools = [(str(t.get("match", "*")), float(t.get("usd", 0.0))) for t in tools_raw]
        return cls(
            version=str(data.get("version") or DEFAULT_VERSION),
            currency=str(data.get("currency") or "USD"),
            unit=str(data.get("unit") or "per_1m_tokens"),
            models=models,
            tools=tools,
            source=source,
        )

    @classmethod
    def default(cls) -> PricingTable:
        return cls(
            models=[(g, _price_from(p)) for g, p in DEFAULT_MODELS],
            tools=list(DEFAULT_TOOLS),
        )

    # ------------------------------------------------------------ lookups
    def model_price(self, model: str | None) -> tuple[str, ModelPrice]:
        name = normalize_model(model)
        for glob, price in self.models:
            if glob == "*" or fnmatchcase(name, glob) or fnmatchcase(name.lower(), glob):
                return glob, price
        return "*", ModelPrice(in_=5.0, out=15.0, cache_read=0.5, cache_write=6.25)

    def is_local_priced(self, model: str | None) -> bool:
        _, p = self.model_price(model)
        return p.compute_s > 0 and p.in_ == 0 and p.out == 0

    def price(self, model: str | None, usage: Usage) -> float:
        _, p = self.model_price(model)
        cr = max(0, usage.cache_read_tokens)
        cw = max(0, usage.cache_write_tokens)
        uncached = max(0, usage.input_tokens - cr - cw)
        tokens_usd = (
            uncached * p.in_ + cr * p.cache_read + cw * p.cache_write + usage.output_tokens * p.out
        ) / 1e6
        return round(tokens_usd + max(0.0, usage.compute_s) * p.compute_s, 10)

    def tool_price(self, tool_name: str | None) -> float:
        if not tool_name:
            return 0.0
        for glob, usd in self.tools:
            if fnmatchcase(tool_name, glob):
                return usd
        return 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "currency": self.currency,
            "unit": self.unit,
            "models": [p.as_dict(g) for g, p in self.models],
            "tools": [{"match": g, "usd": usd} for g, usd in self.tools],
        }


def load_pricing(path: str | Path | None) -> PricingTable:
    """Parse the pricing file; raises on a malformed file (callers keep the last good table)."""
    import yaml

    if path is None:
        return PricingTable.default()
    p = Path(path)
    if not p.exists():
        log.warning("pricing file missing path=%s - using built-in contract prices", p)
        return PricingTable.default()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    table = PricingTable.from_dict(data, source=str(p))
    if not table.models:
        raise ValueError("pricing file has no models")
    return table


__all__ = ["ModelPrice", "PricingTable", "load_pricing", "normalize_model"]
