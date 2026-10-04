"""Token / compute usage extracted from streams (for the budget ledger)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

__all__ = ["Usage"]


@dataclass(slots=True)
class Usage:
    provider: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    # local models (Ollama reports nanoseconds)
    total_duration_ns: int | None = None
    load_duration_ns: int | None = None
    prompt_eval_duration_ns: int | None = None
    eval_duration_ns: int | None = None
    #: characters of model output seen (text + thinking + tool JSON), for estimates
    output_chars: int = 0
    #: True once the upstream reported final counts (message_delta / usage chunk / done)
    exact: bool = False

    @property
    def estimated_output_tokens(self) -> int:
        """Exact count when known, else ~4 chars/token over everything streamed."""
        if self.exact and self.output_tokens is not None:
            return self.output_tokens
        return max((self.output_chars + 3) // 4, self.output_tokens or 0)

    @property
    def compute_seconds(self) -> float | None:
        """Wall-clock model time for local models (budgeted as compute-seconds)."""
        if self.total_duration_ns is None:
            return None
        return self.total_duration_ns / 1e9

    def to_dict(self) -> dict:
        d = asdict(self)
        d["estimated_output_tokens"] = self.estimated_output_tokens
        d["compute_seconds"] = self.compute_seconds
        return d
