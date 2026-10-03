"""PUBLIC import surface of semantic-models (proposed CG-1 / CG-7).

- ``FALLBACK_REASONS`` and ``degraded_disposition(result, fail_mode)``: one shared way for every
  semantic control (INJ-02, INJ-03, CUS-01, MCP-02, ...) to interpret a degraded ScoreResult.
- ``fallback_code(result)``: the ``<code>`` of ``reason == "fallback:<code>"`` (or None).
- internal to semantic-models (A-38): ``load_tokenizer(path, share_vocab_with=None)`` and
  ``xlmr_tokenizer()`` - ONE process-wide XLM-R Unigram vocab (250k pieces, ~300 MB) shared by
  MiniLM and the EU-PII NER. Other workstreams use ``rt.semantic.ner()`` instead.

``tokenizers`` is imported lazily (no import-time side effects).
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

#: ``ScoreResult.reason == "fallback:<code>"`` when ``degraded`` (CONTRACTS Addendum A-44).
FALLBACK_REASONS: dict[str, str] = {
    "off": "AEGIS_SEMANTIC=off or slot disabled by the operator (heuristic only)",
    "warming": "models still loading after startup",
    "missing": "model files / Ollama tag missing (run scripts/fetch_models.sh)",
    "skipped_budget": "not loaded: static RAM plan / available memory",
    "ram_budget": "not enough free RAM for an on-demand model",
    "timeout": "model call exceeded its timeout",
    "error": "model call or load failed (incl. integrity check)",
    "breaker_open": "circuit breaker open after repeated failures",
    "overload": "admission queue full",
    "queue": "Ollama queue wait exceeded",
}

#: Reasons that are an explicit operator choice or the first seconds after boot: the heuristic
#: decides and the decision is merely marked degraded (never fail-closed).
USE_HEURISTIC_REASONS = frozenset({"off", "warming"})

Disposition = Literal["use", "block", "allow"]
_FALLBACK_RE = re.compile(r"fallback:([a-z_]+)")


def fallback_code(result: Any) -> str | None:
    """'timeout' for reason 'fallback:timeout'; None when the result is not a fallback."""
    if result is None or not getattr(result, "degraded", False):
        return None
    m = _FALLBACK_RE.match(getattr(result, "reason", None) or "")
    return m.group(1) if m else "error"


def degraded_disposition(result: Any, fail_mode: str | None) -> Disposition:
    """How a control should treat ``result`` (CG-7).

    - not degraded, or reason in {off, warming} -> ``"use"`` (decide on the score)
    - otherwise ``fail_mode``: closed -> ``"block"``; open -> ``"allow"``;
      deterministic_only (default) -> ``"use"`` (the heuristic score decides).
    """
    code = fallback_code(result)
    if code is None or code in USE_HEURISTIC_REASONS:
        return "use"
    if fail_mode == "closed":
        return "block"
    if fail_mode == "open":
        return "allow"
    return "use"


# ---------------------------------------------------------------- shared XLM-R tokenizer
_lock = threading.Lock()
_xlmr: Any = None
_xlmr_path: Path | None = None


def load_tokenizer(path: str | Path, share_vocab_with: Any = None) -> Any:
    """Load ``tokenizer.json``; optionally reuse the identical vocab model of another tokenizer.

    Only the pipeline (normalizer / pre-tokenizer / post-processor / decoder) is read from
    ``path``; the 250k-piece Unigram model is the Rust Arc of ``share_vocab_with`` (no copy).
    Falls back to a standalone load when the vocab sizes differ.
    """
    from tokenizers import Tokenizer

    if share_vocab_with is None:
        return Tokenizer.from_file(str(path))
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    n_vocab = len(cfg["model"].get("vocab", []))
    if share_vocab_with.get_vocab_size(with_added_tokens=False) != n_vocab:
        log.warning("tokenizer vocab mismatch, loading unshared path=%s", Path(path).name)
        return Tokenizer.from_file(str(path))
    cfg["model"] = {
        "type": "Unigram",
        "unk_id": 0,
        "vocab": [["<unk>", 0.0]],
        "byte_fallback": False,
    }
    shell = Tokenizer.from_str(json.dumps(cfg))
    del cfg
    tok = Tokenizer(share_vocab_with.model)
    tok.normalizer, tok.pre_tokenizer = shell.normalizer, shell.pre_tokenizer
    tok.post_processor, tok.decoder = shell.post_processor, shell.decoder
    return tok


def xlmr_tokenizer(models_dir: str | Path | None = None) -> Any:
    """Process-wide XLM-R vocab owner (loaded once from minilm-l12-multi/tokenizer.json).

    Returns None when the file is missing or ``tokenizers`` is unavailable. Thread-safe.
    """
    global _xlmr, _xlmr_path
    if _xlmr is not None:
        return _xlmr
    with _lock:
        if _xlmr is not None:
            return _xlmr
        if models_dir is None:
            try:
                from aegis.settings import get_settings

                models_dir = get_settings().models_dir
            except Exception:
                models_dir = Path(__file__).resolve().parents[3] / "models"
        path = Path(models_dir) / "minilm-l12-multi" / "tokenizer.json"
        if not path.is_file():
            return None
        try:
            from tokenizers import Tokenizer

            _xlmr = Tokenizer.from_file(str(path))
            _xlmr_path = path
        except Exception as exc:
            log.warning("xlmr tokenizer load failed error=%s", type(exc).__name__)
            return None
        return _xlmr


def release_xlmr_tokenizer() -> None:
    """Drop the singleton reference (memory is freed once no tokenizer shares it)."""
    global _xlmr, _xlmr_path
    with _lock:
        _xlmr = None
        _xlmr_path = None


__all__ = [
    "FALLBACK_REASONS",
    "USE_HEURISTIC_REASONS",
    "degraded_disposition",
    "fallback_code",
    "load_tokenizer",
    "release_xlmr_tokenizer",
    "xlmr_tokenizer",
]
