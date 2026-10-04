"""Model manager: slots, RAM plan, lazy loads off the event loop, executor, Ollama, monitor.

The engine (``aegis.semantic.engine``) owns caching / single-flight / fallback; the manager owns
*what is loaded* and *how calls reach a backend*:

- one ``ModelSlot`` per entry of ``config.MODEL_SPECS`` (state, breaker, latency, counters);
- the static RAM plan (priority ``LOAD_ORDER``; budget ``ram_budget_mb`` and live
  ``psutil`` availability with ``ram_headroom_mb``), checked just before each load;
- sequential ONNX loads in the ``aegis-sem`` executor (3 workers), shared XLM-R vocab with an
  id-equality self-check, optional sha256 integrity check against ``models/MANIFEST.sha256``;
- ``run_onnx`` with admission control (``admission_limit`` in-flight per slot);
- the Ollama guard warm-up (version, tag check, real moderation call) and judge RAM gate;
- the monitor loop (``ollama ps``, psutil, keep-alive refresh, half-open probes, shedding).

Nothing here imports onnxruntime / tokenizers at module import time.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aegis.semantic.config import (
    MODEL_SPECS,
    XLMR_PROBE,
    XLMR_PROBE_IDS,
    ModelSpec,
    SemanticConfig,
)
from aegis.semantic.ollama import OllamaClient
from aegis.semantic.resilience import CircuitBreaker, LatencyWindow

log = logging.getLogger(__name__)

EventFn = Callable[[str, str, dict[str, Any]], None]  # (level, message, data)

#: slot state -> fallback code used when a call cannot reach the backend
STATE_TO_CODE: dict[str, str] = {
    "disabled": "off",
    "external": "off",
    "pending": "warming",
    "loading": "warming",
    "missing": "missing",
    "skipped_budget": "skipped_budget",
    "error": "error",
    "integrity_error": "error",
    "on_demand": "warming",
}


class Overload(Exception):
    """Admission limit reached for an ONNX slot."""


@dataclass
class ModelSlot:
    spec: ModelSpec
    breaker: CircuitBreaker
    state: str = "pending"
    obj: Any = None
    latency: LatencyWindow = field(default_factory=lambda: LatencyWindow(512))
    calls: int = 0
    escalations: int = 0
    errors: int = 0
    timeouts: int = 0
    fallbacks: int = 0
    inflight: int = 0
    load_ms: float | None = None
    last_error: str | None = None
    integrity: str = "unverified"
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def loaded(self) -> bool:
        return self.state == "ready"

    def snapshot(self) -> dict[str, Any]:
        p50, p95 = self.latency.p50, self.latency.p95
        return {
            "name": self.spec.name,
            "role": self.spec.role,
            "backend": self.spec.backend,
            "loaded": self.loaded,
            "state": self.state,
            "p50_ms": round(p50, 1) if p50 is not None else None,
            "p95_ms": round(p95, 1) if p95 is not None else None,
            "calls": self.calls,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "fallbacks": self.fallbacks,
            "escalations": self.escalations,
            "breaker": self.breaker.state,
            "est_mb": self.spec.est_mb,
            "load_ms": round(self.load_ms, 1) if self.load_ms is not None else None,
            "integrity": self.integrity,
            "licence": self.spec.licence,
            "last_error": self.last_error,
            **self.detail,
        }


def _available_mb() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().available / 1e6)
    except Exception:
        return None


def _rss_mb() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss / 1e6)
    except Exception:
        return None


def _read_manifest(models_dir: Path) -> dict[str, str]:
    """'./eu-pii-ner/model_quantized.onnx' -> sha256 (relative paths normalised)."""
    out: dict[str, str] = {}
    path = models_dir / "MANIFEST.sha256"
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            out[parts[1].strip().lstrip("*").removeprefix("./")] = parts[0].lower()
    return out


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


class ModelManager:
    def __init__(
        self,
        cfg: SemanticConfig,
        *,
        on_event: EventFn | None = None,
        on_breaker: Callable[[ModelSlot, str, str, str], None] | None = None,
        ollama: OllamaClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.on_event = on_event or (lambda level, msg, data: None)
        self.ollama = ollama or OllamaClient(cfg.ollama_url)
        self.clock = clock
        self.slots: dict[str, ModelSlot] = {}
        for name, spec in MODEL_SPECS.items():
            if name == "heuristic":
                continue
            slow = cfg.guard_slow_p95_ms if name == "aegis-guard" else None
            br = CircuitBreaker(name, slow_p95_ms=slow, clock=clock)
            slot = ModelSlot(spec=spec, breaker=br)
            if on_breaker is not None:
                br.on_change = lambda b, old, new, why, s=slot: on_breaker(s, old, new, why)
            slot.state = self._initial_state(name)
            self.slots[name] = slot
        self.heuristic_latency = LatencyWindow(512)
        self.heuristic_calls = 0
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self.ollama_info: dict[str, Any] = {
            "url": cfg.ollama_url,
            "reachable": None,
            "version": None,
            "loaded": [],
            "checked_at": None,
        }
        self.ollama_mb: int | None = None
        self.warmup_ms: float | None = None
        self.warming = False
        self.warmed = False
        self.guard_warmed_by_us = False
        self.vocab_shared: bool | None = None
        self._manifest: dict[str, str] | None = None
        self._last_keepalive = 0.0
        self._probe: Callable[[str], Awaitable[Any]] | None = None

    # ------------------------------------------------------------ states
    def _initial_state(self, name: str) -> str:
        cfg = self.cfg
        if cfg.off:
            return "disabled"
        if name == "eu-pii-ner" and not cfg.host_ner:
            return "external"
        if not cfg.slot_enabled(name):
            return "disabled"
        if not MODEL_SPECS[name].resident:
            return "on_demand"
        return "pending"

    def set_state(self, slot: ModelSlot, state: str, error: str | None = None) -> None:
        old = slot.state
        slot.state = state
        if error is not None:
            slot.last_error = error
        elif state == "ready":
            slot.last_error = None
        if old != state:
            log.info("semantic slot state slot=%s %s->%s", slot.name, old, state)

    def gate(self, name: str, *, consume: bool = True) -> str | None:
        """None if a call may go to the backend now, else the fallback code.

        ``consume=True`` takes the HALF_OPEN probe slot (callers that end up not calling the
        model must ``breaker.release_probe()``); ``consume=False`` only inspects.
        """
        if self.cfg.off:
            return "off"
        slot = self.slots[name]
        st = slot.state
        if st != "ready":
            ollama_retry = slot.spec.backend == "ollama" and st in ("error", "on_demand")
            if not ollama_retry or not self.warmed:
                return STATE_TO_CODE.get(st, "error")
        if consume:
            if not slot.breaker.allow():
                return "breaker_open"
        elif slot.breaker.state == "open":
            return "breaker_open"
        return None

    # ------------------------------------------------------------ executor
    @property
    def executor(self) -> concurrent.futures.ThreadPoolExecutor:
        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=self.cfg.executor_workers, thread_name_prefix="aegis-sem"
            )
        return self._executor

    async def run_onnx(self, name: str, fn: Callable[[Any], Any], timeout_s: float) -> Any:
        """Run ``fn(model_obj)`` in the executor; raises Overload / TimeoutError / errors."""
        slot = self.slots[name]
        if slot.inflight >= self.cfg.admission_limit:
            raise Overload(name)
        obj = slot.obj
        if obj is None:
            raise RuntimeError(f"{name} not loaded")
        loop = asyncio.get_running_loop()
        slot.inflight += 1

        def _dec(_: Any) -> None:
            try:
                loop.call_soon_threadsafe(_dec_inflight)
            except RuntimeError:  # loop closed
                slot.inflight = max(0, slot.inflight - 1)

        def _dec_inflight() -> None:
            slot.inflight = max(0, slot.inflight - 1)

        cf = self.executor.submit(fn, obj)
        cf.add_done_callback(_dec)
        return await asyncio.wait_for(asyncio.wrap_future(cf), timeout=timeout_s)

    # ------------------------------------------------------------ RAM plan
    def _resident_est_mb(self) -> int:
        return sum(
            s.spec.est_mb
            for s in self.slots.values()
            if s.state in ("ready", "loading") and s.spec.resident
        )

    def ram_check(self, name: str) -> tuple[bool, str]:
        spec = MODEL_SPECS[name]
        planned = self._resident_est_mb()
        if planned + spec.est_mb > self.cfg.ram_budget_mb:
            return False, f"RAM budget {planned + spec.est_mb}/{self.cfg.ram_budget_mb} MB"
        avail = _available_mb()
        if avail is not None and avail < spec.est_mb + self.cfg.ram_headroom_mb:
            return False, f"available {avail} MB < {spec.est_mb + self.cfg.ram_headroom_mb} MB"
        return True, ""

    def ram_snapshot(self) -> dict[str, Any]:
        return {
            "budget_mb": self.cfg.ram_budget_mb,
            "resident_est_mb": self._resident_est_mb(),
            "process_rss_mb": _rss_mb(),
            "ollama_mb": self.ollama_mb,
            "available_mb": _available_mb(),
        }

    # ------------------------------------------------------------ files / integrity
    def _files(self, spec: ModelSpec) -> list[Path]:
        base = self.cfg.models_dir / spec.subdir
        return [base / f for f in spec.files]

    def _missing(self, spec: ModelSpec) -> list[str]:
        return [
            str(p.relative_to(self.cfg.models_dir)) for p in self._files(spec) if not p.is_file()
        ]

    def _verify(self, spec: ModelSpec) -> str:
        """'verified' | 'mismatch' | 'unverified' (no manifest entry). Runs in the executor."""
        if self._manifest is None:
            self._manifest = _read_manifest(self.cfg.models_dir)
        if not self._manifest:
            return "unverified"
        result = "verified"
        for p in self._files(spec):
            rel = str(p.relative_to(self.cfg.models_dir))
            want = self._manifest.get(rel)
            if want is None:
                result = "unverified"
                continue
            if _sha256(p) != want:
                return "mismatch"
        return result

    # ------------------------------------------------------------ loaders (executor)
    def _load_sync(self, name: str) -> Any:
        cfg = self.cfg
        spec = MODEL_SPECS[name]
        d = cfg.models_dir / spec.subdir
        if name in ("horizon-small", "pg2-22m"):
            from aegis.semantic.onnx import PromptInjectionClassifier

            clf = PromptInjectionClassifier.load(
                name, d, threads=cfg.onnx_threads, max_windows=cfg.caps.injection_windows
            )
            clf.score("hello")
            return clf
        if name == "xlmr-vocab":
            from aegis.semantic.shared import xlmr_tokenizer

            tok = xlmr_tokenizer(cfg.models_dir)
            if tok is None:
                raise RuntimeError("xlmr tokenizer unavailable")
            return tok
        if name == "minilm-l12-multi":
            from aegis.semantic.embeddings import Embedder

            share = self.slots["xlmr-vocab"].obj
            emb = Embedder(d, threads=cfg.onnx_threads, share_vocab_with=share)
            emb.embed(["hello"])
            return emb
        if name == "eu-pii-ner":
            from aegis.semantic.onnx import PiiNer
            from aegis.semantic.shared import load_tokenizer

            share = self.slots["xlmr-vocab"].obj
            tok = None
            if share is not None:
                tok = load_tokenizer(d / "tokenizer.json", share_vocab_with=share)
                ids = tuple(tok.encode(XLMR_PROBE).ids)
                if XLMR_PROBE_IDS and ids != XLMR_PROBE_IDS:
                    log.warning(
                        "shared xlmr vocab self-check failed; loading unshared NER tokenizer"
                    )
                    tok = None
                    self.vocab_shared = False
                else:
                    self.vocab_shared = True
            ner = PiiNer(d, threads=cfg.onnx_threads, tokenizer=tok)
            ner.detect_raw("Jan Kowalski")
            return ner
        raise ValueError(f"unknown onnx slot {name}")

    async def load_slot(self, name: str) -> bool:
        """Load one in-process slot now (RAM plan + files + integrity). True if ready."""
        slot = self.slots[name]
        spec = slot.spec
        if slot.state in ("disabled", "external"):
            return False
        if slot.state == "ready":
            return True
        missing = self._missing(spec)
        if missing:
            self.set_state(
                slot, "missing", f"missing {', '.join(missing)} (run scripts/fetch_models.sh)"
            )
            self.on_event(
                "warning",
                f"Model files missing for {name}: run scripts/fetch_models.sh",
                {"slot": name, "state": "missing"},
            )
            return False
        ok, why = self.ram_check(name)
        if not ok:
            self.set_state(slot, "skipped_budget", why)
            self.on_event(
                "warning", f"{name} not loaded: {why}", {"slot": name, "state": "skipped_budget"}
            )
            return False
        self.set_state(slot, "loading")
        loop = asyncio.get_running_loop()
        t0 = time.perf_counter()
        try:
            if self.cfg.verify_integrity and spec.backend == "onnx":
                slot.integrity = await loop.run_in_executor(self.executor, self._verify, spec)
                if slot.integrity == "mismatch":
                    self.set_state(
                        slot, "integrity_error", "sha256 mismatch vs models/MANIFEST.sha256"
                    )
                    self.on_event(
                        "error",
                        f"Model integrity check FAILED for {name} - not loaded (supply-chain guard)",
                        {"slot": name, "state": "integrity_error", "audit": True},
                    )
                    return False
            obj = await loop.run_in_executor(self.executor, self._load_sync, name)
        except Exception as exc:
            self.set_state(slot, "error", f"load failed: {type(exc).__name__}: {exc}"[:300])
            log.warning("semantic load failed slot=%s error=%s", name, type(exc).__name__)
            self.on_event(
                "warning",
                f"{name} failed to load ({type(exc).__name__})",
                {"slot": name, "state": "error"},
            )
            return False
        slot.obj = obj
        slot.load_ms = (time.perf_counter() - t0) * 1e3
        if name == "eu-pii-ner":
            slot.detail["vocab_shared"] = bool(self.vocab_shared)
        self.set_state(slot, "ready")
        return True

    # ------------------------------------------------------------ Ollama
    async def check_ollama(self) -> bool:
        try:
            self.ollama_info["version"] = await self.ollama.version(timeout_s=1.0)
            self.ollama_info["reachable"] = True
        except Exception:
            self.ollama_info["reachable"] = False
        self.ollama_info["checked_at"] = time.time()
        return bool(self.ollama_info["reachable"])

    async def refresh_ps(self) -> None:
        try:
            models = await self.ollama.ps(timeout_s=1.0)
        except Exception:
            self.ollama_info["reachable"] = False
            return
        self.ollama_info["reachable"] = True
        self.ollama_info["loaded"] = [m["name"].split(":", 1)[0] for m in models]
        ours = [m for m in models if m["name"].split(":", 1)[0] in ("aegis-guard", "aegis-judge")]
        self.ollama_mb = sum(m["size_mb"] for m in ours) if ours else 0

    def ollama_loaded(self, tag: str) -> bool:
        return tag in (self.ollama_info.get("loaded") or [])

    async def prepare_guard(self, warm_call: Callable[[], Awaitable[Any]]) -> bool:
        """Version + tag check, then a real moderation call (loads it with keep_alive 30m)."""
        slot = self.slots["aegis-guard"]
        if slot.state in ("disabled", "external"):
            return False
        if not await self.check_ollama():
            self.set_state(slot, "error", f"Ollama unreachable at {self.cfg.ollama_url}")
            return False
        try:
            if not await self.ollama.has_model(slot.spec.tag):
                self.set_state(
                    slot,
                    "missing",
                    f"Ollama tag {slot.spec.tag} missing (run scripts/fetch_models.sh)",
                )
                return False
        except Exception as exc:
            self.set_state(slot, "error", f"ollama tags failed: {type(exc).__name__}")
            return False
        ok, why = self.ram_check("aegis-guard")
        if not ok and not self.ollama_loaded("aegis-guard"):
            await self.refresh_ps()
            if not self.ollama_loaded("aegis-guard"):
                self.set_state(slot, "skipped_budget", why)
                return False
        self.set_state(slot, "loading")
        t0 = time.perf_counter()
        try:
            await warm_call()
        except Exception as exc:
            self.set_state(slot, "error", f"warm-up failed: {type(exc).__name__}")
            return False
        slot.load_ms = (time.perf_counter() - t0) * 1e3
        self.guard_warmed_by_us = True
        self.set_state(slot, "ready")
        return True

    async def prepare_judge(self) -> None:
        slot = self.slots["aegis-judge"]
        if slot.state in ("disabled", "external"):
            return
        try:
            if self.ollama_info.get("reachable") and not await self.ollama.has_model(slot.spec.tag):
                self.set_state(slot, "missing", f"Ollama tag {slot.spec.tag} missing")
        except Exception:
            pass

    def judge_ram_ok(self) -> tuple[bool, str]:
        if self.ollama_loaded("aegis-judge"):
            return True, ""
        avail = _available_mb()
        if avail is not None and avail < self.cfg.judge_min_available_mb:
            return False, f"available {avail} MB < {self.cfg.judge_min_available_mb} MB"
        return True, ""

    # ------------------------------------------------------------ lifecycle
    async def unload_all(self) -> None:
        for slot in self.slots.values():
            if slot.spec.backend in ("onnx", "tokenizers") and slot.obj is not None:
                slot.obj = None
                if slot.state == "ready":
                    self.set_state(slot, "pending")
        try:
            from aegis.semantic.shared import release_xlmr_tokenizer

            release_xlmr_tokenizer()
        except Exception:
            pass
        if self.cfg.unload_on_stop and self.guard_warmed_by_us:
            try:
                await self.ollama.unload("aegis-guard", timeout_s=2.0)
            except Exception:
                pass
            self.guard_warmed_by_us = False

    async def close(self) -> None:
        await self.unload_all()
        try:
            await self.ollama.aclose()
        except Exception:
            pass
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None


__all__ = ["STATE_TO_CODE", "ModelManager", "ModelSlot", "Overload"]
