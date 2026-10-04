"""Multilingual PII NER (bardsai/eu-pii-anonimization-multilang, XLM-R base, INT8 ONNX, no torch).

24 EU languages incl. Polish; 35 entity types incl. GDPR Art. 9 categories (HEALTH_DATA,
RELIGION_OR_BELIEF, POLITICAL_OPINION, SEXUAL_ORIENTATION, ETHNIC_ORIGIN, ...).

    from ner_pii import PiiNer
    ner = PiiNer("models/eu-pii-ner")
    for s in ner.detect("Nazywam się Jan Kowalski, PESEL 44051401359."):
        print(s.label, s.start, s.end, s.text, round(s.score, 2))

Spans are character offsets into the ORIGINAL text (safe for in-place replacement).
Decoding: per-token softmax -> word-level label = label of the word's first sub-token ("first"
aggregation) -> BIO merge (a stray I-X after O starts a new X span) -> span score = mean token
confidence. Texts longer than 512 tokens are windowed (stride 64) and spans are merged.

This is the ML tier only. Structured IDs (PESEL/NIP/IBAN/PAN) must still be found/validated by the
deterministic tier (checksums); treat NER hits on those labels as corroboration, not proof.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_FILE = "model_quantized.onnx"

# Suggested per-label default min scores (tuned on the bench samples, see RESULTS.md).
DEFAULT_MIN_SCORE = 0.50
LABEL_MIN_SCORE: dict[str, float] = {
    "PERSON_NAME": 0.55,          # PL surnames that are common nouns (Wilk, Mróz) -> keep a bit higher
    "LOCATION": 0.60,             # a city alone is not personal data; policy usually doesn't redact it
    "ORGANIZATION_NAME": 0.60,
    "FINANCIAL_AMOUNT": 0.60,     # usually not PII; useful as metadata only
    # GDPR Art. 9 categories come out with low confidence (e.g. "katolikiem" 0.33) -> lower bar,
    # they are flagged/redacted as "sensitive context", false positives are cheap.
    "HEALTH_DATA": 0.30, "RELIGION_OR_BELIEF": 0.30, "POLITICAL_OPINION": 0.30, "SEXUAL_ORIENTATION": 0.30,
    "ETHNIC_ORIGIN": 0.30, "TRADE_UNION_MEMBERSHIP": 0.30, "BIOMETRIC_DATA": 0.30, "CRIMINAL_OFFENCE_DATA": 0.30,
}
# NOTE: structured identifiers (PESEL, NIP, ID card, passport, PAN, IBAN, IP, API keys) are usually
# typed correctly but with LOW confidence (0.1-0.3) -> leave them to the deterministic tier
# (regex + checksum) and use NER only as corroboration / for context-free names, addresses, Art. 9.

# Labels a redaction policy normally acts on (others are informational).
PII_LABELS = {
    "PERSON_NAME", "PERSON_ALIAS", "POSTAL_ADDRESS", "EMAIL_ADDRESS", "PHONE_NUMBER", "CONTACT_HANDLE",
    "PAYMENT_CARD", "PAYMENT_CARD_SECURITY", "BANK_ACCOUNT_IDENTIFIER", "ACCOUNT_IDENTIFIER",
    "DOCUMENT_IDENTIFIER", "PERSON_IDENTIFIER", "DATE_OF_BIRTH", "IP_ADDRESS", "DEVICE_IDENTIFIER",
    "VEHICLE_IDENTIFIER", "AUTH_SECRET", "GEO_LOCATION", "IDENTIFYING_LINK",
}
SPECIAL_CATEGORY_LABELS = {  # GDPR Art. 9 / 10
    "HEALTH_DATA", "BIOMETRIC_DATA", "RELIGION_OR_BELIEF", "POLITICAL_OPINION", "SEXUAL_ORIENTATION",
    "ETHNIC_ORIGIN", "TRADE_UNION_MEMBERSHIP", "CRIMINAL_OFFENCE_DATA",
}


@dataclass
class Span:
    label: str
    start: int
    end: int
    text: str
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


def load_tokenizer(path: str | Path, share_vocab_with: Tokenizer | None = None) -> Tokenizer:
    """Load tokenizer.json; optionally reuse the (identical) vocab model of another tokenizer.

    HF `tokenizers` keeps a 250k-piece Unigram model at ~200-330 MB RSS. MiniLM-L12-multilingual and
    bardsai NER both use the XLM-R vocab, so one copy can serve both: we load only the pipeline
    (normaliser / pre-tokenizer / post-processor / decoder) from `path` around the shared model.
    """
    if share_vocab_with is None:
        return Tokenizer.from_file(str(path))
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    n_vocab = len(cfg["model"].get("vocab", []))
    if share_vocab_with.get_vocab_size(with_added_tokens=False) != n_vocab:
        return Tokenizer.from_file(str(path))
    cfg["model"] = {"type": "Unigram", "unk_id": 0, "vocab": [["<unk>", 0.0]], "byte_fallback": False}  # dummy
    shell = Tokenizer.from_str(json.dumps(cfg))
    tok = Tokenizer(share_vocab_with.model)        # shares the Rust Arc, no copy
    tok.normalizer, tok.pre_tokenizer = shell.normalizer, shell.pre_tokenizer
    tok.post_processor, tok.decoder = shell.post_processor, shell.decoder
    return tok


def make_session(path: str | Path, threads: int = 2) -> ort.InferenceSession:
    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    so.enable_cpu_mem_arena = False
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    so.log_severity_level = 3
    return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])


class PiiNer:
    def __init__(self, model_dir: str | Path, threads: int = 2, max_len: int = 512, stride: int = 64,
                 min_score: float = DEFAULT_MIN_SCORE, label_min_score: dict[str, float] | None = None,
                 share_vocab_with: Tokenizer | None = None):
        """share_vocab_with: an already-loaded XLM-R Unigram tokenizer (e.g. Embedder.tok) whose
        250k-piece model is reused instead of loading a second copy (saves ~200-300 MB)."""
        d = Path(model_dir)
        cfg = json.loads((d / "config.json").read_text())
        self.id2label = {int(k): v for k, v in cfg["id2label"].items()}
        self.session = make_session(d / MODEL_FILE, threads)
        tok = load_tokenizer(d / "tokenizer.json", share_vocab_with)
        tok.no_padding()
        tok.enable_truncation(max_length=max_len, stride=stride)
        self.tok = tok
        self.min_score = min_score
        self.label_min_score = dict(LABEL_MIN_SCORE if label_min_score is None else label_min_score)

    @property
    def labels(self) -> list[str]:
        return sorted({l[2:] for l in self.id2label.values() if l != "O"})

    def _infer(self, ids: list[int]) -> np.ndarray:
        a = np.asarray([ids], dtype=np.int64)
        logits = self.session.run(None, {"input_ids": a, "attention_mask": np.ones_like(a)})[0][0]
        logits = logits - logits.max(axis=-1, keepdims=True)
        p = np.exp(logits)
        return p / p.sum(axis=-1, keepdims=True)           # (seq, n_labels)

    def _decode_window(self, text: str, enc) -> list[Span]:
        probs = self._infer(enc.ids)
        best = probs.argmax(-1)
        conf = probs.max(-1)
        word_ids = enc.word_ids
        offsets = enc.offsets
        special = enc.special_tokens_mask

        # word-level labels ("first" sub-token strategy); collect (label_str, start, end, [conf...])
        words: list[list] = []
        prev_wid = None
        for i, wid in enumerate(word_ids):
            if wid is None or special[i]:
                prev_wid = None
                continue
            s, e = offsets[i]
            if wid == prev_wid and words:
                words[-1][2] = max(words[-1][2], e)
                words[-1][3].append(float(probs[i, words[-1][4]]))   # P(word label) at this sub-token
            else:
                words.append([self.id2label[int(best[i])], s, e, [float(conf[i])], int(best[i])])
            prev_wid = wid

        spans: list[Span] = []
        cur = None  # [label, start, end, confs]
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

        out = []
        for ent, s, e, confs in spans:
            # trim whitespace / sentence punctuation that word offsets include ("Kraków." -> "Kraków")
            while s < e and text[s] in " \t\n,;:\"'":
                s += 1
            while e > s and (text[e - 1] in " \t\n,;:.\"'" or (text[e - 1] in ")]}" and "([{"[")]}".index(text[e - 1])] not in text[s:e])):
                e -= 1
            if e <= s:
                continue
            # the model tags street addresses as LOCATION; a LOCATION with digits is a postal address
            if ent == "LOCATION" and any(ch.isdigit() for ch in text[s:e]):
                ent = "POSTAL_ADDRESS"
            out.append(Span(ent, s, e, text[s:e], float(np.mean(confs))))
        return out

    def detect(self, text: str, labels: set[str] | None = None, apply_thresholds: bool = True) -> list[Span]:
        if not text or not text.strip():
            return []
        enc = self.tok.encode(text)
        spans: list[Span] = []
        for w in [enc, *enc.overflowing]:
            spans.extend(self._decode_window(text, w))
        spans = _merge(spans)
        if labels is not None:
            spans = [s for s in spans if s.label in labels]
        if apply_thresholds:
            spans = [s for s in spans if s.score >= self.label_min_score.get(s.label, self.min_score)]
        return spans

    def timed_detect(self, text: str, **kw) -> tuple[list[Span], float]:
        t0 = time.perf_counter()
        r = self.detect(text, **kw)
        return r, (time.perf_counter() - t0) * 1e3


def _merge(spans: list[Span]) -> list[Span]:
    """Dedupe overlapping spans from overlapping windows (keep longer, then higher score)."""
    spans = sorted(spans, key=lambda s: (s.start, -(s.end - s.start), -s.score))
    out: list[Span] = []
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


def redact(text: str, spans: list[Span], fmt: str = "[{label}_{n}]") -> tuple[str, dict[str, str]]:
    """Replace spans right-to-left with numbered placeholders; returns (redacted, vault)."""
    vault: dict[str, str] = {}
    counters: dict[str, int] = {}
    seen: dict[tuple[str, str], str] = {}
    keyed = []
    for s in sorted(spans, key=lambda s: s.start):
        key = (s.label, s.text)
        if key not in seen:
            counters[s.label] = counters.get(s.label, 0) + 1
            seen[key] = fmt.format(label=s.label, n=counters[s.label])
            vault[seen[key]] = s.text
        keyed.append((s, seen[key]))
    out = text
    for s, ph in sorted(keyed, key=lambda x: -x[0].start):
        out = out[: s.start] + ph + out[s.end:]
    return out, vault


if __name__ == "__main__":
    import sys
    ner = PiiNer(sys.argv[1])
    for t in sys.argv[2:]:
        spans, ms = ner.timed_detect(t)
        print(f"{ms:.1f} ms", redact(t, spans)[0])
        for s in spans:
            print("   ", s)
