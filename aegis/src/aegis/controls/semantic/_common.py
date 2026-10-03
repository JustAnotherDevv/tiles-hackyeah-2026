"""Shared helpers for INJ-03 / CUS-01 (leading "_" = skipped by control discovery).

- ``engine()``: ``rt.semantic`` via ``aegis.core.runtime.get_runtime()``; before startup (unit
  tests, scripts) a process-local heuristic engine (``AEGIS_SEMANTIC=off`` semantics).
- ``call_engine()``: calls an engine method with the A-44 kw-only extensions and degrades to the
  frozen positional signature (e.g. ``NullSemantic``) on ``TypeError``.
- ``mask()``: ``rt.redactor.mask_for_log`` with a local fallback (never raw content).
- text selection (latest user turn), profile resolution, agent purpose lookup, param models.
"""

from __future__ import annotations

import logging
import re
from fnmatch import fnmatchcase
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aegis.core.types import ACTION_PRECEDENCE, Interaction, RequestContext, TextSegment

log = logging.getLogger(__name__)

PROFILES = ("permissive", "balanced", "strict", "paranoid")
_LOCAL_ENGINE: Any = None
_WARNED: set[tuple[str, str]] = set()


# ---------------------------------------------------------------- runtime access
def runtime() -> Any:
    try:
        from aegis.core.runtime import get_runtime

        return get_runtime()
    except Exception:
        return None


def engine() -> Any:
    rt = runtime()
    sem = getattr(rt, "semantic", None) if rt is not None else None
    if sem is not None:
        return sem
    global _LOCAL_ENGINE
    if _LOCAL_ENGINE is None:  # TODO(integration): only used before the Runtime exists
        from aegis.semantic.config import SemanticConfig
        from aegis.semantic.engine import SemanticModelEngine

        _LOCAL_ENGINE = SemanticModelEngine(None, config=SemanticConfig(mode="off", test_mode=True))
    return _LOCAL_ENGINE


async def call_engine(name: str, *args: Any, **kw: Any) -> Any:
    eng = engine()
    fn = getattr(eng, name, None)
    if fn is None:
        return None
    try:
        return await fn(*args, **kw)
    except TypeError:
        return await fn(*args)


_DIGITS = re.compile(r"\d")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def mask(text: str, max_len: int = 120) -> str:
    rt = runtime()
    red = getattr(rt, "redactor", None) if rt is not None else None
    if red is not None:
        try:
            return str(red.mask_for_log(text, max_len))
        except Exception:
            pass
    out = _DIGITS.sub("#", _EMAIL.sub("[EMAIL]", text or ""))
    return out if len(out) <= max_len else out[: max_len - 1] + "…"


# ---------------------------------------------------------------- policy helpers
def profile_of(ctx: RequestContext) -> str:
    snap = getattr(ctx, "policy", None)
    doc = getattr(snap, "doc", None)
    prof = getattr(doc, "profile", None)
    return str(prof) if prof in PROFILES else "balanced"


def resolve(value: Any, profile: str, default: Any = None) -> Any:
    """Scalar, or a ``{permissive|balanced|strict|paranoid: value}`` map resolved by profile."""
    if isinstance(value, dict) and value and set(value) <= set(PROFILES) | {"default"}:
        if profile in value:
            return value[profile]
        return value.get("default", default)
    return default if value is None else value


def max_action(actions: list[str]) -> str:
    best = "allow"
    for a in actions:
        if ACTION_PRECEDENCE.get(a, -1) > ACTION_PRECEDENCE[best]:
            best = a
    return best


def valid_action(a: Any, default: str) -> str:
    return a if isinstance(a, str) and a in ACTION_PRECEDENCE else default


def warn_unknown(control_id: str, model: BaseModel) -> None:
    for key in model.model_extra or {}:
        if (control_id, key) not in _WARNED:
            _WARNED.add((control_id, key))
            log.warning("unknown param ignored control=%s key=%s", control_id, key)


def glob_match(pattern: str, value: str | None) -> bool:
    try:
        from aegis.core.paths import glob_match as _gm

        return bool(_gm(pattern, value))
    except Exception:
        return value is not None and fnmatchcase(value, pattern)


# ---------------------------------------------------------------- text selection
_MSG_IDX = re.compile(r"messages\[(\d+)\]")
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def strip_harness(text: str) -> str:
    """Drop Claude Code ``<system-reminder>`` harness blocks (A-45)."""
    return _REMINDER.sub(" ", text or "").strip()


def _msg_index(seg: TextSegment) -> int | None:
    m = _MSG_IDX.search(seg.path or "")
    return int(m.group(1)) if m else None


def user_text(interaction: Interaction, *, latest_only: bool) -> str | None:
    """User text of a request. ``latest_only``: only the newest user turn; None when that turn
    carries no user text (agent-loop turns that only hold tool_result blocks)."""
    segs = interaction.segments
    users = [s for s in segs if s.role == "user" and s.trusted]
    if not latest_only:
        txt = "\n".join(strip_harness(s.text) for s in users)
        return txt.strip() or None
    turns = [
        (i, s)
        for s in segs
        if s.role in ("user", "tool_result")
        if (i := _msg_index(s)) is not None
    ]
    if turns:
        last = max(i for i, _ in turns)
        latest = [s for i, s in turns if i == last and s.role == "user" and s.trusted]
        if not latest:
            return None
        txt = "\n".join(strip_harness(s.text) for s in latest)
        return txt.strip() or None
    if users:
        return strip_harness(users[-1].text) or None
    return None


def assistant_text(interaction: Interaction) -> str | None:
    txt = "\n".join(s.text for s in interaction.segments if s.role == "assistant")
    return txt.strip() or None


# ---------------------------------------------------------------- params
DEFAULT_CATEGORY_ACTIONS: dict[str, str] = {
    "Violent": "block",
    "Non-violent Illegal Acts": "block",
    "Sexual Content or Sexual Acts": "block",
    "Suicide & Self-Harm": "block",
    "Jailbreak": "log",
    "PII": "log",
    "Unethical Acts": "log",
    "Politically Sensitive Topics": "log",
    "Copyright Violation": "log",
}

DEFAULT_CALIBRATION: dict[str, list[float]] = {
    "minilm-l12-multi": [0.10, 0.46],
    "heuristic": [0.02, 0.18],
}


class AdherenceParams(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: Any = Field(
        default_factory=lambda: {
            "permissive": False,
            "balanced": True,
            "strict": True,
            "paranoid": True,
        }
    )
    on_low: Any = Field(
        default_factory=lambda: {
            "permissive": "log",
            "balanced": "log",
            "strict": "block",
            "paranoid": "block",
        }
    )
    min_chars: int = 20
    calibration: dict[str, list[float]] = Field(default_factory=lambda: dict(DEFAULT_CALIBRATION))
    purposes: dict[str, str] = Field(default_factory=dict)  # agent-id glob -> declared purpose


class Inj03Params(BaseModel):
    model_config = ConfigDict(extra="allow")

    check_input: Any = True
    check_output: Any = Field(
        default_factory=lambda: {
            "permissive": False,
            "balanced": True,
            "strict": True,
            "paranoid": True,
        }
    )
    max_chars: int = 6000
    controversial_action: str = "log"
    category_actions: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_CATEGORY_ACTIONS))
    adherence: AdherenceParams = Field(default_factory=AdherenceParams)
    # aliases used by docs/seed-fixes/policy.yaml
    purpose: str | None = None  # global purpose for agents without their own
    off_topic_action: str | None = None  # alias of adherence.on_low


class CustomRule(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = "rule"
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)
    deny_terms: list[str] = Field(default_factory=list)
    text: str | None = None  # natural-language rule (judge leg) when it has no keywords
    action: str | None = None
    destinations: list[str] | None = None
    surfaces: list[str] | None = None
    threshold: float | None = None

    @property
    def terms(self) -> list[str]:
        return [t for t in [*self.keywords, *self.deny_terms] if t and t.strip()]


class Cus01Params(BaseModel):
    model_config = ConfigDict(extra="allow")

    rules: list[CustomRule] = Field(default_factory=list)
    deny_terms: list[str] = Field(default_factory=list)  # legacy -> rule "deny-terms"
    destinations: list[str] = Field(default_factory=lambda: ["remote", "third_party"])
    case_insensitive: bool = True
    fold_diacritics: bool = True
    whole_word: bool = True
    semantic_leg: bool = True
    max_nl_rules: int = 3

    def all_rules(self) -> list[CustomRule]:
        rules = list(self.rules)
        if self.deny_terms:
            rules.append(CustomRule(id="deny-terms", keywords=list(self.deny_terms)))
        return rules
