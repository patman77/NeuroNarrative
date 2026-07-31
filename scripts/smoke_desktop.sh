#!/usr/bin/env bash
# Smoke-test a built desktop bundle: no venv, no Python on PATH, network forced offline.
#
#   scripts/smoke_desktop.sh [path-to-executable]
#
# Exercises health, the served SPA, upload, analyze, and — if the build bundled the ASR
# model — real transcription. HF_HUB_OFFLINE=1 means a passing ASR check proves the model
# came from the bundle rather than the network.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_BIN="$REPO_ROOT/dist/NeuroNarrative.app/Contents/MacOS/NeuroNarrative"
[[ "$(uname)" != "Darwin" ]] && DEFAULT_BIN="$REPO_ROOT/dist/NeuroNarrative/NeuroNarrative"
APP_BIN="${1:-$DEFAULT_BIN}"

if [[ ! -x "$APP_BIN" ]]; then
  echo "Not found: $APP_BIN — run scripts/build_desktop.sh first." >&2
  exit 1
fi

WORK="$(mktemp -d)"
LOG="$WORK/app.log"
trap 'kill "${APP_PID:-}" 2>/dev/null || true; rm -rf "$WORK"' EXIT

fail() { echo "FAIL: $*" >&2; echo "--- app log ---" >&2; tail -30 "$LOG" >&2; exit 1; }

echo "==> Launching $APP_BIN with a minimal environment"
env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin TMPDIR="${TMPDIR:-/tmp}" \
  NEURONARRATIVE_NO_BROWSER=1 HF_HUB_OFFLINE=1 \
  "$APP_BIN" > "$LOG" 2>&1 &
APP_PID=$!

URL=""
for _ in $(seq 1 60); do
  URL="$(grep -o 'http://127.0.0.1:[0-9]*' "$LOG" 2>/dev/null | head -1 || true)"
  [[ -n "$URL" ]] && curl -fsS "$URL/api/health" >/dev/null 2>&1 && break
  sleep 1
done
[[ -n "$URL" ]] || fail "app never printed a URL"
# The single-instance guard would otherwise silently test a previously running build.
if grep -q "already running" "$LOG"; then
  fail "attached to an existing instance -- quit the running app before smoke testing"
fi
echo "    serving on $URL"

echo "==> health"
curl -fsS "$URL/api/health" | grep -q '"status":"ok"' || fail "health check"

echo "==> SPA"
curl -fsS "$URL/" | grep -q '<title>' || fail "index.html not served"
curl -fsS -o /dev/null "$URL/some/client/route" || fail "SPA fallback"

# Analysis is a background job: POST returns a job id, then poll until it settles.
analyze() {
  local csv="$1" wav="$2" job body
  job="$(curl -fsS -X POST "$URL/api/analyze" -H 'Content-Type: application/json' \
    -d "{\"csv_path\":\"$csv\",\"wav_path\":\"$wav\",\"ruleset_name\":\"default\",\"pre_event_window_sec\":5,\"post_event_window_sec\":7}")" || return 1
  job="$(printf '%s' "$job" | sed -n 's/.*"job_id":"\([0-9a-f]*\)".*/\1/p')"
  # Guard against an unexpected response shape (e.g. an older build answering).
  if [[ -z "$job" ]]; then
    echo "no job_id in analyze response -- is an older instance answering?" >&2
    return 1
  fi
  for _ in $(seq 1 600); do
    body="$(curl -fsS "$URL/api/analyze/$job")" || return 1
    case "$body" in
      *'"status":"done"'*) printf '%s' "$body"; return 0 ;;
      *'"status":"error"'*) printf '%s' "$body" >&2; return 1 ;;
    esac
    sleep 1
  done
  echo "analysis timed out" >&2
  return 1
}

echo "==> upload + analyze"
UP="$(curl -fsS -X POST "$URL/api/upload" \
  -F "gsr=@$REPO_ROOT/test_gsr.csv;type=text/csv" \
  -F "audio=@$REPO_ROOT/test_audio.wav;type=audio/wav")" || fail "upload"
CSV="$(printf '%s' "$UP" | sed 's/.*"csv_path":"\([^"]*\)".*/\1/')"
WAV="$(printf '%s' "$UP" | sed 's/.*"wav_path":"\([^"]*\)".*/\1/')"
RESULT="$(analyze "$CSV" "$WAV")" || fail "analyze"
printf '%s' "$RESULT" | grep -q '"events"' || fail "analyze returned no events key"
echo "    events detected: $(printf '%s' "$RESULT" | grep -o '"event_id"' | wc -l | tr -d ' ')"

echo "==> path confinement"
CODE="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/api/analyze" \
  -H 'Content-Type: application/json' -d '{"csv_path":"/etc/passwd","wav_path":"/etc/hosts"}')"
[[ "$CODE" == "400" ]] || fail "expected 400 for unstaged path, got $CODE"

# Real speech, so an empty transcript means the ASR stack is actually broken.
if command -v say >/dev/null 2>&1; then
  echo "==> transcription (bundled model, offline)"
  say -o "$WORK/speech.wav" --data-format=LEI16@16000 \
    "I felt quite anxious when the interviewer asked about the deadline." 2>/dev/null
  UP2="$(curl -fsS -X POST "$URL/api/upload" \
    -F "gsr=@$REPO_ROOT/test_gsr.csv;type=text/csv" \
    -F "audio=@$WORK/speech.wav;type=audio/wav")"
  CSV2="$(printf '%s' "$UP2" | sed 's/.*"csv_path":"\([^"]*\)".*/\1/')"
  WAV2="$(printf '%s' "$UP2" | sed 's/.*"wav_path":"\([^"]*\)".*/\1/')"
  R2="$(analyze "$CSV2" "$WAV2")" || fail "analyze (speech)"
  WORDS="$(printf '%s' "$R2" | grep -o '"text"' | wc -l | tr -d ' ')"
  if [[ "$WORDS" -gt 0 ]]; then
    echo "    transcribed $WORDS words"
  elif grep -q "asr_models" "$LOG"; then
    fail "model is bundled but transcription produced no words"
  else
    echo "    SKIP: no bundled model and offline, so no transcript (expected for --no-model)"
  fi
else
  echo "==> transcription: SKIP (no 'say' available to synthesise speech)"
fi

grep -qiE "traceback|Failed to execute script" "$LOG" && fail "errors in app log"

echo
echo "PASS — bundle is functional"
