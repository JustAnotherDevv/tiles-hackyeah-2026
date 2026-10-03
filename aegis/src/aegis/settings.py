"""Gateway settings from environment variables (CONTRACTS section 6.5).

Public import surface (CONTRACTS section 3.3): `Settings`, `get_settings()`.

Field names are the env var names lower-cased without the `AEGIS_` prefix. Relative paths are
resolved against the repository root so `python -m aegis` works from any cwd. An optional `.env`
file in the repo root is read too (real environment variables win). `pydantic-settings` is not a
dependency, so `Settings` is a plain pydantic `BaseModel`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_HOST_MAP = (
    "exfil.test=127.0.0.1:8793,paste.test=127.0.0.1:8794,"
    "pay.saas.test=127.0.0.1:8794,crm.saas.test=127.0.0.1:8794"
)

_TRUE = {"1", "true", "yes", "on", "y", "t"}

#: provider keys read without the AEGIS_ prefix
_PLAIN_ENV = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
}


def _read_dotenv(path: Path) -> dict[str, str]:
    """Minimal `.env` parser (KEY=VALUE, `#` comments, optional quotes, `export ` prefix)."""
    out: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            out[key] = value
    return out


class Settings(BaseModel):
    """All gateway settings. Construct directly in tests (`Settings(data_dir=tmp)`)."""

    model_config = ConfigDict(extra="ignore")

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
    # Addendum A-57 additions
    warmup: str = "auto"
    reports_dir: Path = Path("reports")
    semantic_models: str = "horizon-small,minilm-l12-multi,eu-pii-ner,aegis-guard,aegis-judge"
    semantic_ram_mb: int = 2048
    mock_llm_port: int = 8791
    mock_mcp_port: int = 8792
    exfil_sink_port: int = 8793
    mock_saas_port: int = 8794
    # provider credentials (plain env names, no AEGIS_ prefix)
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    gemini_api_key: str | None = None

    def model_post_init(self, __context: Any) -> None:
        for name, value in list(self.__dict__.items()):
            if isinstance(value, Path) and not value.is_absolute():
                object.__setattr__(self, name, (ROOT / value).resolve())

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None, *, dotenv: Path | None = None
    ) -> Settings:
        """Build from `environ` (default `os.environ`) layered over the repo `.env` file."""
        if environ is None:
            env: dict[str, str] = {}
            env.update(_read_dotenv(dotenv or ROOT / ".env"))
            env.update(os.environ)
        else:
            env = dict(environ)
        values: dict[str, Any] = {}
        for name, field in cls.model_fields.items():
            env_name = _PLAIN_ENV.get(name, f"AEGIS_{name.upper()}")
            raw = env.get(env_name)
            if raw is None or raw == "":
                continue
            if field.annotation is bool:
                values[name] = raw.strip().lower() in _TRUE
            else:
                values[name] = raw.strip()
        return cls.model_validate(values)

    # ------------------------------------------------------------------ helpers
    def env(self, name: str | None, default: str | None = None) -> str | None:
        """Read an arbitrary env var (policy `providers.*.api_key_env` / `enabled_if_env`).

        Settings fields win for the known provider keys so tests can inject them.
        """
        if not name:
            return default
        for field, env_name in _PLAIN_ENV.items():
            if env_name == name and getattr(self, field):
                return getattr(self, field)
        value = os.environ.get(name)
        if value is None:
            value = _dotenv_cache().get(name)
        return value if value not in (None, "") else default

    def env_flag(self, name: str | None) -> bool:
        """Truthiness of an env var (empty / 0 / false / no / off = False)."""
        value = self.env(name)
        return bool(value) and value.strip().lower() not in {"0", "false", "no", "off"}

    @property
    def public_url(self) -> str:
        """Base URL used in approval links and messages ("http://127.0.0.1:8787")."""
        host = self.host if self.host not in {"0.0.0.0", "::", ""} else "127.0.0.1"
        port = self.port or 8787
        return f"http://{host}:{port}"

    @property
    def semantic_off(self) -> bool:
        return self.semantic.strip().lower() == "off"

    @property
    def root(self) -> Path:
        return ROOT


@lru_cache(maxsize=1)
def _dotenv_cache() -> dict[str, str]:
    return _read_dotenv(ROOT / ".env")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings (cached). Tests pass explicit `Settings` to `create_app` instead."""
    return Settings.from_env()


__all__ = ["DEFAULT_HOST_MAP", "ROOT", "Settings", "get_settings"]
