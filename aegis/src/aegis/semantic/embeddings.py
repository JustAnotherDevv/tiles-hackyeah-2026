"""Multilingual sentence embeddings (paraphrase-multilingual-MiniLM-L12-v2, qint8 ONNX, 384-d).

Ported from staging/models/embedder.py. Pooling = attention-masked mean of last_hidden_state,
then L2-normalised (cosine = dot product). max_seq_length is 128 tokens, so long texts are split
into sentences (``embed_windows``): an injected sentence hidden in a 128-token window of benign
prose scores ~0.12 against attack exemplars, the same sentence alone ~0.6-0.8.

The tokenizer shares the XLM-R vocab with the NER (``aegis.semantic.shared``). Imported lazily
by the model manager; synchronous; runs in the "aegis-sem" executor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from aegis.semantic.onnx import make_session
from aegis.semantic.shared import load_tokenizer

MODEL_FILE = "model_qint8_arm64.onnx"  # model_quint8_avx2.onnx on x86 hosts
_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")


class Embedder:
    dim = 384

    def __init__(
        self,
        model_dir: str | Path,
        threads: int = 2,
        max_len: int = 128,
        stride: int = 32,
        model_file: str = MODEL_FILE,
        share_vocab_with: Any = None,
    ) -> None:
        d = Path(model_dir)
        self.session = make_session(d / model_file, threads)
        self._inputs = {i.name for i in self.session.get_inputs()}
        self.max_len = max_len
        tok = load_tokenizer(d / "tokenizer.json", share_vocab_with)
        tok.no_padding()
        tok.enable_truncation(max_length=max_len, stride=stride)
        self.tok = tok

    def _forward(self, ids: list[list[int]]) -> np.ndarray:
        n = max(len(x) for x in ids)
        input_ids = np.ones((len(ids), n), dtype=np.int64)  # 1 = <pad> in the XLM-R vocab
        mask = np.zeros((len(ids), n), dtype=np.int64)
        for r, x in enumerate(ids):
            input_ids[r, : len(x)] = x
            mask[r, : len(x)] = 1
        feeds = {
            "input_ids": input_ids,
            "attention_mask": mask,
            "token_type_ids": np.zeros_like(input_ids),
        }
        hidden = self.session.run(None, {k: v for k, v in feeds.items() if k in self._inputs})[0]
        m = mask[..., None].astype(np.float32)
        pooled = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
        pooled /= np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
        return pooled.astype(np.float32)

    def embed(self, texts: list[str] | str, batch_size: int = 32) -> np.ndarray:
        """One vector per text (first ``max_len`` tokens only) -> (n, 384)."""
        if isinstance(texts, str):
            texts = [texts]
        out = []
        for i in range(0, len(texts), batch_size):
            encs = self.tok.encode_batch([t or " " for t in texts[i : i + batch_size]])
            out.append(self._forward([e.ids for e in encs]))
        return np.vstack(out) if out else np.zeros((0, self.dim), np.float32)

    def embed_windows(self, text: str, max_segments: int = 32) -> np.ndarray:
        """Short text: one vector. Long text: one per sentence + the overlapping token windows."""
        enc = self.tok.encode(text or " ")
        if not enc.overflowing:
            return self._forward([enc.ids])
        sents = [x.strip() for x in _SENT_SPLIT.split(text) if len(x.strip()) > 3][:max_segments]
        wins = self._forward([w.ids for w in [enc, *enc.overflowing][:max_segments]])
        return np.vstack([self.embed(sents), wins]) if sents else wins

    def max_sim(self, text: str, ref_vecs: np.ndarray) -> float:
        """Max cosine between any window of ``text`` and any reference vector, clamped [0, 1]."""
        if ref_vecs.size == 0:
            return 0.0
        q = self.embed_windows(text)
        return float(max(0.0, min(1.0, float((q @ ref_vecs.T).max()))))


@dataclass
class Match:
    id: str
    label: str
    sim: float


class ExemplarIndex:
    """Brute-force cosine kNN over exemplar vectors (stores ids/labels, never exemplar text)."""

    def __init__(self, embedder: Embedder) -> None:
        self.emb = embedder
        self.vecs = np.zeros((0, embedder.dim), np.float32)
        self.meta: list[tuple[str, str]] = []

    def add(self, sig_id: str, label: str, texts: list[str]) -> None:
        v = self.emb.embed(texts)
        self.vecs = np.vstack([self.vecs, v])
        self.meta.extend((sig_id, label) for _ in texts)

    def search(self, text: str, k: int = 3, min_sim: float = 0.0) -> list[Match]:
        if not self.meta:
            return []
        sims = (self.emb.embed_windows(text) @ self.vecs.T).max(axis=0)
        top = np.argsort(-sims)[:k]
        return [Match(*self.meta[i], float(sims[i])) for i in top if sims[i] >= min_sim]


__all__ = ["MODEL_FILE", "Embedder", "ExemplarIndex", "Match"]
