"""NER for DLP-07: bardsai eu-pii-anonimization-multilang (XLM-R, INT8 ONNX) - single instance.

Order of preference (KI-03 "never load the NER twice", +673 MB on an 8 GB machine):
  1. ``rt.semantic.ner(text, labels=, min_scores=, timeout_s=)`` (semantic-models hosts the model,
     CG-1a) -> raw bardsai labels mapped here to contract entities;
  2. our own lazily loaded ``PiiNer`` - ONLY if ``rt.semantic`` has no ``ner`` at all, the model
     files exist, ``AEGIS_SEMANTIC != off`` and psutil reports > 900 MB available;
  3. the deterministic heuristics in ``aegis.redaction.ner_fallback`` (``degraded=True``).
Heuristic spans are also merged next to model spans (hybrid), so the scripted demo names,
addresses and health terms are always covered.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from aegis.core.types import Span

from . import entities as E
from . import ner_fallback

log = logging.getLogger(__name__)

MODEL_DIR_NAME = "eu-pii-ner"
MODEL_FILE = "model_quantized.onnx"
MIN_FREE_MB = 900

#: bardsai label -> contract entity
LABEL_TO_ENTITY: dict[str, str] = {
    "PERSON_NAME": "PERSON",
    "PERSON_ALIAS": "PERSON",
    "POSTAL_ADDRESS": "ADDRESS",
    "DATE_OF_BIRTH": "DOB",
    "HEALTH_DATA": "HEALTH",
    "BIOMETRIC_DATA": "SPECIAL_CATEGORY",
    "RELIGION_OR_BELIEF": "SPECIAL_CATEGORY",
    "POLITICAL_OPINION": "SPECIAL_CATEGORY",
    "SEXUAL_ORIENTATION": "SPECIAL_CATEGORY",
    "ETHNIC_ORIGIN": "SPECIAL_CATEGORY",
    "TRADE_UNION_MEMBERSHIP": "SPECIAL_CATEGORY",
    "CRIMINAL_OFFENCE_DATA": "SPECIAL_CATEGORY",
}
ENTITY_TO_LABELS: dict[str, list[str]] = {}
for _lab, _ent in LABEL_TO_ENTITY.items():
    ENTITY_TO_LABELS.setdefault(_ent, []).append(_lab)

#: staged per-label floors (staging/models/RESULTS.md)
LABEL_MIN_SCORE: dict[str, float] = {
    "PERSON_NAME": 0.55,
    "LOCATION": 0.60,
    "HEALTH_DATA": 0.30,
    "RELIGION_OR_BELIEF": 0.30,
    "POLITICAL_OPINION": 0.30,
    "SEXUAL_ORIENTATION": 0.30,
    "ETHNIC_ORIGIN": 0.30,
    "TRADE_UNION_MEMBERSHIP": 0.30,
    "BIOMETRIC_DATA": 0.30,
    "CRIMINAL_OFFENCE_DATA": 0.30,
}


def _state(engine: Any) -> dict[str, Any]:
    st = getattr(engine, "_ner_state", None)
    if st is None:
        st = {
            "backend": "none",
            "loaded": False,
            "degraded": True,
            "last_ms": None,
            "calls": 0,
            "fallbacks": 0,
            "reason": "not used yet",
        }
        engine._ner_state = st
    return st


def _semantic_mode(engine: Any) -> str:
    return str(getattr(getattr(engine, "settings", None), "semantic", "auto") or "auto").lower()


def heuristic_spans(text: str, entities: set[str] | None = None) -> list[Span]:
    want = None if entities is None else (set(entities) & E.NER_ENTITIES)
    if want is not None and not want:
        return []
    return [
        Span(
            start=s.start,
            end=s.end,
            entity=s.entity,
            data_class=E.data_class(s.entity),
            detector_id=s.detector_id,
            score=s.score,
            category="pii",
        )
        for s in ner_fallback.detect(text, want)
    ]


def _map_model_spans(raw: dict[str, Any] | None, entities: set[str] | None) -> list[Span]:
    out: list[Span] = []
    for sp in (raw or {}).get("spans") or []:
        label = str(sp.get("label", ""))
        ent = LABEL_TO_ENTITY.get(label)
        if ent is None:
            continue
        if entities is not None and ent not in entities:
            continue
        try:
            a, b, score = int(sp["start"]), int(sp["end"]), float(sp.get("score", 0.0))
        except (KeyError, TypeError, ValueError):
            continue
        if b <= a:
            continue
        out.append(
            Span(
                start=a,
                end=b,
                entity=ent,
                data_class=E.data_class(ent),
                detector_id="ner.eu-pii-ner",
                score=round(score, 3),
                category="pii",
            )
        )
    return out


async def ner_spans(
    engine: Any,
    text: str,
    *,
    entities: set[str] | None = None,
    timeout_s: float = 0.4,
    heuristic: bool = True,
) -> tuple[list[Span], bool]:
    """(spans, degraded). Never raises; falls back to heuristics."""
    st = _state(engine)
    st["calls"] += 1
    want = None if entities is None else set(entities) & E.NER_ENTITIES | (set(entities) & {"DOB"})
    heur = heuristic_spans(text, want) if heuristic else []
    if _semantic_mode(engine) == "off":
        st.update(backend="heuristic", loaded=False, degraded=True, reason="AEGIS_SEMANTIC=off")
        st["fallbacks"] += 1
        return heur, True
    labels = None
    if want is not None:
        labels = sorted({lab for e in want for lab in ENTITY_TO_LABELS.get(e, [])})
    t0 = time.perf_counter()
    raw: dict[str, Any] | None = None
    sem = getattr(getattr(engine, "rt", None), "semantic", None)
    sem_ner = getattr(sem, "ner", None)
    try:
        if callable(sem_ner):
            st["backend"] = "semantic"
            raw = await asyncio.wait_for(
                sem_ner(text, labels=labels, min_scores=LABEL_MIN_SCORE, timeout_s=timeout_s),
                timeout=timeout_s + 0.05,
            )
        else:
            own = _own(engine)
            if own is not None:
                st["backend"] = "own"
                raw = await asyncio.wait_for(
                    asyncio.to_thread(own.detect_dict, text, labels), timeout=timeout_s
                )
    except TimeoutError:
        st.update(degraded=True, reason="timeout")
        raw = None
    except Exception as exc:  # model errors -> heuristic
        st.update(degraded=True, reason=f"error: {type(exc).__name__}")
        raw = None
    if raw is None:
        st.update(loaded=False, degraded=True)
        st["fallbacks"] += 1
        if st.get("reason") in (None, "not used yet"):
            st["reason"] = "NER unavailable"
        return heur, True
    st.update(
        loaded=True,
        degraded=False,
        reason=None,
        last_ms=round((time.perf_counter() - t0) * 1000, 2),
    )
    model = _map_model_spans(raw, want)
    merged = list(model)
    for h in heur:
        if not any(h.start < m.end and m.start < h.end for m in merged):
            merged.append(h)
    return merged, False


def ner_status(engine: Any) -> dict[str, Any]:
    st = dict(_state(engine))
    st["mode"] = _semantic_mode(engine)
    own = getattr(engine, "_ner", None)
    if own is not None:
        st["own"] = own.status()
    return st


# ====================================================================== own session (fallback)


def _own(engine: Any) -> PiiNerService | None:
    """Own NER session only when rt.semantic cannot host it (never two sessions)."""
    svc = getattr(engine, "_ner", None)
    if svc is not None:
        return svc if svc.ready() else None
    settings = getattr(engine, "settings", None)
    models_dir = Path(getattr(settings, "models_dir", "models"))
    model_dir = models_dir / MODEL_DIR_NAME
    if not (model_dir / MODEL_FILE).exists():
        return None
    try:
        import psutil

        if psutil.virtual_memory().available < MIN_FREE_MB * 1024 * 1024:
            log.warning("ner own-load skipped: available RAM below %d MB", MIN_FREE_MB)
            return None
    except Exception:
        pass
    svc = PiiNerService(model_dir)
    engine._ner = svc
    svc.load_background()
    return None  # warming; heuristics until loaded


class PiiNerService:
    """Lazy background-loaded PiiNer (port of staging/models/ner_pii.py), 1-slot lock."""

    def __init__(self, model_dir: Path) -> None:
        self.model_dir = model_dir
        self._ner: Any = None
        self._lock = threading.Lock()
        self._loading = False
        self.load_ms: float | None = None
        self.error: str | None = None

    @property
    def loaded(self) -> bool:
        return self._ner is not None

    def ready(self) -> bool:
        return self._ner is not None

    def load_background(self) -> None:
        if self._loading or self._ner is not None:
            return
        self._loading = True
        threading.Thread(target=self._load, name="aegis-ner-load", daemon=True).start()

    def _load(self) -> None:
        t0 = time.perf_counter()
        try:
            self._ner = _PiiNer(self.model_dir)
            self.load_ms = round((time.perf_counter() - t0) * 1000, 1)
            log.info("ner model loaded model=eu-pii-ner ms=%.0f", self.load_ms)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            log.warning("ner model load failed: %s", self.error)
        finally:
            self._loading = False

    def detect_dict(self, text: str, labels: list[str] | None = None) -> dict[str, Any] | None:
        ner = self._ner
        if ner is None:
            return None
        with self._lock:
            spans = ner.detect(text, set(labels) if labels else None)
        return {"model": "eu-pii-ner", "spans": spans, "truncated": False}

    def detect_sync(self, text: str, entities: set[str] | None = None) -> list[Span]:
        labels = None
        if entities is not None:
            labels = [lab for e in entities for lab in ENTITY_TO_LABELS.get(e, [])]
        return _map_model_spans(self.detect_dict(text, labels), entities)

    def status(self) -> dict[str, Any]:
        return {"loaded": self.loaded, "load_ms": self.load_ms, "error": self.error}

    def close(self) -> None:
        self._ner = None


class _PiiNer:
    """Minimal port of staged PiiNer: spans as dicts WITHOUT text (privacy; caller slices)."""

    def __init__(self, model_dir: Path, threads: int = 2, max_len: int = 512, stride: int = 64):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        cfg = json.loads((model_dir / "config.json").read_text())
        self.id2label = {int(k): v for k, v in cfg["id2label"].items()}
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        so.enable_cpu_mem_arena = False
        so.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(model_dir / MODEL_FILE), so, providers=["CPUExecutionProvider"]
        )
        tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        tok.no_padding()
        tok.enable_truncation(max_length=max_len, stride=stride)
        self.tok = tok

    def detect(self, text: str, labels: set[str] | None = None) -> list[dict[str, Any]]:
        import numpy as np

        if not text.strip():
            return []
        enc = self.tok.encode(text)
        found: list[list[Any]] = []
        for w in [enc, *enc.overflowing]:
            ids = np.asarray([w.ids], dtype=np.int64)
            logits = self.session.run(None, {"input_ids": ids, "attention_mask": np.ones_like(ids)})
            lg = logits[0][0]
            lg = lg - lg.max(axis=-1, keepdims=True)
            p = np.exp(lg)
            p = p / p.sum(axis=-1, keepdims=True)
            best, conf = p.argmax(-1), p.max(-1)
            cur: list[Any] | None = None
            prev = None
            for i, wid in enumerate(w.word_ids):
                if wid is None or w.special_tokens_mask[i]:
                    prev = None
                    continue
                s, e = w.offsets[i]
                if wid == prev and cur is not None:
                    cur[2] = max(cur[2], e)
                    continue
                prev = wid
                lab = self.id2label[int(best[i])]
                if lab == "O":
                    if cur:
                        found.append(cur)
                    cur = None
                    continue
                tag, ent = lab[:2], lab[2:]
                if tag == "I-" and cur and cur[0] == ent:
                    cur[2] = e
                    cur[3].append(float(conf[i]))
                else:
                    if cur:
                        found.append(cur)
                    cur = [ent, s, e, [float(conf[i])]]
            if cur:
                found.append(cur)
        out: list[dict[str, Any]] = []
        for ent, s, e, confs in found:
            while s < e and text[s] in " \t\n,;:\"'":
                s += 1
            while e > s and text[e - 1] in " \t\n,;:.\"'":
                e -= 1
            if e <= s:
                continue
            if ent == "LOCATION" and any(ch.isdigit() for ch in text[s:e]):
                ent = "POSTAL_ADDRESS"
            score = float(sum(confs) / len(confs))
            if score < LABEL_MIN_SCORE.get(ent, 0.5):
                continue
            if labels is not None and ent not in labels:
                continue
            out.append({"label": ent, "start": s, "end": e, "score": score})
        return out
