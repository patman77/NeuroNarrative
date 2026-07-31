#!/usr/bin/env bash
# Build the NeuroNarrative desktop bundle.
#
#   scripts/build_desktop.sh              # bundle the ASR model (offline on first run)
#   scripts/build_desktop.sh --no-model   # smaller bundle; model downloads on first use
#
# NEURONARRATIVE_ASR_MODEL picks the model (default "small"; "base" is ~2.5x faster and
# 320 MB smaller, at roughly double the word error rate).
#
# Requires: node/npm, and a backend venv with `pip install -e ".[asr,packaging]"`.
set -euo pipefail

BUNDLE_MODEL=1
for arg in "$@"; do
  case "$arg" in
    --no-model) BUNDLE_MODEL=0 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGED_MODELS="$REPO_ROOT/packaging/build/asr_models"
# Keep in step with Settings.asr_model, so the bundled weights are the ones actually used.
ASR_MODEL="${NEURONARRATIVE_ASR_MODEL:-small}"

echo "==> Building frontend"
cd "$REPO_ROOT/frontend"
npm run build

echo "==> Preparing backend"
cd "$REPO_ROOT/backend"
if [[ -z "${VIRTUAL_ENV:-}" && -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
python -c "import PyInstaller" 2>/dev/null || {
  echo "PyInstaller missing. Run: pip install -e \".[asr,desktop,packaging]\"" >&2
  exit 1
}
python -c "import webview" 2>/dev/null || {
  echo "pywebview missing (the app would fall back to a browser tab)." >&2
  echo "Run: pip install -e \".[asr,desktop,packaging]\"" >&2
  exit 1
}

rm -rf "$STAGED_MODELS"
if [[ "$BUNDLE_MODEL" == "1" ]]; then
  echo "==> Staging ASR model '$ASR_MODEL' for offline first run"
  mkdir -p "$STAGED_MODELS"
  # Stage whatever the *detected* backend will ask for: MLX weights on Apple silicon,
  # CTranslate2 weights otherwise. Bundling the wrong format means a silent download on
  # first use, defeating the offline promise.
  python - "$ASR_MODEL" "$STAGED_MODELS" <<'PY'
import os, sys

# Run from backend/, so the `app` package is importable from the cwd.
from app.utils.accelerator import detect_accelerator, resolve_model

model_size, target = sys.argv[1], sys.argv[2]
accelerator = detect_accelerator("auto")
resolved = resolve_model(model_size, accelerator.backend)
print(f"backend={accelerator.describe()} -> model {resolved}")

if accelerator.backend == "mlx":
    os.environ["HF_HUB_CACHE"] = target
    from huggingface_hub import snapshot_download

    snapshot_download(repo_id=resolved, cache_dir=target)
else:
    from faster_whisper import WhisperModel

    # Instantiating downloads into `target` and validates the weights load.
    WhisperModel(resolved, device="cpu", compute_type="int8", download_root=target)
print(f"staged {resolved} -> {target}")
PY
else
  echo "==> Skipping model bundle (--no-model): it will download on first use"
fi

echo "==> Running PyInstaller"
rm -rf "$REPO_ROOT/backend/dist" "$REPO_ROOT/backend/build"
pyinstaller "$REPO_ROOT/packaging/neuronarrative.spec" --noconfirm --distpath "$REPO_ROOT/dist" --workpath "$REPO_ROOT/packaging/build/pyinstaller"

echo
echo "==> Done"
du -sh "$REPO_ROOT/dist"/* 2>/dev/null || true
