"""Prompt-injection / jailbreak encoder classifiers on ONNX Runtime (no torch).

Supported models (download with download_models.sh, see RESULTS.md):

  horizon-small  Horizon-Labs/prompt-injection-guard-small v2 (mmBERT-small, 141M, int8)
                 multilingual incl. Polish, direct + indirect injection; obfuscation
                 normalizer (tag chars, NFKC, zero-width) is BAKED INTO tokenizer.json.
  pg2-22m        Llama Prompt Guard 2 22M (int8 ONNX, gravitee-io mirror). High-precision
                 "explicit jailbreak" vote; very conservative, use a low threshold.
                 Llama 4 Community License: keep "Built with Llama" attribution.
  protectai-v2   protectai/deberta-v3-base-prompt-injection-v2 (fp32, optional fallback, EN only).

Usage:
    from pi_classifier import PromptInjectionClassifier
    clf = PromptInjectionClassifier.load("horizon-small", "models/pi-horizon-small")
    clf.score("Ignore all previous instructions")        # -> 0.99 (P(injection), max over chunks)
    clf.classify("...", threshold=0.5)                    # -> PIResult(label, score, chunks, ms)

Thread-safe for concurrent `score()` calls (ORT sessions are; the tokenizer is used read-only).
Long inputs are split into overlapping windows of `max_len` tokens and the max score is used.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer


@dataclass(frozen=True)
class PIModelSpec:
    name: str
    model_file: str
    tokenizer_file: str = "tokenizer.json"
    positive_idx: int = 1          # index of the INJECTION/MALICIOUS logit (check config.json id2label!)
    max_len: int = 512             # tokens per window (incl. special tokens)
    stride: int = 64               # token overlap between windows
    default_threshold: float = 0.5
    licence: str = ""


SPECS: dict[str, PIModelSpec] = {
    # id2label {0: SAFE, 1: INJECTION}; model supports 8k ctx, tokenizer.json truncates at 1024.
    "horizon-small": PIModelSpec("horizon-small", "model_quantized.onnx", positive_idx=1,
                                 max_len=512, stride=64, default_threshold=0.5, licence="Apache-2.0"),
    # id2label {0: BENIGN, 1: MALICIOUS}
    "pg2-22m": PIModelSpec("pg2-22m", "model.quant.onnx", positive_idx=1,
                           max_len=512, stride=64, default_threshold=0.3,
                           licence="Llama 4 Community License (Built with Llama)"),
    # id2label {0: SAFE, 1: INJECTION}
    "protectai-v2": PIModelSpec("protectai-v2", "model.onnx", positive_idx=1,
                                max_len=512, stride=64, default_threshold=0.9, licence="Apache-2.0"),
}


@dataclass
class PIResult:
    label: str          # "injection" | "benign"
    score: float        # P(injection), max over windows
    chunks: int
    ms: float


def make_session(path: str | Path, threads: int = 2) -> ort.InferenceSession:
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.enable_cpu_mem_arena = False          # lower steady RSS; negligible latency cost here
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    so.log_severity_level = 3
    return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x - x.max(axis=-1, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=-1, keepdims=True)


class PromptInjectionClassifier:
    def __init__(self, spec: PIModelSpec, model_dir: str | Path, threads: int = 2):
        d = Path(model_dir)
        self.spec = spec
        self.session = make_session(d / spec.model_file, threads)
        self._inputs = {i.name for i in self.session.get_inputs()}
        tok = Tokenizer.from_file(str(d / spec.tokenizer_file))
        tok.no_padding()
        tok.enable_truncation(max_length=spec.max_len, stride=spec.stride)
        self.tok = tok

    @classmethod
    def load(cls, name: str, model_dir: str | Path, threads: int = 2) -> "PromptInjectionClassifier":
        return cls(SPECS[name], model_dir, threads)

    def _windows(self, text: str):
        enc = self.tok.encode(text)
        return [enc, *enc.overflowing]

    def _run(self, ids: list[list[int]]) -> np.ndarray:
        """ids: list of token-id lists (one per window); returns P(positive) per window."""
        n = max(len(x) for x in ids)
        input_ids = np.zeros((len(ids), n), dtype=np.int64)    # pad id irrelevant: masked out
        mask = np.zeros((len(ids), n), dtype=np.int64)
        for r, x in enumerate(ids):
            input_ids[r, : len(x)] = x
            mask[r, : len(x)] = 1
        feeds = {"input_ids": input_ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feeds["token_type_ids"] = np.zeros_like(input_ids)
        logits = self.session.run(None, {k: v for k, v in feeds.items() if k in self._inputs})[0]
        return _softmax(logits.astype(np.float32))[:, self.spec.positive_idx]

    def score(self, text: str) -> float:
        """P(injection) in [0,1]; max over overlapping windows."""
        return self.score_detail(text)[0]

    def score_detail(self, text: str) -> tuple[float, int]:
        wins = self._windows(text or " ")
        probs = self._run([w.ids for w in wins])
        return float(probs.max()), len(wins)

    def score_batch(self, texts: list[str]) -> list[float]:
        """Batch of short texts (each truncated to one window)."""
        if not texts:
            return []
        encs = self.tok.encode_batch([t or " " for t in texts])
        return [float(p) for p in self._run([e.ids for e in encs])]

    def classify(self, text: str, threshold: float | None = None) -> PIResult:
        t0 = time.perf_counter()
        s, n = self.score_detail(text)
        thr = self.spec.default_threshold if threshold is None else threshold
        return PIResult("injection" if s >= thr else "benign", s, n, (time.perf_counter() - t0) * 1e3)


class PIEnsemble:
    """Recommended combination: Horizon (recall, multilingual, indirect) OR PG2 (explicit jailbreak).

    verdict = block      if horizon >= block_thr or pg2 >= pg2_thr
              review     if horizon in [review_thr, block_thr)    -> escalate to Qwen3Guard / judge
              allow      otherwise
    """

    def __init__(self, horizon: PromptInjectionClassifier, pg2: PromptInjectionClassifier | None = None,
                 block_thr: float = 0.5, review_thr: float = 0.2, pg2_thr: float = 0.3):
        self.horizon, self.pg2 = horizon, pg2
        self.block_thr, self.review_thr, self.pg2_thr = block_thr, review_thr, pg2_thr

    def evaluate(self, text: str) -> dict:
        h = self.horizon.score(text)
        p = self.pg2.score(text) if self.pg2 else 0.0
        if h >= self.block_thr or p >= self.pg2_thr:
            verdict = "block"
        elif h >= self.review_thr:
            verdict = "review"
        else:
            verdict = "allow"
        return {"verdict": verdict, "horizon": round(h, 4), "pg2": round(p, 4)}


if __name__ == "__main__":  # quick manual check:  python pi_classifier.py models/pi-horizon-small "text"
    import sys
    name = "pg2-22m" if "pg2" in sys.argv[1] else "protectai-v2" if "protectai" in sys.argv[1] else "horizon-small"
    clf = PromptInjectionClassifier.load(name, sys.argv[1])
    for t in sys.argv[2:]:
        print(clf.classify(t), t[:80])
