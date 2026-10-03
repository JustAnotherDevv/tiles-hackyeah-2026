"""Gateway settings from environment variables (CONTRACTS section 6.5).

SCAFFOLD STUB - owned by core-gateway, safe to extend/replace. Field names are the env var
names lower-cased without the `AEGIS_` prefix (public import surface, CONTRACTS section 3.3).
Relative paths are resolved against the repository root so `python -m aegis` works from any cwd.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_HOST_MAP = (
    "exfil.test=127.0.0.1:8793,paste.test=127.0.0.1:8794,"
    "pay.saas.test=127.0.0.1:8794,crm.saas.test=127.0.0.1:8794"
)


class Settings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787
    policy: Path = Path("config/policy.yaml")
    org_seed: Path = Path("config/org.seed.yaml")
    pricing: Path = Path("config/pricing.yaml")
    data_dir: Path = Path("data")
    models_dir: Path = Path("models")
    hmac_key: str | None = None
    feed_url: str = "http://127.0.0.1:8790"
    feed_pubkey: Path = Path("config/feeds/feed_pubkey.b64")
    ollama_url: str = "http://127.0.0.1:11434"
    semantic: str = "auto"
    demo_mode: bool = True
    default_viewer: str | None = None
    admin_token: str | None = None
    ui_dist: Path = Path("web/dist")
    host_map: str = DEFAULT_HOST_MAP
    vault_secret: str | None = None
    log_level: str = "INFO"
    log_json: bool = False
    access_log: bool = False
    test_mode: bool = False
    live_url: str | None = None

    def model_post_init(self, __context: Any) -> None:
        for name, value in list(self.__dict__.items()):
            if isinstance(value, Path) and not value.is_absolute():
                object.__setattr__(self, name, ROOT / value)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        values: dict[str, Any] = {}
        for name, field in cls.model_fields.items():
            raw = env.get(f"AEGIS_{name.upper()}")
            if raw is None or raw == "":
                continue
            if field.annotation is bool:
                values[name] = raw.strip().lower() in {"1", "true", "yes", "on"}
            else:
                values[name] = raw
        return cls.model_validate(values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
