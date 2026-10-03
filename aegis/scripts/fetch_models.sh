#!/usr/bin/env bash
# Aegis local models: download (pinned, ungated sources) or verify offline.
#
#   bash scripts/fetch_models.sh             # fetch whatever is missing (no network if complete)
#   bash scripts/fetch_models.sh --verify    # offline: MANIFEST sha256 + Ollama aliases, exit 0/1
#   bash scripts/fetch_models.sh --onnx-only # skip Ollama pulls / aliases
#   bash scripts/fetch_models.sh --force     # re-download every ONNX file, rewrite MANIFEST
#   WITH_PG2=0 ...                           # skip Llama Prompt Guard 2 (off by default at runtime)
#
# Layout (models/, gitignored except MANIFEST.sha256):
#   pi-horizon-small/  Horizon-Labs prompt-injection-guard-small v2, int8 ONNX  (~303 MB, Apache-2.0)
#   pg2-22m/           Llama Prompt Guard 2 22M, int8 ONNX (gravitee mirror)   (~81 MB, Llama 4 Community)
#   minilm-l12-multi/  paraphrase-multilingual-MiniLM-L12-v2 qint8 arm64 ONNX  (~128 MB, Apache-2.0)
#   eu-pii-ner/        bardsai eu-pii-anonimization-multilang int8 ONNX       (~296 MB, Apache-2.0)
#   qwen3guard/        Qwen3Guard-Gen-0.6B tokenizer_config.json (chat template reference only)
#   Ollama: hf.co/QuantFactory/Qwen3Guard-Gen-0.6B-GGUF:Q4_K_M -> alias aegis-guard
#           hf.co/unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M            -> alias aegis-judge
#
# Never runs pip/uv installs. Never restarts Ollama. Licences: src/aegis/semantic/data/MODEL_LICENSES.md
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
M="${AEGIS_MODELS_DIR:-${MODELS_DIR:-$ROOT/models}}"
case "$M" in /*) ;; *) M="$ROOT/$M" ;; esac
DATA="$ROOT/src/aegis/semantic/data"
OLLAMA_URL="${AEGIS_OLLAMA_URL:-http://127.0.0.1:11434}"
HF="https://huggingface.co"

VERIFY=0; ONNX_ONLY=0; FORCE=0
for a in "$@"; do
  case "$a" in
    --verify) VERIFY=1 ;;
    --onnx-only) ONNX_ONLY=1 ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------- offline verification
verify_manifest() {
  [[ -s "$M/MANIFEST.sha256" ]] || { bad "MANIFEST missing ($M/MANIFEST.sha256)"; return 1; }
  if (cd "$M" && shasum -a 256 -c MANIFEST.sha256 --quiet >/dev/null 2>&1); then
    ok "MANIFEST OK ($(grep -c . "$M/MANIFEST.sha256") files)"
  else
    bad "MANIFEST mismatch or missing files:"
    (cd "$M" && shasum -a 256 -c MANIFEST.sha256 --quiet 2>&1 | sed 's/^/      /' | head -20) || true
    return 1
  fi
}

verify_ollama() {
  local rc=0 tags
  if ! tags="$(curl -sf --max-time 2 "$OLLAMA_URL/api/tags")"; then
    bad "Ollama not reachable at $OLLAMA_URL (start the Ollama app; Aegis falls back to the heuristic)"
    return 1
  fi
  for alias in aegis-guard aegis-judge; do
    if grep -q "\"$alias:latest\"\|\"$alias\"" <<<"$tags"; then ok "$alias"; else bad "$alias missing"; rc=1; fi
  done
  return $rc
}

if [[ $VERIFY == 1 ]]; then
  echo "Aegis models - offline verify ($M)"
  rc=0
  verify_manifest || rc=1
  [[ $ONNX_ONLY == 1 ]] || verify_ollama || rc=1
  if [[ $rc != 0 ]]; then echo "hint: run 'bash scripts/fetch_models.sh' to fetch what is missing" >&2; fi
  exit $rc
fi

# ---------------------------------------------------------------- download
mkdir -p "$M"

# repo@pinned-commit (2026-10-03). Bump deliberately, never float on "main".
HORIZON="Horizon-Labs/prompt-injection-guard-small@3215a27edd62c5ba0bd786c57a9d243b2158e70e"
PG2="gravitee-io/Llama-Prompt-Guard-2-22M-onnx@da68d0f6023c7aeaf6b256eec549de295d5e8740"
MINILM="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2@e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
BARDSAI="bardsai/eu-pii-anonimization-multilang@0e72e19f030ed4e661b1673e549af8e0dd176386"
QWEN3GUARD="Qwen/Qwen3Guard-Gen-0.6B@fada3b2f655b89601929198343c94cd2f64d93cc"

if [[ $FORCE == 0 ]] && verify_manifest >/dev/null 2>&1; then
  ONNX_DONE=1
  ok "ONNX models complete (MANIFEST OK) - no download needed"
else
  ONNX_DONE=0
fi

# fetch <repo@sha> <remote path> <local dir> [local name]
fetch() {
  local spec="$1" remote="$2" dir="$3" name="${4:-$(basename "$2")}"
  local repo="${spec%@*}" rev="${spec#*@}"
  mkdir -p "$M/$dir"
  local out="$M/$dir/$name"
  local url="$HF/$repo/resolve/$rev/$remote"
  if [[ $FORCE == 1 ]]; then rm -f "$out"; fi
  if [[ -s "$out" ]]; then
    local want have
    want=$(curl -sIL "$url" | awk 'tolower($1)=="x-linked-size:"{s=$2} tolower($1)=="content-length:"{c=$2} END{print (s?s:c)}' | tr -d '\r')
    have=$(stat -f%z "$out" 2>/dev/null || stat -c%s "$out")
    if [[ -n "$want" && "$want" == "$have" ]]; then echo "  ok   $dir/$name"; return; fi
  fi
  echo "  get  $dir/$name  <- $repo/$remote"
  curl -fsSL --retry 3 -C - -o "$out" "$url"
}

if [[ $ONNX_DONE == 0 ]]; then
  echo "[1/5] Horizon-Labs prompt-injection-guard-small (Apache-2.0)"
  for f in onnx/model_quantized.onnx tokenizer.json tokenizer_config.json special_tokens_map.json config.json code/train/normalizer.py; do
    fetch "$HORIZON" "$f" pi-horizon-small
  done
  if [[ "${WITH_PG2:-1}" == "1" ]]; then
    echo "[2/5] Llama Prompt Guard 2 22M int8 ONNX (Llama 4 Community License - Built with Llama; off at runtime by default)"
    for f in model.quant.onnx tokenizer.json tokenizer_config.json special_tokens_map.json config.json; do
      fetch "$PG2" "$f" pg2-22m
    done
  fi
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

  echo "Writing $M/MANIFEST.sha256"
  (cd "$M" && find . -type f \( -name '*.onnx' -o -name '*.json' -o -name '*.py' \) ! -name 'MANIFEST*' -print0 \
    | sort -z | xargs -0 shasum -a 256 > MANIFEST.sha256)
fi

if [[ $ONNX_ONLY == 0 ]]; then
  echo "[5/5] Ollama models (aegis-guard, aegis-judge)"
  if ! curl -sf --max-time 2 "$OLLAMA_URL/api/version" >/dev/null; then
    echo "  Ollama not reachable at $OLLAMA_URL - start the Ollama app and re-run (we never start/restart it)" >&2
    exit 1
  fi
  if [[ $FORCE == 0 ]] && verify_ollama >/dev/null 2>&1; then
    ok "aegis-guard and aegis-judge aliases present - nothing to pull"
  else
    GUARD_SRC="hf.co/QuantFactory/Qwen3Guard-Gen-0.6B-GGUF:Q4_K_M"   # 484 MB
    JUDGE_SRC="hf.co/unsloth/Qwen3.5-0.8B-GGUF:Q4_K_M"               # 533 MB text + 204 MB mmproj (unused)
    ollama pull "$GUARD_SRC"
    ollama pull "$JUDGE_SRC"
    # Local aliases (no extra disk: same blobs). See the Modelfiles for why they exist.
    tmp="$(mktemp -d)"
    first_blob() { ollama show --modelfile "$1" | awk '/^FROM /{print $2; exit}'; }
    sed "s|__MODEL_BLOB__|$(first_blob "$GUARD_SRC")|" "$DATA/Modelfile.guard" > "$tmp/Modelfile.guard"
    sed "s|__MODEL_BLOB__|$(first_blob "$JUDGE_SRC")|" "$DATA/Modelfile.judge" > "$tmp/Modelfile.judge"
    ollama create aegis-guard -f "$tmp/Modelfile.guard"
    ollama create aegis-judge -f "$tmp/Modelfile.judge"
    rm -rf "$tmp"
    # Optional: free the unused 204 MB vision projector -> ollama rm "$JUDGE_SRC"
  fi
fi

cat <<'EOF'

Recommended Ollama server env (set in the Ollama app / launchctl; Aegis never restarts Ollama):
  OLLAMA_MAX_LOADED_MODELS=2 OLLAMA_NUM_PARALLEL=1 OLLAMA_CONTEXT_LENGTH=2048
  OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0
EOF
du -sh "$M"/* 2>/dev/null || true
echo "done. Verify any time (offline): bash scripts/fetch_models.sh --verify"
