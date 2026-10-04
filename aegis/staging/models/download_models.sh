#!/usr/bin/env bash
# Reproduce Aegis local model downloads (ungated sources only, pinned commits).
#
#   bash staging/models/download_models.sh            # ONNX encoders + Ollama models
#   SKIP_OLLAMA=1 bash staging/models/download_models.sh
#   WITH_PROTECTAI=1 bash ...                          # optional fallback PI model (+748 MB)
#   WITH_QWEN3=1 bash ...                              # optional fast demo-chat model qwen3:0.6b (+523 MB)
#
# Layout (relative to the aegis/ repo root, gitignored):
#   models/pi-horizon-small/   Horizon-Labs prompt-injection-guard-small v2, int8 ONNX  (~303 MB)
#   models/pg2-22m/            Llama Prompt Guard 2 22M, int8 ONNX (gravitee mirror)   (~81 MB)
#   models/minilm-l12-multi/   paraphrase-multilingual-MiniLM-L12-v2, qint8 arm64 ONNX  (~128 MB)
#   models/eu-pii-ner/         bardsai eu-pii-anonimization-multilang, int8 ONNX       (~296 MB)
#   models/qwen3guard/         Qwen3Guard-Gen-0.6B tokenizer_config.json (chat template ref only)
#   Ollama: hf.co/QuantFactory/Qwen3Guard-Gen-0.6B-GGUF:Q4_K_M (484 MB)
#           hf.co/unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M            (533 MB text + 204 MB unused mmproj)
#   Ollama aliases (no extra disk): aegis-guard (Modelfile.guard), aegis-judge (Modelfile.judge)
#
# Re-running is idempotent (curl -C - resumes, existing complete files are skipped).
# After download, models/MANIFEST.sha256 is (re)written; verify later with
#   (cd models && shasum -a 256 -c MANIFEST.sha256)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
M="${MODELS_DIR:-$ROOT/models}"
mkdir -p "$M"

HF="https://huggingface.co"

# repo@pinned-commit (2026-10-03). Bump deliberately, never float on "main".
HORIZON="Horizon-Labs/prompt-injection-guard-small@3215a27edd62c5ba0bd786c57a9d243b2158e70e"
PG2="gravitee-io/Llama-Prompt-Guard-2-22M-onnx@da68d0f6023c7aeaf6b256eec549de295d5e8740"
MINILM="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2@e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
BARDSAI="bardsai/eu-pii-anonimization-multilang@0e72e19f030ed4e661b1673e549af8e0dd176386"
QWEN3GUARD="Qwen/Qwen3Guard-Gen-0.6B@fada3b2f655b89601929198343c94cd2f64d93cc"
PROTECTAI="protectai/deberta-v3-base-prompt-injection-v2@90c9989b1a342275dd0d1a95aad283c04e075671"

# fetch <repo@sha> <remote path> <local dir> [local name]
fetch() {
  local spec="$1" remote="$2" dir="$3" name="${4:-$(basename "$2")}"
  local repo="${spec%@*}" rev="${spec#*@}"
  mkdir -p "$M/$dir"
  local out="$M/$dir/$name"
  local url="$HF/$repo/resolve/$rev/$remote"
  if [[ -s "$out" ]]; then
    local want have
    want=$(curl -sIL "$url" | awk 'tolower($1)=="x-linked-size:"{s=$2} tolower($1)=="content-length:"{c=$2} END{print (s?s:c)}' | tr -d '\r')
    have=$(stat -f%z "$out" 2>/dev/null || stat -c%s "$out")
    if [[ -n "$want" && "$want" == "$have" ]]; then echo "  ok   $dir/$name"; return; fi
  fi
  echo "  get  $dir/$name  <- $repo/$remote"
  curl -fsSL --retry 3 -C - -o "$out" "$url"
}

echo "[1/5] Horizon-Labs prompt-injection-guard-small (Apache-2.0)"
for f in onnx/model_quantized.onnx tokenizer.json tokenizer_config.json special_tokens_map.json config.json code/train/normalizer.py; do
  fetch "$HORIZON" "$f" pi-horizon-small
done

echo "[2/5] Llama Prompt Guard 2 22M int8 ONNX (Llama 4 Community License, gravitee mirror)"
for f in model.quant.onnx tokenizer.json tokenizer_config.json special_tokens_map.json config.json; do
  fetch "$PG2" "$f" pg2-22m
done

echo "[3/5] paraphrase-multilingual-MiniLM-L12-v2 qint8 arm64 (Apache-2.0)"
for f in onnx/model_qint8_arm64.onnx tokenizer.json tokenizer_config.json special_tokens_map.json config.json; do
  fetch "$MINILM" "$f" minilm-l12-multi
done
fetch "$MINILM" 1_Pooling/config.json minilm-l12-multi pooling_config.json

echo "[4/5] bardsai eu-pii-anonimization-multilang int8 (Apache-2.0)"
for f in onnx/model_quantized.onnx tokenizer.json tokenizer_config.json config.json; do
  fetch "$BARDSAI" "$f" eu-pii-ner
done

echo "[4b] Qwen3Guard-Gen-0.6B tokenizer_config.json (official chat template, reference only)"
fetch "$QWEN3GUARD" tokenizer_config.json qwen3guard

if [[ "${WITH_PROTECTAI:-0}" == "1" ]]; then
  echo "[opt] protectai deberta-v3-base-prompt-injection-v2 fp32 ONNX (Apache-2.0, archived)"
  for f in onnx/model.onnx onnx/tokenizer.json onnx/config.json onnx/special_tokens_map.json onnx/tokenizer_config.json; do
    fetch "$PROTECTAI" "$f" pi-protectai-v2
  done
fi

if [[ "${SKIP_OLLAMA:-0}" != "1" ]]; then
  echo "[5/5] Ollama models"
  if ! curl -sf http://127.0.0.1:11434/api/version >/dev/null; then
    echo "  Ollama server not reachable on :11434 - start the app or 'ollama serve &' and re-run" >&2
    exit 1
  fi
  GUARD_SRC="hf.co/QuantFactory/Qwen3Guard-Gen-0.6B-GGUF:Q4_K_M"   # 484 MB
  JUDGE_SRC="hf.co/unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M"               # 533 MB text + 204 MB mmproj (unused)
  ollama pull "$GUARD_SRC"
  ollama pull "$JUDGE_SRC"

  # Local aliases (no extra disk: they reference the same blobs). See the Modelfiles for why.
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  tmp="$(mktemp -d)"
  first_blob() { ollama show --modelfile "$1" | awk '/^FROM /{print $2; exit}'; }
  sed "s|__MODEL_BLOB__|$(first_blob "$GUARD_SRC")|" "$HERE/Modelfile.guard" > "$tmp/Modelfile.guard"
  sed "s|__MODEL_BLOB__|$(first_blob "$JUDGE_SRC")|" "$HERE/Modelfile.judge" > "$tmp/Modelfile.judge"
  ollama create aegis-guard -f "$tmp/Modelfile.guard"
  ollama create aegis-judge -f "$tmp/Modelfile.judge"
  rm -rf "$tmp"
  # Optional: free the unused 204 MB vision projector -> `ollama rm "$JUDGE_SRC"`
  # (aegis-judge keeps the text blob alive).
  if [[ "${WITH_QWEN3:-0}" == "1" ]]; then
    # Fast demo-chat model (130 tok/s vs 34 tok/s for aegis-judge) - but a poor judge (yes-biased).
    ollama pull qwen3:0.6b                                         # 523 MB
  fi
fi

echo "Writing $M/MANIFEST.sha256"
(cd "$M" && find . -type f \( -name '*.onnx' -o -name '*.json' -o -name '*.py' \) ! -name 'MANIFEST*' -print0 \
  | sort -z | xargs -0 shasum -a 256 > MANIFEST.sha256)
du -sh "$M"/* 2>/dev/null || true
echo "done."
