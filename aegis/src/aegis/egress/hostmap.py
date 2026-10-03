"""Logical host -> local mock mapping for `/egress` (AEGIS_HOST_MAP, Addendum A-57).

`exfil.test=127.0.0.1:8793,crm.saas.test=127.0.0.1:8794` -> requests to `https://exfil.test/p`
connect to `http://127.0.0.1:8793/p` with `Host: exfil.test`. Resolution happens only
**after** policy evaluation. Unmapped `.test` hosts are unresolvable (fail closed)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

log = logging.getLogger(__name__)

DEFAULT_HOST_MAP = ("exfil.test=127.0.0.1:8793,paste.test=127.0.0.1:8794,"
                    "pay.saas.test=127.0.0.1:8794,crm.saas.test=127.0.0.1:8794")
RESERVED_SUFFIXES = (".test", ".invalid", ".localhost.test")


class UnresolvableHost(Exception):
    pass


@dataclass(frozen=True)
class Target:
    connect_url: str
    host_header: str | None  # logical host (Host header) when mapped
    mapped: bool
    host: str


class HostMap:
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = {k.lower().strip(): v.strip() for k, v in mapping.items() if k and v}

    @classmethod
    def parse(cls, spec: str | None) -> HostMap:
        out: dict[str, str] = {}
        for item in (spec or "").split(","):
            if "=" not in item:
                continue
            host, _, target = item.partition("=")
            out[host.strip()] = target.strip()
        return cls(out)

    @classmethod
    def from_settings(cls, settings: object | None = None) -> HostMap:
        spec = None
        try:
            if settings is None:
                from aegis.settings import get_settings

                settings = get_settings()
            spec = getattr(settings, "host_map", None)
        except Exception:
            spec = None
        if spec is None:
            log.warning("settings.host_map missing; using default host map")
            spec = DEFAULT_HOST_MAP
        return cls.parse(spec)

    def __len__(self) -> int:
        return len(self.mapping)

    def resolve(self, url: str) -> Target:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if not host:
            raise UnresolvableHost("missing host")
        target = self.mapping.get(host)
        if target is None:
            if host.endswith(RESERVED_SUFFIXES):
                raise UnresolvableHost(f"unresolvable test host {host}")
            return Target(connect_url=url, host_header=None, mapped=False, host=host)
        netloc = target.split("://", 1)[-1]
        scheme = "https" if target.startswith("https://") else "http"
        connect = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
        host_header = host if parts.port is None else f"{host}:{parts.port}"
        return Target(connect_url=connect, host_header=host_header, mapped=True, host=host)
