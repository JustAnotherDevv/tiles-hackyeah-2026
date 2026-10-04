"""Model routing: requested model + inbound wire -> provider route (CONTRACTS sections 4.2, 3.4).

Owner: core-gateway (bundle B02).

`resolve_route(model, wire, snap, settings)` walks `models.routes` (first match wins) and returns a
`Route` with the provider config, upstream base URL, destination classification and credentials.
Rules:

* a route matches when its glob matches the model, its optional `wire` equals the inbound wire,
  the provider exists, its `enabled_if_env` (if any) is set, and the **provider wire equals the
  inbound wire** (cross-wire translation is out of scope: such routes are skipped);
* models ending in ``:cloud`` are always classified ``remote`` (Ollama cloud models leave the box);
* built-in providers/routes (mock LLM on :8791, Ollama on `settings.ollama_url`, Anthropic
  passthrough) are used when the policy defines none, and as a last-resort fallback when no
  policy route matches, so the gateway proxies with the Null policy too.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from aegis.core.policy_schema import ModelRoute, ProviderConfig
from aegis.core.types import Destination

log = logging.getLogger(__name__)

__all__ = [
    "DEST_RANK",
    "Route",
    "builtin_providers",
    "builtin_routes",
    "env_value",
    "providers_for",
    "resolve_route",
]

MOCK_LLM_URL = "http://127.0.0.1:8791"
DEST_RANK: dict[str, int] = {"local": 0, "remote": 1, "third_party": 2}


def env_value(settings: Any, name: str | None) -> str | None:
    """Read an arbitrary env var (provider `api_key_env` / `enabled_if_env`)."""
    if not name:
        return None
    getter = getattr(settings, "env", None)
    if callable(getter):
        try:
            v = getter(name)
            if v:
                return str(v)
        except Exception:  # pragma: no cover - defensive
            pass
    # Settings fields like `anthropic_api_key` mirror well-known env vars.
    attr = name.lower()
    v = getattr(settings, attr, None) if settings is not None else None
    if isinstance(v, str) and v:
        return v
    return os.environ.get(name) or None


def builtin_providers(settings: Any = None) -> dict[str, ProviderConfig]:
    ollama = (getattr(settings, "ollama_url", None) or "http://127.0.0.1:11434").rstrip("/")
    return {
        "anthropic": ProviderConfig(
            wire="anthropic", base_url="https://api.anthropic.com", destination="remote",
            passthrough_auth=True, api_key_env="ANTHROPIC_API_KEY",
        ),
        "openai": ProviderConfig(
            wire="openai", base_url="https://api.openai.com/v1", destination="remote",
            api_key_env="OPENAI_API_KEY", enabled_if_env="OPENAI_API_KEY",
        ),
        "openrouter": ProviderConfig(
            wire="openai", base_url="https://openrouter.ai/api/v1", destination="remote",
            api_key_env="OPENROUTER_API_KEY", enabled_if_env="OPENROUTER_API_KEY",
        ),
        "ollama": ProviderConfig(wire="ollama", base_url=ollama, destination="local", timeout_s=300),
        "ollama-openai": ProviderConfig(
            wire="openai", base_url=f"{ollama}/v1", destination="local", timeout_s=300
        ),
        "ollama-anthropic": ProviderConfig(
            wire="anthropic", base_url=ollama, destination="local", timeout_s=300
        ),
        "mock-anthropic": ProviderConfig(
            wire="anthropic", base_url=MOCK_LLM_URL, destination="remote", timeout_s=30
        ),
        "mock-openai": ProviderConfig(
            wire="openai", base_url=f"{MOCK_LLM_URL}/v1", destination="remote", timeout_s=30
        ),
    }


def builtin_routes() -> list[ModelRoute]:
    return [
        ModelRoute(match="mock-*", provider="mock-anthropic", wire="anthropic"),
        ModelRoute(match="mock-*", provider="mock-openai", wire="openai"),
        ModelRoute(match="claude-*", provider="anthropic", wire="anthropic"),
        ModelRoute(match="gpt-*", provider="openai", wire="openai"),
        ModelRoute(match="meta-llama/*", provider="openrouter", wire="openai"),
        ModelRoute(match="*", provider="ollama-openai", wire="openai"),
        ModelRoute(match="*", provider="ollama", wire="ollama"),
        ModelRoute(match="*", provider="ollama-anthropic", wire="anthropic"),
    ]


@dataclass(slots=True)
class Route:
    provider: str
    cfg: ProviderConfig
    wire: str
    url_base: str
    destination: Destination
    model: str
    api_key: str | None = None
    rule: str | None = None  # the glob that matched (for logs / wire view)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def dest_class(self) -> str:
        return self.destination.dest_class

    @property
    def timeout_s(self) -> float:
        return float(self.cfg.timeout_s or 120.0)

    @property
    def redact_system(self) -> bool:
        extra = getattr(self.cfg, "model_extra", None) or {}
        return bool(extra.get("redact_system", False))

    def url(self, op: str = "", query: str = "") -> str:
        """Upstream URL for an operation.

        anthropic: op "messages" | "count_tokens"; openai: "chat" | "models";
        ollama: "chat" | "generate" | any native op ("tags", "pull", ...).
        """
        base = self.url_base.rstrip("/")
        if self.wire == "anthropic":
            path = "/v1/messages/count_tokens" if op == "count_tokens" else "/v1/messages"
        elif self.wire == "openai":
            path = "/models" if op == "models" else "/chat/completions"
        else:
            path = f"/api/{(op or 'chat').lstrip('/')}"
            if base.endswith("/api"):
                base = base[: -len("/api")]
        url = base + path
        if query:
            url += "?" + query.lstrip("?")
        return url


def _glob(pattern: str, value: str | None) -> bool:
    if value is None:
        return pattern == "*"
    return fnmatch.fnmatchcase(value, pattern)


def providers_for(snap: Any, settings: Any = None) -> dict[str, ProviderConfig]:
    """Effective providers: built-ins overlaid with the policy's `providers` section."""
    out = builtin_providers(settings)
    doc = getattr(snap, "doc", None)
    for name, cfg in (getattr(doc, "providers", None) or {}).items():
        out[name] = cfg
    return out


def _policy_routes(snap: Any) -> list[ModelRoute]:
    doc = getattr(snap, "doc", None)
    models = getattr(doc, "models", None)
    return list(getattr(models, "routes", None) or [])


def _build(
    route: ModelRoute, cfg: ProviderConfig, model: str, settings: Any
) -> Route:
    base = cfg.base_url.rstrip("/")
    if cfg.wire == "ollama" or (cfg.destination == "local" and "11434" in base):
        # Ollama defaults follow AEGIS_OLLAMA_URL when the policy uses the stock address
        ollama = (getattr(settings, "ollama_url", None) or "").rstrip("/")
        if ollama and base.startswith("http://127.0.0.1:11434"):
            base = ollama + base[len("http://127.0.0.1:11434") :]
    parsed = urlparse(base)
    dest_class = cfg.destination
    if model.endswith(":cloud"):
        dest_class = "remote"
    destination = Destination(
        name=route.provider,
        dest_class=dest_class,
        provider=route.provider,
        host=parsed.hostname,
        url=base,
    )
    return Route(
        provider=route.provider,
        cfg=cfg,
        wire=cfg.wire,
        url_base=base,
        destination=destination,
        model=model,
        api_key=env_value(settings, cfg.api_key_env),
        rule=route.match,
    )


def _first_match(
    routes: list[ModelRoute],
    providers: dict[str, ProviderConfig],
    model: str,
    wire: str,
    settings: Any,
    *,
    provider: str | None = None,
) -> Route | None:
    for r in routes:
        if provider is not None and r.provider != provider:
            continue
        if not _glob(r.match, model):
            continue
        if r.wire is not None and r.wire != wire:
            continue
        cfg = providers.get(r.provider)
        if cfg is None:
            log.debug("route skipped: unknown provider=%s", r.provider)
            continue
        if cfg.wire != wire:
            continue  # no cross-wire translation
        if cfg.enabled_if_env and not env_value(settings, cfg.enabled_if_env):
            continue
        return _build(r, cfg, model, settings)
    return None


def resolve_route(
    model: str | None,
    wire: str,
    snap: Any = None,
    settings: Any = None,
    *,
    provider: str | None = None,
) -> Route | None:
    """Resolve the upstream for `model` arriving on `wire`; None when nothing can serve it.

    `provider` pins the provider (route mutation ``path="provider"`` or playground); when the
    pinned provider has no matching route entry it is used directly if its wire fits.
    """
    if not model:
        return None
    providers = providers_for(snap, settings)
    routes = _policy_routes(snap)
    found = _first_match(routes or builtin_routes(), providers, model, wire, settings,
                         provider=provider)
    if found is None and routes:
        found = _first_match(builtin_routes(), providers, model, wire, settings,
                             provider=provider)
    if found is None and provider is not None:
        cfg = providers.get(provider)
        if cfg is not None and cfg.wire == wire:
            found = _build(ModelRoute(match="*", provider=provider), cfg, model, settings)
    return found
