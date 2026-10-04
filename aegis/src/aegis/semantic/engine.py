"""SemanticModelEngine - ``rt.semantic`` (factory ``aegis.semantic.engine:create``).

Implements the frozen ``SemanticEngine`` protocol plus the kw-only extensions of CONTRACTS
Addendum A-44 / A-38 (``ner``, ``similarity_detail``, ``warmup``). Every call path is:

    cache(task, slot, mode, sha256(text)) -hit-> ScoreResult (~0 ms)
      miss -> gate (mode off / slot state / breaker) -> SingleFlight -> backend under timeout
      outcome -> latency window, breaker, metrics; failures -> heuristic, degraded=True,
                 reason "fallback:<code>" (shared.FALLBACK_REASONS). The engine never raises.

Lifecycle: ``create(rt)`` is cheap (no ORT / tokenizers import, no I/O). ``start()`` spawns the
warm-up task (sequential ONNX loads in the executor, then the Ollama guard) and the monitor loop;
in ``AEGIS_TEST_MODE`` nothing runs in the background and models load only via ``warmup()``.
With ``AEGIS_SEMANTIC=off`` nothing ever loads and every answer is the heuristic (``fallback:off``).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aegis.core.types import AuditEvent, ScoreResult, new_id
from aegis.semantic import guard as guard_mod
from aegis.semantic import heuristic
from aegis.semantic import judge as judge_mod
from aegis.semantic.config import MODEL_SPECS, SemanticConfig
from aegis.semantic.manager import ModelManager, ModelSlot, Overload
from aegis.semantic.ollama import OllamaClient, QueueTimeout
from aegis.semantic.resilience import SingleFlight, TTLCache

log = logging.getLogger(__name__)

ONNX_ORDER = ("horizon-small", "xlmr-vocab", "minilm-l12-multi", "eu-pii-ner", "pg2-22m")
STATUS_ORDER = (
    "horizon-small",
    "pg2-22m",
    "xlmr-vocab",
    "minilm-l12-multi",
    "eu-pii-ner",
    "aegis-guard",
    "aegis-judge",
)
ESCALATE_BAND = (0.50, 0.80)  # Horizon review band escalated to Qwen3Guard (SF-22 / SEM-15)


class GuardParseError(Exception):
    """Qwen3Guard answered without a parsable 'Safety:' line."""


def _h(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", "surrogatepass")).hexdigest()


def _cap_head_tail(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    half = cap // 2
    return text[:half] + "\n" + text[-half:]


def _ascii_dominant(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    return sum(1 for c in letters if c.isascii()) / len(letters) >= 0.9


def _pg2_calibrate(raw: float) -> float:
    """PG2 is very conservative: raw 0.30 ~ calibrated 0.90 (RESULTS.md)."""
    if raw <= 0.30:
        return raw * 3.0
    return min(1.0, 0.90 + (raw - 0.30) * (0.10 / 0.70))


class SemanticModelEngine:
    """The one in-process model runtime. See module docstring."""

    def __init__(
        self,
        rt: Any = None,
        *,
        config: SemanticConfig | None = None,
        ollama: OllamaClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rt = rt
        settings = getattr(rt, "settings", None) if rt is not None else None
        if settings is None and config is None:
            try:
                from aegis.settings import get_settings

                settings = get_settings()
            except Exception:
                settings = None
        self.cfg = config or SemanticConfig.from_settings(settings)
        self.mgr = ModelManager(
            self.cfg,
            on_event=self._event,
            on_breaker=self._breaker_changed,
            ollama=ollama,
            clock=clock,
        )
        self.cache = TTLCache(self.cfg.cache_size, self.cfg.cache_ttl_s, clock=clock)
        self.vec_cache = TTLCache(self.cfg.cache_size, self.cfg.cache_ttl_s, clock=clock)
        self.flight = SingleFlight()
        self._tasks: list[asyncio.Task[Any]] = []
        self._health: str | None = None
        self._started = False
        self._shed: set[str] = set()

    # ================================================================ rt side-channels
    def _publish(self, level: str, message: str) -> None:
        bus = getattr(self.rt, "bus", None)
        if bus is None:
            return
        try:
            bus.publish("system", {"level": level, "message": message, "component": "semantic"})
        except Exception:
            log.debug("semantic bus publish failed")

    def _audit(self, data: dict[str, Any]) -> None:
        audit = getattr(self.rt, "audit", None)
        if audit is None:
            return
        try:
            ev = AuditEvent(
                event_id=new_id("evt"),
                event_type="system",
                data={"component": "semantic", **data},
            )
            coro = audit.record(ev)
            if asyncio.iscoroutine(coro):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    coro.close()
                    return
                task = loop.create_task(coro)
                self._tasks.append(task)
                task.add_done_callback(
                    lambda t: self._tasks.remove(t) if t in self._tasks else None
                )
        except Exception:
            log.debug("semantic audit record failed")

    def _metric_inc(self, model: str, outcome: str) -> None:
        m = getattr(self.rt, "metrics", None)
        if m is None:
            return
        try:
            m.inc("aegis_semantic_calls_total", {"model": model, "outcome": outcome})
        except Exception:
            pass

    def _metric_overhead(self, slot: str, ms: float) -> None:
        m = getattr(self.rt, "metrics", None)
        if m is None:
            return
        try:
            m.observe_overhead(f"semantic.{slot}", ms / 1000.0)
        except Exception:
            pass

    def _metric_gauges(self, health: str) -> None:
        m = getattr(self.rt, "metrics", None)
        if m is None:
            return
        try:
            m.set_gauge("aegis_semantic_degraded", 0.0 if health == "ok" else 1.0)
            for name, slot in self.mgr.slots.items():
                m.set_gauge("aegis_semantic_model_up", 1.0 if slot.loaded else 0.0, {"model": name})
        except Exception:
            pass

    def _event(self, level: str, message: str, data: dict[str, Any]) -> None:
        """Manager slot events -> SSE `system` (+ audit for errors / integrity)."""
        if not data.pop("quiet", False):
            self._publish(level, message)
        if level == "error" or data.pop("audit", False):
            self._audit({**data, "message": message})

    def _breaker_changed(self, slot: ModelSlot, old: str, new: str, why: str) -> None:
        if new == "open":
            log.warning("semantic breaker open slot=%s reason=%s", slot.name, why)
            self._publish(
                "warning",
                f"Semantic model {slot.name} unavailable ({why}) - heuristic fallback active",
            )
            self._audit({"slot": slot.name, "state": "breaker_open", "reason": why})
        elif new == "closed" and old == "half_open":
            log.info("semantic breaker closed slot=%s", slot.name)
            self._publish("info", f"Semantic model {slot.name} recovered")
            self._audit({"slot": slot.name, "state": "breaker_closed", "reason": why})
        # the breaker message above already told the operator: one toast, not two
        self._health = self.compute_health()
        self._metric_gauges(self._health)

    # ================================================================ health
    def compute_health(self) -> str:
        if self.cfg.off:
            return "off"
        enabled = [s for s in self.mgr.slots.values() if s.state not in ("disabled", "external")]
        if not enabled:
            return "off"
        required = [s for s in enabled if s.spec.required]

        def ok(s: ModelSlot) -> bool:
            return s.state == "ready" and s.breaker.state != "open"

        if all(ok(s) for s in required):
            return "ok"
        if not any(ok(s) for s in enabled if s.spec.backend != "tokenizers"):
            return "down"
        return "degraded"

    def _update_health(self, *, force: bool = False) -> str:
        health = self.compute_health()
        self._metric_gauges(health)
        if health != self._health:
            old = self._health
            self._health = health
            if (self.mgr.warmed or force) and old is not None and not self.mgr.warming:
                level = "info" if health in ("ok", "off") else "warning"
                not_ready = [
                    s.name
                    for s in self.mgr.slots.values()
                    if s.spec.required and s.state not in ("ready", "disabled", "external")
                ]
                msg = f"Semantic tier {health}" + (
                    f" (not ready: {', '.join(not_ready)})" if not_ready and health != "ok" else ""
                )
                self._publish(level, msg)
                self._audit({"state": f"health.{health}", "from": old})
        return health

    # ================================================================ core call path
    def _fallback(
        self, fn: Callable[[], ScoreResult], code: str, slot: str, t0: float
    ) -> ScoreResult:
        try:
            r = fn()
        except Exception:  # the heuristic must never take the engine down
            r = ScoreResult(score=0.0, model="heuristic")
        ms = (time.perf_counter() - t0) * 1e3
        self.mgr.heuristic_calls += 1
        self.mgr.heuristic_latency.add(ms)
        s = self.mgr.slots.get(slot)
        if s is not None and code != "off":
            s.fallbacks += 1
        if code != "off":
            outcome = code if code in ("timeout", "error", "breaker_open") else "fallback"
            self._metric_inc(slot, outcome)
        detail = f" · {r.reason}" if r.reason else ""
        return r.model_copy(
            update={
                "degraded": True,
                "reason": f"fallback:{code}{detail}",
                "model": "heuristic",
                "latency_ms": round(ms, 3),
            }
        )

    async def _invoke(
        self, name: str, backend: Callable[[], Awaitable[Any]], timeout_s: float
    ) -> Any:
        """Run a backend call with breaker / latency / recovery bookkeeping (may raise)."""
        slot = self.mgr.slots[name]
        t0 = time.perf_counter()
        slot.calls += 1
        try:
            res = await asyncio.wait_for(backend(), timeout=max(0.001, timeout_s))
        except (QueueTimeout, Overload, asyncio.CancelledError):
            slot.breaker.release_probe()  # not a model failure
            raise
        except TimeoutError:
            slot.timeouts += 1
            slot.breaker.record(False, (time.perf_counter() - t0) * 1e3)
            raise
        except Exception as exc:
            slot.errors += 1
            slot.last_error = f"{type(exc).__name__}: {exc}"[:200]
            slot.breaker.record(False, (time.perf_counter() - t0) * 1e3)
            raise
        ms = (time.perf_counter() - t0) * 1e3
        slot.latency.add(ms)
        slot.breaker.record(True, ms)
        if slot.state != "ready" and slot.spec.backend == "ollama":
            prev = slot.state
            self.mgr.set_state(slot, "ready")
            if prev == "error":
                self._publish("info", f"Semantic model {name} recovered")
                self._audit({"slot": name, "state": "ready", "from": prev})
            self._update_health()
        self._metric_inc(name, "ok")
        self._metric_overhead(name, ms)
        return res

    async def _score(
        self,
        *,
        task: str,
        slot: str,
        key: tuple[Any, ...],
        timeout_s: float,
        backend: Callable[[], Awaitable[ScoreResult]],
        fallback: Callable[[], ScoreResult],
        precheck: Callable[[], str | None] | None = None,
    ) -> ScoreResult:
        t0 = time.perf_counter()
        try:
            if self.cfg.off:
                return self._fallback(fallback, "off", slot, t0)
            ckey = (task, slot, *key)
            hit = self.cache.get(ckey)
            if hit is not None:
                self._metric_inc(slot, "cache")
                return hit.model_copy(
                    update={"latency_ms": round((time.perf_counter() - t0) * 1e3, 3)}
                )
            code = self.mgr.gate(slot)
            if code is None and precheck is not None:
                code = precheck()
                if code is not None:
                    self.mgr.slots[slot].breaker.release_probe()
            if code is not None:
                return self._fallback(fallback, code, slot, t0)
            try:
                res = await self.flight.do(ckey, lambda: self._invoke(slot, backend, timeout_s))
            except Overload:
                return self._fallback(fallback, "overload", slot, t0)
            except QueueTimeout:
                return self._fallback(fallback, "queue", slot, t0)
            except TimeoutError:
                return self._fallback(fallback, "timeout", slot, t0)
            except asyncio.CancelledError:
                raise
            except Exception:
                return self._fallback(fallback, "error", slot, t0)
            self.cache.set(ckey, res)
            return res.model_copy(update={"latency_ms": round((time.perf_counter() - t0) * 1e3, 3)})
        except asyncio.CancelledError:
            raise
        except Exception:  # defensive: never raise to callers
            log.exception("semantic call failed task=%s", task)
            return self._fallback(fallback, "error", slot, t0)

    def _timeout(self, timeout_s: float | None, default_ms: int) -> float:
        return float(timeout_s) if timeout_s is not None and timeout_s > 0 else default_ms / 1000.0

    # ================================================================ protocol methods
    async def injection_score(
        self,
        text: str,
        *,
        trusted: bool = True,
        timeout_s: float | None = None,
        escalate: bool = True,
    ) -> ScoreResult:
        """P(injection) from Horizon PI-small (max over head+tail windows; PG2 vote if enabled).

        Scores in the 0.50-0.80 review band are escalated to Qwen3Guard when it is ready and
        ``escalate`` is set: Jailbreak -> max(score, 0.92); Safe -> min(score, 0.45).
        """
        text = text or ""
        capped = _cap_head_tail(text, self.cfg.caps.injection_chars)
        timeout = self._timeout(timeout_s, self.cfg.timeouts.injection_ms)
        use_pg2 = self.mgr.slots["pg2-22m"].state == "ready" and _ascii_dominant(capped)

        async def backend() -> ScoreResult:
            score, wins = await self.mgr.run_onnx(
                "horizon-small", lambda clf: clf.score_detail(capped), timeout
            )
            model = "horizon-small"
            if use_pg2:
                try:
                    raw, _ = await self.mgr.run_onnx(
                        "pg2-22m", lambda clf: clf.score_detail(capped), timeout
                    )
                    cal = _pg2_calibrate(raw)
                    if cal > score:
                        score, model = cal, "horizon-small+pg2-22m"
                except Exception:
                    pass
            return ScoreResult(
                score=round(float(score), 4),
                label="injection" if score >= 0.5 else "benign",
                model=model,
                categories=["Jailbreak"] if score >= 0.5 else [],
                reason=f"windows={wins}",
            )

        res = await self._score(
            task="injection",
            slot="horizon-small",
            key=(_h(capped), use_pg2),
            timeout_s=timeout,
            backend=backend,
            fallback=lambda: heuristic.injection(capped),
        )
        if (
            escalate
            and not res.degraded
            and ESCALATE_BAND[0] <= res.score < ESCALATE_BAND[1]
            and self.mgr.gate("aegis-guard", consume=False) is None
        ):
            g = await self.moderate(
                text, mode="prompt", timeout_s=self._timeout(None, self.cfg.timeouts.moderate_ms)
            )
            if not g.degraded:
                self.mgr.slots["horizon-small"].escalations += 1
                if "Jailbreak" in g.categories and g.label in ("Unsafe", "Controversial"):
                    score = max(res.score, 0.92)
                elif g.label == "Safe":
                    score = min(res.score, 0.45)
                else:
                    score = res.score
                res = res.model_copy(
                    update={
                        "score": round(score, 4),
                        "label": "injection" if score >= 0.5 else "benign",
                        "categories": ["Jailbreak"] if score >= 0.5 else [],
                        "model": f"{res.model}+aegis-guard",
                        "latency_ms": round(res.latency_ms + g.latency_ms, 3),
                        "reason": f"escalated: guard={g.label}",
                    }
                )
        return res

    async def moderate(
        self,
        text: str,
        *,
        mode: str = "prompt",
        prompt: str | None = None,
        timeout_s: float | None = None,
    ) -> ScoreResult:
        """Qwen3Guard safety: label Safe/Controversial/Unsafe, score 0.0/0.5/1.0, categories."""
        text = text or ""
        mode = "response" if mode == "response" else "prompt"
        timeout = self._timeout(timeout_s, self.cfg.timeouts.moderate_ms)
        cfg = self.cfg
        tag = MODEL_SPECS["aegis-guard"].tag

        async def backend() -> ScoreResult:
            msgs = guard_mod.messages_for(text, mode=mode, prompt=prompt)
            body = guard_mod.payload(
                tag,
                guard_mod.build_prompt(msgs, max_chars=cfg.caps.guard_chars),
                keep_alive=cfg.guard_keep_alive,
                num_ctx=cfg.guard_num_ctx,
                logprobs=False,
            )
            t0 = time.perf_counter()
            resp = await self.mgr.ollama.generate_raw(
                body, timeout_s=timeout, queue_wait_s=cfg.guard_queue_wait_ms / 1000.0
            )
            v = guard_mod.verdict_from_response(resp)
            if v.safety == "Unknown":
                raise GuardParseError("unparsable guard output")
            return guard_mod.verdict_to_score(
                v, mode=mode, latency_ms=(time.perf_counter() - t0) * 1e3
            )

        return await self._score(
            task="moderate",
            slot="aegis-guard",
            key=(mode, _h(prompt or "") if mode == "response" else "", _h(text)),
            timeout_s=timeout,
            backend=backend,
            fallback=lambda: heuristic.moderation(text, mode),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """MiniLM vectors (384-d, L2-normalised). ``[]`` when MiniLM is unavailable (A-44:
        never fake vectors)."""
        name = "minilm-l12-multi"
        if not texts or self.mgr.gate(name, consume=False) is not None:
            return []
        capped = [(t or "")[: self.cfg.caps.embed_chars] for t in texts]
        keys = [("vec", _h(t)) for t in capped]
        out: list[Any] = [self.vec_cache.get(k) for k in keys]
        missing = [i for i, v in enumerate(out) if v is None]
        if missing:
            if self.mgr.gate(name) is not None:
                return []
            todo = [capped[i] for i in missing]
            timeout = self._timeout(None, self.cfg.timeouts.embed_ms) * max(1, len(todo) // 8 + 1)

            async def backend() -> Any:
                return await self.mgr.run_onnx(
                    "minilm-l12-multi", lambda e: e.embed(todo).tolist(), timeout
                )

            try:
                vecs = await self._invoke("minilm-l12-multi", backend, timeout)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.mgr.slots["minilm-l12-multi"].fallbacks += 1
                return []
            for i, v in zip(missing, vecs, strict=True):
                out[i] = v
                self.vec_cache.set(keys[i], v)
        return [list(v) for v in out]

    async def similarity(self, text: str, references: list[str]) -> float:
        return (await self.similarity_detail(text, references)).score

    async def similarity_detail(
        self, text: str, references: list[str], *, timeout_s: float | None = None
    ) -> ScoreResult:
        """Max cosine of ``text`` (sentence windows when long) vs ``references``, in [0, 1].

        ``model`` tells the backend ("minilm-l12-multi" or "heuristic") so callers can apply a
        per-backend calibration (INJ-03 adherence).
        """
        text = (text or "")[: self.cfg.caps.embed_chars * 4]
        refs = [r for r in references if r and r.strip()]
        timeout = self._timeout(timeout_s, self.cfg.timeouts.similarity_ms)
        if not refs:
            return ScoreResult(score=0.0, label="similarity", model="none")
        vec_cache = self.vec_cache

        def run(emb: Any) -> tuple[float, list[tuple[str, Any]]]:
            import numpy as np

            new: list[tuple[str, Any]] = []
            mats = []
            todo = []
            for r in refs:
                v = vec_cache.get(("vec", _h(r)))
                if v is None:
                    todo.append(r)
                else:
                    mats.append(v)
            if todo:
                vv = emb.embed(todo)
                for r, v in zip(todo, vv, strict=True):
                    new.append((_h(r), v.tolist()))
                    mats.append(v.tolist())
            ref_mat = np.asarray(mats, dtype=np.float32)
            return emb.max_sim(text, ref_mat), new

        async def backend() -> ScoreResult:
            sim, new = await self.mgr.run_onnx("minilm-l12-multi", run, timeout)
            for hk, v in new:
                vec_cache.set(("vec", hk), v)
            return ScoreResult(score=round(sim, 4), label="similarity", model="minilm-l12-multi")

        return await self._score(
            task="similarity",
            slot="minilm-l12-multi",
            key=(_h(text), _h("\x1f".join(refs))),
            timeout_s=timeout,
            backend=backend,
            fallback=lambda: heuristic.similarity(text, refs),
        )

    async def judge(self, rule: str, text: str, *, timeout_s: float | None = None) -> ScoreResult:
        """Calibrated P(violation) of ``rule`` by ``aegis-judge`` (0.70 = raw P(yes) 0.08)."""
        rule = rule or ""
        text = (text or "")[: self.cfg.caps.judge_chars]
        timeout = self._timeout(timeout_s, self.cfg.timeouts.judge_ms)
        cfg = self.cfg
        tag = MODEL_SPECS["aegis-judge"].tag

        async def backend() -> ScoreResult:
            body = judge_mod.yesno_payload(
                tag,
                judge_mod.yesno_messages(rule, text, cfg.caps.judge_chars),
                cfg.judge_keep_alive,
            )
            t0 = time.perf_counter()
            resp = await self.mgr.ollama.chat(
                body, timeout_s=timeout, queue_wait_s=cfg.judge_queue_wait_ms / 1000.0
            )
            raw = judge_mod.p_yes(resp)
            score = judge_mod.calibrate(raw)
            return ScoreResult(
                score=round(score, 4),
                label="violation" if score >= 0.7 else "ok",
                model="aegis-judge",
                latency_ms=(time.perf_counter() - t0) * 1e3,
                reason=f"p_yes={raw:.3f}",
            )

        def precheck() -> str | None:
            ok, _ = self.mgr.judge_ram_ok()
            return None if ok else "ram_budget"

        return await self._score(
            task="judge",
            slot="aegis-judge",
            key=(_h(rule), _h(text)),
            timeout_s=timeout,
            backend=backend,
            fallback=lambda: heuristic.judge(rule, text),
            precheck=precheck,
        )

    async def ner(
        self,
        text: str,
        *,
        labels: set[str] | list[str] | None = None,
        min_scores: dict[str, float] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any] | None:
        """EU-PII NER spans (A-38): ``{"model", "spans": [{label, start, end, score}],
        "latency_ms", "truncated"}`` - raw bardsai labels, offsets into ``text``, no text.
        ``None`` = NER unavailable (off, not loaded, timeout, error)."""
        t0 = time.perf_counter()
        name = "eu-pii-ner"
        text = text or ""
        cap = self.cfg.caps.ner_chars
        capped = text[:cap]
        truncated = len(text) > cap
        if self.mgr.gate(name, consume=False) is not None:
            if not self.cfg.off:
                self.mgr.slots[name].fallbacks += 1
            return None
        key = ("ner", name, _h(capped))
        raw = self.cache.get(key)
        if raw is None:
            if self.mgr.gate(name) is not None:
                self.mgr.slots[name].fallbacks += 1
                return None
            timeout = self._timeout(timeout_s, self.cfg.timeouts.ner_ms)

            async def backend() -> list[dict[str, Any]]:
                return await self.mgr.run_onnx(
                    name, lambda n: [s.to_dict() for s in n.detect_raw(capped)], timeout
                )

            try:
                raw = await self.flight.do(key, lambda: self._invoke(name, backend, timeout))
            except asyncio.CancelledError:
                raise
            except Exception:
                self.mgr.slots[name].fallbacks += 1
                return None
            self.cache.set(key, raw)
        else:
            self._metric_inc(name, "cache")
        from aegis.semantic.onnx import DEFAULT_MIN_SCORE, LABEL_MIN_SCORE

        thr = dict(LABEL_MIN_SCORE)
        if min_scores:
            thr.update(min_scores)
        want = set(labels) if labels is not None else None
        spans = [
            dict(s)
            for s in raw
            if (want is None or s["label"] in want)
            and s["score"] >= thr.get(s["label"], DEFAULT_MIN_SCORE)
        ]
        return {
            "model": name,
            "spans": spans,
            "latency_ms": round((time.perf_counter() - t0) * 1e3, 3),
            "truncated": truncated,
        }

    # ================================================================ status
    def status(self) -> dict[str, Any]:
        health = self.compute_health()
        models = [self.mgr.slots[n].snapshot() for n in STATUS_ORDER if n in self.mgr.slots]
        hl = self.mgr.heuristic_latency
        models.append(
            {
                "name": "heuristic",
                "role": "fallback",
                "backend": "python",
                "loaded": True,
                "state": "ready",
                "p50_ms": round(hl.p50, 3) if hl.p50 is not None else None,
                "p95_ms": round(hl.p95, 3) if hl.p95 is not None else None,
                "calls": self.mgr.heuristic_calls,
                "errors": 0,
                "timeouts": 0,
                "fallbacks": 0,
                "escalations": 0,
                "breaker": "closed",
                "est_mb": 0,
                "load_ms": 0.0,
                "integrity": "n/a",
                "licence": "Apache-2.0",
                "last_error": None,
            }
        )
        return {
            "mode": self.cfg.mode,
            "degraded": health != "ok",
            "health": health,
            "ready": bool(self.cfg.off or self.mgr.warmed),
            "warming": self.mgr.warming,
            "warmup_ms": round(self.mgr.warmup_ms, 1) if self.mgr.warmup_ms is not None else None,
            "test_mode": self.cfg.test_mode,
            "ram": self.mgr.ram_snapshot(),
            "ollama": {
                "url": self.cfg.ollama_url,
                "reachable": self.mgr.ollama_info.get("reachable"),
                "version": self.mgr.ollama_info.get("version"),
                "loaded": list(self.mgr.ollama_info.get("loaded") or []),
            },
            "vocab_shared": self.mgr.vocab_shared,
            "models": models,
            "cache": {
                "hits": self.cache.hits,
                "misses": self.cache.misses,
                "size": len(self.cache),
                "single_flight_shared": self.flight.shared,
            },
        }

    # ================================================================ lifecycle
    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self.cfg.off:
            log.info("semantic engine off (heuristic only)")
            self._update_health()
            return
        self._update_health()
        if self.cfg.test_mode:
            return
        self._tasks.append(asyncio.create_task(self._warmup_task(), name="aegis-sem-warmup"))
        self._tasks.append(asyncio.create_task(self._monitor_loop(), name="aegis-sem-monitor"))

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(BaseException):
                await t
        await self.mgr.close()
        self.cache.clear()
        self.vec_cache.clear()
        self._started = False

    async def warmup(self, models: list[str] | None = None) -> dict[str, Any]:
        """Load the given slots (default: all planned) now; for tests and admins."""
        if self.cfg.off:
            return self.status()
        await self._load_all(models)
        return self.status()

    async def _guard_warm(self) -> None:
        cfg = self.cfg
        body = guard_mod.payload(
            MODEL_SPECS["aegis-guard"].tag,
            guard_mod.build_prompt([{"role": "user", "content": "Hello"}]),
            keep_alive=cfg.guard_keep_alive,
            num_ctx=cfg.guard_num_ctx,
            logprobs=False,
        )
        resp = await self.mgr.ollama.generate_raw(body, timeout_s=60.0, queue_wait_s=None)
        if guard_mod.verdict_from_response(resp).safety == "Unknown":
            raise GuardParseError("guard warm-up output unparsable")

    async def _load_all(self, models: list[str] | None = None) -> None:
        want = set(models) if models else None
        t0 = time.perf_counter()
        self.mgr.warming = True
        try:
            needs_vocab = {"minilm-l12-multi", "eu-pii-ner"}
            for name in ONNX_ORDER:
                slot = self.mgr.slots[name]
                if want is not None and name not in want:
                    if not (name == "xlmr-vocab" and want & needs_vocab):
                        continue
                if slot.state not in ("pending", "error", "skipped_budget", "missing"):
                    continue
                await self.mgr.load_slot(name)
            if want is None or "aegis-guard" in want:
                g = self.mgr.slots["aegis-guard"]
                if g.state not in ("disabled", "external", "ready"):
                    await self.mgr.prepare_guard(self._guard_warm)
            if want is None or "aegis-judge" in want:
                await self.mgr.prepare_judge()
            await self.mgr.refresh_ps()
        finally:
            self.mgr.warming = False
            self.mgr.warmed = True
            self.mgr.warmup_ms = (time.perf_counter() - t0) * 1e3

    async def _warmup_task(self) -> None:
        try:
            await self._load_all()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("semantic warm-up failed")
        ready = [
            s.name for s in self.mgr.slots.values() if s.state == "ready" and s.name != "xlmr-vocab"
        ]
        not_ready = [
            f"{s.name} ({s.state})"
            for s in self.mgr.slots.values()
            if s.spec.required and s.state not in ("ready", "disabled", "external")
        ]
        est = self.mgr._resident_est_mb() / 1000.0
        secs = (self.mgr.warmup_ms or 0.0) / 1000.0
        if not not_ready:
            msg = (
                f"Semantic tier ready in {secs:.1f} s: {', '.join(ready)} "
                f"(est {est:.2f}/{self.cfg.ram_budget_mb / 1000:.2f} GB)"
            )
            self._publish("info", msg)
            log.info(
                "semantic warm-up done ms=%.0f ready=%s", self.mgr.warmup_ms or 0, ",".join(ready)
            )
        else:
            msg = (
                f"Semantic tier degraded after {secs:.1f} s - heuristic fallback for: "
                f"{', '.join(not_ready)}"
            )
            self._publish("warning", msg)
            self._audit({"state": "warmup.degraded", "not_ready": not_ready})
            log.warning("semantic warm-up degraded not_ready=%s", ",".join(not_ready))
        self._health = self.compute_health()
        self._metric_gauges(self._health)

    # ================================================================ monitor (SEM-12)
    async def _monitor_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.monitor_interval_s)
            if self.mgr.warming:
                continue
            try:
                await self.monitor_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug("semantic monitor tick failed", exc_info=True)

    async def monitor_tick(self) -> None:
        """One monitor iteration: ps/psutil, guard re-warm / probe, keep-alive, shedding."""
        from aegis.semantic.manager import _available_mb

        mgr, cfg = self.mgr, self.cfg
        await mgr.refresh_ps()
        g = mgr.slots["aegis-guard"]
        tag = g.spec.tag
        now = mgr.clock()
        avail = _available_mb()

        # shedding under memory pressure (pg2 -> judge -> guard)
        if avail is not None and avail < cfg.shed_below_mb:
            p = mgr.slots["pg2-22m"]
            if p.state == "ready":
                p.obj = None
                mgr.set_state(p, "skipped_budget", "shed under memory pressure")
                self._shed.add(p.name)
                self._publish("warning", f"Low memory ({avail} MB): unloaded pg2-22m")
            elif mgr.ollama_loaded("aegis-judge"):
                with contextlib.suppress(Exception):
                    await mgr.ollama.unload("aegis-judge")
                self._publish("warning", f"Low memory ({avail} MB): unloaded aegis-judge")
            elif g.state == "ready" and mgr.guard_warmed_by_us:
                with contextlib.suppress(Exception):
                    await mgr.ollama.unload(tag)
                mgr.set_state(g, "skipped_budget", "shed under memory pressure")
                self._shed.add(g.name)
                self._publish(
                    "warning",
                    f"Low memory ({avail} MB): unloaded aegis-guard - heuristic moderation",
                )
            self._update_health()
            return
        if (
            avail is not None
            and avail > cfg.reload_above_mb
            and "aegis-guard" in self._shed
            and g.state == "skipped_budget"
        ):
            self._shed.discard("aegis-guard")
            await mgr.prepare_guard(self._guard_warm)
            self._update_health()

        # guard evicted by Ollama, or down since startup -> re-warm / probe
        if g.state in ("ready", "error", "on_demand") and g.breaker.state != "open":
            evicted = (
                g.state == "ready"
                and mgr.ollama_info.get("reachable")
                and not mgr.ollama_loaded(tag)
            )
            if evicted or g.state != "ready" or g.breaker.state == "half_open":
                if g.breaker.allow():
                    try:
                        await self._invoke("aegis-guard", self._guard_warm, 30.0)
                        mgr.guard_warmed_by_us = True
                        mgr._last_keepalive = now
                    except Exception:
                        pass
        if g.state == "ready" and now - mgr._last_keepalive >= cfg.keepalive_refresh_s:
            mgr._last_keepalive = now
            with contextlib.suppress(Exception):
                await mgr.ollama.warm(tag, cfg.guard_keep_alive, timeout_s=10.0)
        self._update_health()


def create(rt: Any) -> SemanticModelEngine:
    """Factory for ``rt.semantic`` (cheap: no model loads, no heavy imports, no I/O)."""
    return SemanticModelEngine(rt)


__all__ = ["SemanticModelEngine", "create"]
