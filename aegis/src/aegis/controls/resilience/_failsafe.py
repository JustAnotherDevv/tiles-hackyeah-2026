"""Fail-mode-aware decision for a control's own internal error (ASI08).

Controls used to catch ``Exception`` and return ``allow`` + ``degraded`` regardless of the
configured ``fail_mode`` - the pipeline never saw the error, so ``fail_mode: closed`` was not
honoured. ``internal_error_decision`` reproduces the pipeline's ``_fail_decision`` semantics:

* ``fail_mode: closed``                -> ``block`` (degraded), reason "<ID> internal error (fail-closed)"
* ``open`` / ``deterministic_only``    -> ``allow`` (degraded), reason "... (fail-open)"

``meta`` always carries ``internal_error: True``, the error class/message (truncated, never the
inspected content) and the effective ``fail_mode`` so the decision trace explains itself.
A cfg without a ``fail_mode`` attribute (bare test doubles) is treated as fail-open, exactly as
before; a real ``ControlConfig`` defaults to ``closed``.
"""

from __future__ import annotations

from typing import Any

from aegis.core.types import Decision

ERROR_MAX = 200


def fail_mode_of(cfg: Any) -> str | None:
    return getattr(cfg, "fail_mode", None)


def is_fail_closed(cfg: Any) -> bool:
    return fail_mode_of(cfg) == "closed"


def internal_error_decision(
    control_id: str,
    cfg: Any,
    exc: BaseException | str,
    *,
    what: str = "internal error",
    closed_action: str = "block",
) -> Decision:
    """Decision for ``control_id`` failing internally; honours ``cfg.fail_mode``."""
    err = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    fm = fail_mode_of(cfg)
    closed = fm == "closed"
    sev = getattr(cfg, "severity", None) or "medium"
    return Decision(
        action=closed_action if closed else "allow",  # type: ignore[arg-type]
        control_id=control_id,
        reason=f"{control_id} {what} ({'fail-closed' if closed else 'fail-open'})",
        severity=sev,
        degraded=True,
        meta={"internal_error": True, "error": err[:ERROR_MAX], "fail_mode": fm or "unset"},
    )
