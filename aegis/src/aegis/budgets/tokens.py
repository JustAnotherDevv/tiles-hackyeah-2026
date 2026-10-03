"""Token estimation (public import surface, CONTRACTS section 3.3).

`estimate_tokens` is a cheap chars-per-token heuristic (chars/4; Claude models chars/3.5). Budgets
reserve on the estimate and reconcile on settle with the provider-reported usage.
"""

from __future__ import annotations

import math

CHARS_PER_TOKEN = 4.0
CLAUDE_CHARS_PER_TOKEN = 3.5


def estimate_tokens(text: str, model: str | None = None) -> int:
    """Estimated token count of `text` (ceil; at least 1 for non-empty text)."""
    if not text:
        return 0
    ratio = CLAUDE_CHARS_PER_TOKEN if model and "claude" in model.lower() else CHARS_PER_TOKEN
    return max(1, math.ceil(len(text) / ratio))


__all__ = ["estimate_tokens"]
