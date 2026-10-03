"""Semantic runtime configuration: model slot table + SemanticConfig.from_settings().

Numbers are the measured ones from staging/models/RESULTS.md (Apple M2, 8 GB, ORT 1.30,
Ollama 0.24): Horizon p50 14 ms / 0.40 GB, MiniLM 3 ms / 0.15 GB (+ shared XLM-R vocab),
NER 13 ms / 0.35 GB, Qwen3Guard 223 ms / 0.75 GB, Qwen3.5 judge 315 ms per rule / 1.32 GB.
No I/O and no heavy imports here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

Backend = Literal["onnx", "ollama", "tokenizers", "python"]
SemanticMode = Literal["auto", "on", "off"]


@dataclass(frozen=True)
class ModelSpec:
    name: str
    role: str
    backend: Backend
    est_mb: int
    subdir: str = ""  # under models_dir (onnx / tokenizers)
    files: tuple[str, ...] = ()  # files that must exist (relative to subdir)
    tag: str = ""  # Ollama model tag
    timeout_ms: int = 0
    resident: bool = True  # False = on demand (judge)
    required: bool = False  # counts for health "ok"
    licence: str = "Apache-2.0"


MODEL_SPECS: dict[str, ModelSpec] = {
    "horizon-small": ModelSpec(
        "horizon-small",
        "injection",
        "onnx",
        400,
        "pi-horizon-small",
        ("model_quantized.onnx", "tokenizer.json"),
        timeout_ms=300,
        required=True,
    ),
    "pg2-22m": ModelSpec(
        "pg2-22m",
        "injection_vote",
        "onnx",
        260,
        "pg2-22m",
        ("model.quant.onnx", "tokenizer.json"),
        timeout_ms=150,
        licence="Llama 4 Community License (Built with Llama)",
    ),
    "xlmr-vocab": ModelSpec(
        "xlmr-vocab",
        "tokenizer",
        "tokenizers",
        300,
        "minilm-l12-multi",
        ("tokenizer.json",),
    ),
    "minilm-l12-multi": ModelSpec(
        "minilm-l12-multi",
        "embeddings",
        "onnx",
        150,
        "minilm-l12-multi",
        ("model_qint8_arm64.onnx", "tokenizer.json"),
        timeout_ms=200,
        required=True,
    ),
    "eu-pii-ner": ModelSpec(
        "eu-pii-ner",
        "ner",
        "onnx",
        350,
        "eu-pii-ner",
        ("model_quantized.onnx", "tokenizer.json", "config.json"),
        timeout_ms=400,
        required=True,
    ),
    "aegis-guard": ModelSpec(
        "aegis-guard",
        "moderation",
        "ollama",
        750,
        tag="aegis-guard",
        timeout_ms=700,
        required=True,
    ),
    "aegis-judge": ModelSpec(
        "aegis-judge",
        "judge",
        "ollama",
        1320,
        tag="aegis-judge",
        timeout_ms=2000,
        resident=False,
    ),
    "heuristic": ModelSpec("heuristic", "fallback", "python", 0),
}

#: RAM plan priority (first = most important). The vocab rides along with minilm / ner.
LOAD_ORDER: tuple[str, ...] = (
    "horizon-small",
    "xlmr-vocab",
    "minilm-l12-multi",
    "eu-pii-ner",
    "aegis-guard",
    "pg2-22m",
)
#: Shedding order under live memory pressure (first = shed first).
SHED_ORDER: tuple[str, ...] = ("pg2-22m", "aegis-judge", "aegis-guard")

DEFAULT_MODELS = "horizon-small,minilm-l12-multi,eu-pii-ner,aegis-guard,aegis-judge"

#: Golden XLM-R token ids of a probe string, produced once with the STANDALONE
#: models/eu-pii-ner/tokenizer.json (tests/unit/semantic_models/test_models_live.py re-checks
#: it). At load time the shared-vocab NER tokenizer must reproduce them exactly, otherwise the
#: engine falls back to an unshared tokenizer and logs a WARNING.
XLMR_PROBE = "Nazywam się Jan Kowalski, mieszkam w Krakowie. Project Falcon, zażółć gęślą jaźń!"
XLMR_PROBE_IDS: tuple[int, ...] = (
    0,
    63654,
    63109,
    39,
    410,
    3342,
    1204,
    8202,
    1336,
    4,
    39089,
    39,
    148,
    139801,
    5,
    27331,
    160378,
    4,
    80,
    138371,
    1032,
    6,
    68322,
    3124,
    35091,
    79,
    17469,
    6419,
    38,
    2,
)


class Timeouts(BaseModel):
    injection_ms: int = 300
    moderate_ms: int = 700
    embed_ms: int = 200
    similarity_ms: int = 250
    judge_ms: int = 2000
    ner_ms: int = 400


class Caps(BaseModel):
    injection_chars: int = 8_000  # head 4k + tail 4k
    injection_windows: int = 2
    guard_chars: int = 6_000
    judge_chars: int = 4_000
    ner_chars: int = 20_000
    embed_chars: int = 4_000


class SemanticConfig(BaseModel):
    mode: SemanticMode = "auto"
    test_mode: bool = False
    models_dir: Path = Path("models")
    ollama_url: str = "http://127.0.0.1:11434"
    enabled: list[str] = Field(default_factory=lambda: DEFAULT_MODELS.split(","))
    ram_budget_mb: int = 2048
    ram_headroom_mb: int = 400  # psutil available must exceed est_mb + this to load a slot
    judge_min_available_mb: int = 1920  # 1320 + 600
    host_ner: bool = True
    onnx_threads: int = 2
    executor_workers: int = 3
    admission_limit: int = 8
    guard_keep_alive: str = "30m"
    judge_keep_alive: str = "2m"
    guard_queue_wait_ms: int = 400
    judge_queue_wait_ms: int = 1000
    guard_num_ctx: int = 2048
    guard_slow_p95_ms: float = 1200.0
    cache_ttl_s: float = 3600.0
    cache_size: int = 4096
    monitor_interval_s: float = 10.0
    keepalive_refresh_s: float = 600.0
    shed_below_mb: int = 600
    reload_above_mb: int = 1500
    unload_on_stop: bool = True
    verify_integrity: bool = True
    timeouts: Timeouts = Field(default_factory=Timeouts)
    caps: Caps = Field(default_factory=Caps)

    @property
    def off(self) -> bool:
        return self.mode == "off"

    def slot_enabled(self, name: str) -> bool:
        if name == "heuristic":
            return True
        if self.off:
            return False
        if name == "xlmr-vocab":
            return self.slot_enabled("minilm-l12-multi") or (
                self.host_ner and self.slot_enabled("eu-pii-ner")
            )
        if name == "eu-pii-ner" and not self.host_ner:
            return False
        return name in self.enabled

    @classmethod
    def from_settings(cls, settings: Any = None, **overrides: Any) -> SemanticConfig:
        """Build from aegis.settings.Settings (getattr defaults; CG-4 fields may be missing)."""
        values: dict[str, Any] = {}
        if settings is not None:
            mode = str(getattr(settings, "semantic", "auto") or "auto").strip().lower()
            values["mode"] = mode if mode in ("auto", "on", "off") else "auto"
            values["test_mode"] = bool(getattr(settings, "test_mode", False))
            md = getattr(settings, "models_dir", None)
            if md:
                values["models_dir"] = Path(md)
            url = getattr(settings, "ollama_url", None)
            if url:
                values["ollama_url"] = str(url).rstrip("/")
            # CG-4 (proposed Settings fields). TODO(integration): drop the env fallback once
            # aegis.settings.Settings has semantic_models / semantic_ram_mb.
            models = getattr(settings, "semantic_models", None) or os.environ.get(
                "AEGIS_SEMANTIC_MODELS"
            )
            if models:
                values["enabled"] = [m.strip() for m in str(models).split(",") if m.strip()]
            ram = getattr(settings, "semantic_ram_mb", None) or os.environ.get(
                "AEGIS_SEMANTIC_RAM_MB"
            )
            if ram:
                try:
                    values["ram_budget_mb"] = int(ram)
                except ValueError:
                    pass
        values.update(overrides)
        cfg = cls.model_validate(values)
        if not cfg.models_dir.is_absolute():
            root = Path(__file__).resolve().parents[3]
            cfg.models_dir = root / cfg.models_dir
        return cfg
