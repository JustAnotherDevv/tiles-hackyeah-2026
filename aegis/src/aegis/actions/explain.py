"""Explainability helpers: ``Decision.meta["explain"]`` builder, masking and path display.

Every action-guard decision explains itself with a one-line reason, structured ``facts``,
the ``checks`` it ran (value vs limit, pass/fail, the policy knob) and the ``levers`` a judge
would edit to change the result. Nothing here ever contains raw PII or secrets.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from aegis.actions import runtime as art

VERB = {
    "allow": "Allowed",
    "log": "Logged",
    "redact": "Redacted",
    "require_approval": "Needs approval",
    "block": "Blocked",
}

_EMAIL_RX = re.compile(r"([A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]*@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
_LONG_DIGITS_RX = re.compile(r"\d[\d \-]{5,}\d")
_SECRETISH_RX = re.compile(
    r"\b(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{28,}\b"
)


def local_mask(text: str, max_len: int = 160) -> str:
    """Fallback masking (used when rt.redactor is unavailable): emails keep their domain,
    long digit runs and secret-looking tokens are hidden."""
    out = _EMAIL_RX.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)
    out = _LONG_DIGITS_RX.sub(lambda m: "*" * min(len(m.group(0)), 8), out)
    out = _SECRETISH_RX.sub("[SECRET]", out)
    return out if len(out) <= max_len else out[: max_len - 1] + "…"


def mask(text: Any, max_len: int = 160) -> str:
    """Irreversible masking for excerpts/titles/payloads (``rt.redactor.mask_for_log``)."""
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    if not s:
        return s
    rt = art.current_rt()
    red = getattr(rt, "redactor", None) if rt is not None else None
    if red is not None:
        try:
            masked = red.mask_for_log(s, max_len=max_len)
            # defence in depth: the local masker also runs over the engine's output
            return local_mask(masked, max_len) if masked else masked
        except Exception:
            pass
    return local_mask(s, max_len)


def mask_email(addr: str) -> str:
    """``client@client-portal.example`` -> ``c***@client-portal.example`` (domain kept)."""
    m = _EMAIL_RX.search(addr or "")
    if not m:
        return mask(addr, 80)
    return f"{m.group(1)}***@{m.group(2)}"


def display_path(path: str | None) -> str:
    """Show the home directory as ``~`` (never leak the local username in reasons)."""
    if not path:
        return ""
    home = os.path.expanduser("~")
    if home and home != "~" and (path == home or path.startswith(home + os.sep)):
        path = "~" + path[len(home) :]
    path = re.sub(r"^/(Users|home)/[^/]+(?=/|$)", "~", path)
    return path


@dataclass
class Explain:
    summary: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)
    route: dict[str, Any] | None = None
    levers: list[str] = field(default_factory=list)

    def check(
        self,
        cid: str,
        label: str,
        value: Any = None,
        limit: Any = None,
        result: str = "pass",
        param: str | None = None,
    ) -> Explain:
        """Record one check: ``result`` in pass | fail | info | skip."""
        self.checks.append(
            {
                "id": cid,
                "label": label,
                "value": value,
                "limit": limit,
                "result": result,
                "param": param,
            }
        )
        return self

    def lever(self, *paths: str) -> Explain:
        for p in paths:
            if p not in self.levers:
                self.levers.append(p)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "facts": self.facts,
            "checks": self.checks,
            "route": self.route,
            "levers": self.levers,
        }


def reason_line(action: str, core: str, *, suffix: str = "") -> str:
    """``"Blocked: pipe-to-shell — ..."``; one line, verdict first."""
    line = f"{VERB.get(action, action)}: {core.strip()}"
    if suffix:
        line = f"{line.rstrip('.')}. {suffix}"
    return " ".join(line.split())


__all__ = ["VERB", "Explain", "display_path", "local_mask", "mask", "mask_email", "reason_line"]
