"""ONNX Runtime backends (CPU EP, no torch): prompt-injection classifiers + EU-PII NER.

Ported from staging/models/{pi_classifier,ner_pii}.py. Imported lazily by the model manager
(never at gateway import time). All methods are synchronous and run in the "aegis-sem" executor;
ORT sessions release the GIL and are safe for concurrent ``run`` calls.

- ``PromptInjectionClassifier``: Horizon-Labs prompt-injection-guard-small v2 (multilingual,
  direct + indirect; its obfuscation normaliser is baked into tokenizer.json) and optional
  Llama Prompt Guard 2 22M. Max P(injection) over 512-token windows (stride 64), capped to
  head + tail windows so a huge tool result cannot stall the executor.
- ``PiiNer``: bardsai/eu-pii-anonimization-multilang (XLM-R, INT8), 24 EU languages incl. Polish.
  Returns spans ``{label, start, end, score}`` WITHOUT the matched text (privacy; callers slice).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from aegis.semantic.shared import load_tokenizer


@dataclass(frozen=True)
class PIModelSpec:
    name: str
    model_file: str
    tokenizer_file: str = "tokenizer.json"
    positive_idx: int = 1  # index of the INJECTION / MALICIOUS logit (config.json id2label)
    max_len: int = 512
    stride: int = 64
    licence: str = ""


PI_SPECS: dict[str, PIModelSpec] = {
    # id2label {0: SAFE, 1: INJECTION}
    "horizon-small": PIModelSpec("horizon-small", "model_quantized.onnx", licence="Apache-2.0"),
    # id2label {0: BENIGN, 1: MALICIOUS}
    "pg2-22m": PIModelSpec(
        "pg2-22m", "model.quant.onnx", licence="Llama 4 Community License (Built with Llama)"
    ),
}


def make_session(path: str | Path, threads: int = 2) -> Any:
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.enable_cpu_mem_arena = False  # lower steady RSS; negligible latency cost here
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    so.log_severity_level = 3
    return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x - x.max(axis=-1, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=-1, keepdims=True)


class PromptInjectionClassifier:
    def __init__(
        self, spec: PIModelSpec, model_dir: str | Path, threads: int = 2, max_windows: int = 2
    ) -> None:
        d = Path(model_dir)
        self.spec = spec
        self.max_windows = max(1, max_windows)
        self.session = make_session(d / spec.model_file, threads)
        self._inputs = {i.name for i in self.session.get_inputs()}
        tok = load_tokenizer(d / spec.tokenizer_file)
        tok.no_padding()
        tok.enable_truncation(max_length=spec.max_len, stride=spec.stride)
        self.tok = tok

    @classmethod
    def load(
        cls, name: str, model_dir: str | Path, threads: int = 2, max_windows: int = 2
    ) -> PromptInjectionClassifier:
        return cls(PI_SPECS[name], model_dir, threads, max_windows)

    def _windows(self, text: str) -> list[Any]:
        enc = self.tok.encode(text)
        wins = [enc, *enc.overflowing]
        if len(wins) > self.max_windows:
            head = self.max_windows // 2 or 1
            tail = self.max_windows - head
            wins = wins[:head] + (wins[-tail:] if tail else [])
        return wins

    def _run(self, ids: list[list[int]]) -> np.ndarray:
        n = max(len(x) for x in ids)
        input_ids = np.zeros((len(ids), n), dtype=np.int64)  # pad id irrelevant: masked out
        mask = np.zeros((len(ids), n), dtype=np.int64)
        for r, x in enumerate(ids):
            input_ids[r, : len(x)] = x
            mask[r, : len(x)] = 1
        feeds = {"input_ids": input_ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feeds["token_type_ids"] = np.zeros_like(input_ids)
        logits = self.session.run(None, {k: v for k, v in feeds.items() if k in self._inputs})[0]
        return _softmax(logits.astype(np.float32))[:, self.spec.positive_idx]

    def score_detail(self, text: str) -> tuple[float, int]:
        """(P(injection) max over windows, number of windows scored)."""
        wins = self._windows(text or " ")
        probs = self._run([w.ids for w in wins])
        return float(probs.max()), len(wins)

    def score(self, text: str) -> float:
        return self.score_detail(text)[0]


# ---------------------------------------------------------------- NER
NER_MODEL_FILE = "model_quantized.onnx"
DEFAULT_MIN_SCORE = 0.50
LABEL_MIN_SCORE: dict[str, float] = {
    "PERSON_NAME": 0.55,
    "LOCATION": 0.60,
    "ORGANIZATION_NAME": 0.60,
    "FINANCIAL_AMOUNT": 0.60,
    "HEALTH_DATA": 0.30,
    "RELIGION_OR_BELIEF": 0.30,
    "POLITICAL_OPINION": 0.30,
    "SEXUAL_ORIENTATION": 0.30,
    "ETHNIC_ORIGIN": 0.30,
    "TRADE_UNION_MEMBERSHIP": 0.30,
    "BIOMETRIC_DATA": 0.30,
    "CRIMINAL_OFFENCE_DATA": 0.30,
}
PII_LABELS = frozenset(
    {
        "PERSON_NAME",
        "PERSON_ALIAS",
        "POSTAL_ADDRESS",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CONTACT_HANDLE",
        "PAYMENT_CARD",
        "PAYMENT_CARD_SECURITY",
        "BANK_ACCOUNT_IDENTIFIER",
        "ACCOUNT_IDENTIFIER",
        "DOCUMENT_IDENTIFIER",
        "PERSON_IDENTIFIER",
        "DATE_OF_BIRTH",
        "IP_ADDRESS",
        "DEVICE_IDENTIFIER",
        "VEHICLE_IDENTIFIER",
        "AUTH_SECRET",
        "GEO_LOCATION",
        "IDENTIFYING_LINK",
    }
)
SPECIAL_CATEGORY_LABELS = frozenset(
    {  # GDPR Art. 9 / 10
        "HEALTH_DATA",
        "BIOMETRIC_DATA",
        "RELIGION_OR_BELIEF",
        "POLITICAL_OPINION",
        "SEXUAL_ORIENTATION",
        "ETHNIC_ORIGIN",
        "TRADE_UNION_MEMBERSHIP",
        "CRIMINAL_OFFENCE_DATA",
    }
)

_OPEN_FOR = {")": "(", "]": "[", "}": "{"}


@dataclass
class NerSpan:
    label: str
    start: int
    end: int
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "score": round(self.score, 4),
        }


class PiiNer:
    def __init__(
        self,
        model_dir: str | Path,
        threads: int = 2,
        max_len: int = 512,
        stride: int = 64,
        tokenizer: Any = None,
    ) -> None:
        """``tokenizer``: a prepared tokenizer (e.g. the shared-vocab one); default: standalone."""
        d = Path(model_dir)
        cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
        self.id2label = {int(k): v for k, v in cfg["id2label"].items()}
        self.session = make_session(d / NER_MODEL_FILE, threads)
        tok = tokenizer if tokenizer is not None else load_tokenizer(d / "tokenizer.json")
        tok.no_padding()
        tok.enable_truncation(max_length=max_len, stride=stride)
        self.tok = tok

    @property
    def labels(self) -> list[str]:
        return sorted({lab[2:] for lab in self.id2label.values() if lab != "O"})

    def _infer(self, ids: list[int]) -> np.ndarray:
        a = np.asarray([ids], dtype=np.int64)
        logits = self.session.run(None, {"input_ids": a, "attention_mask": np.ones_like(a)})[0][0]
        logits = logits - logits.max(axis=-1, keepdims=True)
        p = np.exp(logits)
        return p / p.sum(axis=-1, keepdims=True)

    def _decode_window(self, text: str, enc: Any) -> list[NerSpan]:
        probs = self._infer(enc.ids)
        best = probs.argmax(-1)
        conf = probs.max(-1)
        word_ids, offsets, special = enc.word_ids, enc.offsets, enc.special_tokens_mask
        words: list[list[Any]] = []  # [label, start, end, confs, label_idx]
        prev_wid = None
        for i, wid in enumerate(word_ids):
            if wid is None or special[i]:
                prev_wid = None
                continue
            s, e = offsets[i]
            if wid == prev_wid and words:
                words[-1][2] = max(words[-1][2], e)
                words[-1][3].append(float(probs[i, words[-1][4]]))
            else:
                words.append([self.id2label[int(best[i])], s, e, [float(conf[i])], int(best[i])])
            prev_wid = wid
        spans: list[list[Any]] = []
        cur: list[Any] | None = None
        for lab, s, e, confs, _ in words:
            if lab == "O":
                if cur:
                    spans.append(cur)
                cur = None
                continue
            tag, ent = lab[:2], lab[2:]
            if tag == "I-" and cur and cur[0] == ent:
                cur[2] = e
                cur[3].extend(confs)
            else:
                if cur:
                    spans.append(cur)
                cur = [ent, s, e, list(confs)]
        if cur:
            spans.append(cur)
        out: list[NerSpan] = []
        for ent, s, e, confs in spans:
            while s < e and text[s] in " \t\n,;:\"'":
                s += 1
            while e > s and (
                text[e - 1] in " \t\n,;:.\"'"
                or (text[e - 1] in _OPEN_FOR and _OPEN_FOR[text[e - 1]] not in text[s:e])
            ):
                e -= 1
            if e <= s:
                continue
            if ent == "LOCATION" and any(ch.isdigit() for ch in text[s:e]):
                ent = "POSTAL_ADDRESS"  # the model tags street addresses as LOCATION
            out.append(NerSpan(ent, s, e, float(np.mean(confs))))
        return out

    def detect_raw(self, text: str) -> list[NerSpan]:
        """Every span with its score (no thresholds, no label filter)."""
        if not text or not text.strip():
            return []
        enc = self.tok.encode(text)
        spans: list[NerSpan] = []
        for w in [enc, *enc.overflowing]:
            spans.extend(self._decode_window(text, w))
        return merge_spans(spans)


def merge_spans(spans: list[NerSpan]) -> list[NerSpan]:
    """Dedupe overlapping spans from overlapping windows (keep longer, then higher score)."""
    spans = sorted(spans, key=lambda s: (s.start, -(s.end - s.start), -s.score))
    out: list[NerSpan] = []
    for s in spans:
        if out and s.start < out[-1].end:
            o = out[-1]
            if s.label == o.label:
                o.end = max(o.end, s.end)
                o.score = max(o.score, s.score)
            elif (s.end - s.start, s.score) > (o.end - o.start, o.score):
                out[-1] = s
            continue
        out.append(s)
    return out


def filter_spans(
    spans: list[NerSpan],
    *,
    labels: set[str] | frozenset[str] | None = None,
    min_scores: dict[str, float] | None = None,
    default_min: float = DEFAULT_MIN_SCORE,
) -> list[NerSpan]:
    thresholds = dict(LABEL_MIN_SCORE)
    if min_scores:
        thresholds.update(min_scores)
    return [
        s
        for s in spans
        if (labels is None or s.label in labels) and s.score >= thresholds.get(s.label, default_min)
    ]


__all__ = [
    "DEFAULT_MIN_SCORE",
    "LABEL_MIN_SCORE",
    "PII_LABELS",
    "PI_SPECS",
    "SPECIAL_CATEGORY_LABELS",
    "NerSpan",
    "PIModelSpec",
    "PiiNer",
    "PromptInjectionClassifier",
    "filter_spans",
    "make_session",
    "merge_spans",
]
