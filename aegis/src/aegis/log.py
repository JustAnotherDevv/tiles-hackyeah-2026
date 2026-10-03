"""Logging setup (CONTRACTS section 7.4): `setup_logging()`, `SecretScrubFilter`.

Format `%(asctime)s %(levelname)-5s %(name)s | %(message)s` or JSON lines (`AEGIS_LOG_JSON=1`).
`SecretScrubFilter` masks credential-shaped strings in every record (defence in depth; code never
logs headers or bodies anyway).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

FORMAT = "%(asctime)s %(levelname)-5s %(name)s | %(message)s"

_SCRUB_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), "sk-ant-***"),
    (re.compile(r"(?i)bearer\s+\S+"), "Bearer ***"),
    (re.compile(r"aegis_[A-Za-z0-9_]+"), "aegis_***"),
    (re.compile(r"(?i)(x-api-key\s*[:=]\s*)\S+"), r"\1***"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}"), "sk-***"),
]


def scrub(text: str) -> str:
    for pattern, repl in _SCRUB_RULES:
        text = pattern.sub(repl, text)
    return text


class SecretScrubFilter(logging.Filter):
    """Masks API keys / bearer tokens in the formatted message (msg % args)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        cleaned = scrub(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = scrub(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


class _ScrubbingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return scrub(super().format(record))


_configured = False


def setup_logging(
    level: str | int = "INFO", json_lines: bool = False, access_log: bool = False
) -> None:
    """Configure the `aegis` root handler once (idempotent; later calls only adjust levels)."""
    global _configured
    lvl = logging.getLevelName(level.upper()) if isinstance(level, str) else level
    if not isinstance(lvl, int):
        lvl = logging.INFO
    root = logging.getLogger()
    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter() if json_lines else _ScrubbingFormatter(FORMAT))
        handler.addFilter(SecretScrubFilter())
        handler.set_name("aegis")
        # don't stack handlers if pytest / uvicorn already installed some
        if not any(h.get_name() == "aegis" for h in root.handlers):
            root.addHandler(handler)
        _configured = True
    if root.level == logging.NOTSET or root.level > lvl:
        root.setLevel(lvl)
    logging.getLogger("aegis").setLevel(lvl)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO if access_log else logging.WARNING)
    for noisy in ("httpx", "httpcore", "watchfiles", "sse_starlette"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


__all__ = ["FORMAT", "SecretScrubFilter", "scrub", "setup_logging"]
