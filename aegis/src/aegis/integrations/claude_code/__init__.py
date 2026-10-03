"""Claude Code integration: hook-event mapping for `POST /v1/hooks/claude-code`.

Owner: claude-code-integration (docs/CONTRACTS.md section 1.2, plan docs/plan/12-*.md).
Public names: `handle_hook`, `HOOK_EVENTS`, `BLOCKING_EVENTS`. No import-time side effects.
Control GOV-06 lives in `gov06.py` (`CONTROLS`, discovered via Addendum A-15).
"""

from __future__ import annotations

from .handler import handle_hook, handle_hook_ex, hook_status
from .schema import BLOCKING_EVENTS, HOOK_EVENTS

__all__ = ["BLOCKING_EVENTS", "HOOK_EVENTS", "handle_hook", "handle_hook_ex", "hook_status"]
