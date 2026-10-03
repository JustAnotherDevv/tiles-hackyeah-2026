"""Shared transformer machinery: options, report, termination, fail-closed."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter_ns
from typing import Any, Literal

from .channel import TextChannel
from .placeholders import Vault
from .scanner import Finding, LeakScanner
from .usage import Usage

__all__ = ["StreamOptions", "StreamReport", "Termination", "StreamTransformer"]

log = logging.getLogger("aegis.stream")


@dataclass(slots=True)
class StreamOptions:
    """Per-request knobs (build one per request from the policy snapshot)."""

    #: session vault; ``None`` disables rehydration (e.g. destination is remote)
    vault: Vault | None = None
    #: output leak scanner; ``None`` disables scanning
    scanner: LeakScanner | None = None
    rehydrate_text: bool = True
    #: rehydrate tool-call arguments (True only when the tools run locally / T0)
    rehydrate_tool_input: bool = True
    #: "buffer": hold each tool call until complete, then scan+rehydrate it whole
    #: (safe termination: an unfinished tool call is never shown). "stream": forward
    #: arguments incrementally (JSON-aware hold-back; JSON is auto-closed on stop).
    tool_input_mode: Literal["buffer", "stream"] = "buffer"
    max_holdback: int = 512
    #: graceful stop when the estimated output tokens exceed this
    output_token_cap: int | None = None
    #: called after each output delta with the running usage; return a reason to stop
    budget_guard: Callable[[Usage], str | None] | None = None
    notice_template: str = "\n\n[aegis] Response stopped by policy {control}: {reason}"
    #: upstream EOF without a proper end: "error" -> emit a protocol error event
    #: (clients retry), "close" -> graceful synthetic end, "passthrough" -> just end
    on_truncated_upstream: Literal["error", "close", "passthrough"] = "error"
    on_finding: Callable[[Finding], None] | None = None
    #: internal exception -> graceful termination instead of raising
    fail_closed: bool = True


@dataclass(slots=True)
class Termination:
    reason: str
    control: str
    finding: Finding | None = None

    def to_dict(self) -> dict:
        return {
            "reason": self.reason,
            "control": self.control,
            "finding": self.finding.to_dict() if self.finding else None,
        }


@dataclass(slots=True)
class StreamReport:
    protocol: str
    usage: Usage
    findings: list[Finding] = field(default_factory=list)
    rehydrated: dict[str, int] = field(default_factory=lambda: {"text": 0, "tool_input": 0})
    termination: Termination | None = None
    upstream_complete: bool = False
    upstream_truncated: bool = False
    upstream_error: Any = None
    client_disconnected: bool = False
    internal_error: str | None = None
    chunks_in: int = 0
    events_in: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    cpu_ns: int = 0

    @property
    def overhead_us_per_chunk(self) -> float:
        return self.cpu_ns / 1000 / self.chunks_in if self.chunks_in else 0.0

    def to_dict(self) -> dict:
        return {
            "protocol": self.protocol,
            "usage": self.usage.to_dict(),
            "findings": [f.to_dict() for f in self.findings],
            "rehydrated": dict(self.rehydrated),
            "termination": self.termination.to_dict() if self.termination else None,
            "upstream_complete": self.upstream_complete,
            "upstream_truncated": self.upstream_truncated,
            "upstream_error": self.upstream_error,
            "client_disconnected": self.client_disconnected,
            "internal_error": self.internal_error,
            "chunks_in": self.chunks_in,
            "events_in": self.events_in,
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "cpu_ms": round(self.cpu_ns / 1e6, 3),
            "overhead_us_per_chunk": round(self.overhead_us_per_chunk, 2),
        }



class StreamTransformer:
    """Sans-IO base: ``feed(bytes) -> bytes``, ``close() -> bytes``, ``abort() -> bytes``.

    Subclasses implement ``_feed``, ``_close`` and ``_terminate`` for their
    wire protocol.  All public entry points are timed (``report.cpu_ns``) and
    fail closed: an internal exception turns into a graceful, protocol-valid
    termination instead of an unscanned passthrough or a broken stream.
    """

    protocol = "base"
    media_type = "application/octet-stream"

    def __init__(self, options: StreamOptions | None = None) -> None:
        self.options = options or StreamOptions()
        self.report = StreamReport(protocol=self.protocol, usage=Usage(provider=self.protocol))
        self._finished = False

    # ------------------------------------------------------------- public
    @property
    def finished(self) -> bool:
        """True once the client-facing stream is complete (stop reading upstream)."""
        return self._finished

    def feed(self, chunk: bytes) -> bytes:
        if self._finished or not chunk:
            return b""
        t0 = perf_counter_ns()
        rep = self.report
        rep.chunks_in += 1
        rep.bytes_in += len(chunk)
        try:
            out = self._feed(chunk)
        except Exception as exc:  # fail closed
            out = self._fail(exc)
        rep.cpu_ns += perf_counter_ns() - t0
        rep.bytes_out += len(out)
        return out

    def close(self) -> bytes:
        """Upstream reached EOF."""
        if self._finished:
            return b""
        t0 = perf_counter_ns()
        try:
            out = self._close()
        except Exception as exc:
            out = self._fail(exc)
        self._finished = True
        self.report.cpu_ns += perf_counter_ns() - t0
        self.report.bytes_out += len(out)
        return out

    def abort(self, reason: str, control: str = "KILL-SWITCH") -> bytes:
        """Stop gracefully now (kill switch, budget, client policy...)."""
        if self._finished:
            return b""
        try:
            out = self._terminate_bytes(Termination(reason, control))
        except Exception as exc:
            out = self._fail(exc)
        self.report.bytes_out += len(out)
        return out

    def keepalive(self) -> bytes:
        """Protocol-valid no-op to send while output is being held back."""
        return b""

    # ---------------------------------------------------- sink (channels)
    def on_finding(self, finding: Finding) -> None:
        self.report.findings.append(finding)
        cb = self.options.on_finding
        if cb is not None:
            try:
                cb(finding)
            except Exception:  # never let an audit hook break the stream
                log.exception("on_finding callback failed")

    def on_rehydrate(self, kind: str, count: int) -> None:
        self.report.rehydrated[kind] = self.report.rehydrated.get(kind, 0) + count

    # ------------------------------------------------------------ helpers
    def _channel(self, name: str, *, kind: str, json_mode: bool) -> TextChannel:
        o = self.options
        rehydrate = o.rehydrate_text if kind == "text" else o.rehydrate_tool_input
        return TextChannel(
            name,
            kind=kind,
            vault=o.vault if rehydrate else None,
            scanner=o.scanner,
            json_mode=json_mode,
            max_holdback=o.max_holdback,
            sink=self,
        )

    @property
    def _tools_processed(self) -> bool:
        o = self.options
        return o.scanner is not None or (o.vault is not None and o.rehydrate_tool_input)

    def _leak_termination(self, f: Finding) -> Termination:
        control = self.options.scanner.control if self.options.scanner else "OUT-LEAK"
        return Termination(f"model output contained {f.type}", control, f)  # preview stays in the audit finding

    def _check_budget(self) -> Termination | None:
        u = self.report.usage
        cap = self.options.output_token_cap
        if cap is not None and u.estimated_output_tokens > cap:
            return Termination(f"output token budget exceeded (cap {cap})", "BUDGET")
        guard = self.options.budget_guard
        if guard is not None:
            reason = guard(u)
            if reason:
                return Termination(reason, "BUDGET")
        return None

    def _notice(self, term: Termination) -> str:
        return self.options.notice_template.format(reason=term.reason, control=term.control)

    def _fail(self, exc: Exception) -> bytes:
        log.exception("aegis stream transformer failed; terminating stream (fail-closed)")
        self.report.internal_error = repr(exc)
        if not self.options.fail_closed:
            raise exc
        try:
            return self._terminate_bytes(Termination("internal error in the aegis stream filter", "AEGIS-FAILSAFE"))
        except Exception:
            log.exception("graceful termination failed")
            self._finished = True
            return b""

    # ------------------------------------------------- subclass interface
    def _feed(self, chunk: bytes) -> bytes:  # pragma: no cover - abstract
        raise NotImplementedError

    def _close(self) -> bytes:  # pragma: no cover - abstract
        raise NotImplementedError

    def _terminate_bytes(self, term: Termination) -> bytes:  # pragma: no cover - abstract
        raise NotImplementedError
