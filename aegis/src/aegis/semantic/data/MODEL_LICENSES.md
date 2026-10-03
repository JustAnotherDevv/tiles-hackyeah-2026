# Model licences and attribution

All models run locally (ONNX Runtime CPU in-process, or the local Ollama server). Weights are
downloaded by `scripts/fetch_models.sh` from pinned commits and are never committed.

| Slot | Model (pinned source) | Licence | Default |
|---|---|---|---|
| `horizon-small` | Horizon-Labs/prompt-injection-guard-small v2, int8 ONNX (`@3215a27e`) | Apache-2.0 | on |
| `minilm-l12-multi` | sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2, qint8 arm64 ONNX (`@e8f8c211`) | Apache-2.0 | on |
| `eu-pii-ner` | bardsai/eu-pii-anonimization-multilang, int8 ONNX (`@0e72e19f`) | Apache-2.0 | on |
| `aegis-guard` | Qwen/Qwen3Guard-Gen-0.6B (QuantFactory Q4_K_M GGUF; Ollama alias) | Apache-2.0 | on |
| `aegis-judge` | Qwen/Qwen3.5-0.8B (unsloth Q4_K_M GGUF; Ollama alias) | Apache-2.0 | on demand |
| `pg2-22m` | meta-llama/Llama-Prompt-Guard-2-22M (gravitee-io int8 ONNX mirror, `@da68d0f6`) | Llama 4 Community License | **off** |

**Built with Llama.** If `pg2-22m` is enabled (`AEGIS_SEMANTIC_MODELS=...,pg2-22m`), Llama Prompt
Guard 2 is distributed under the Llama 4 Community License Agreement; "Built with Llama" must be
displayed and the licence terms apply. It is disabled by default.

The deterministic heuristic fallback (`heuristic`) is original Aegis code (project licence).
