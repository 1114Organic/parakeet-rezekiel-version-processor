#!/usr/bin/env bash
set -euo pipefail

# Run the full P3 pipeline. Intended for cron.
# Usage:
#   DRY_RUN_ONLY=1 ./scripts/run_pipeline.sh   # run only fetch --dry-run for testing

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE_DIR"

LOG_DIR="$BASE_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/cron.log"
LOCKDIR="$BASE_DIR/.p3_pipeline_lock"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting pipeline" >> "$LOG_FILE"

# Acquire lock (simple mkdir-based lock)
if mkdir "$LOCKDIR" 2>/dev/null; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Lock acquired" >> "$LOG_FILE"
else
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Another pipeline run is in progress, exiting" >> "$LOG_FILE"
  exit 0
fi

# Ensure lock cleanup on exit
cleanup() {
  rm -rf "$LOCKDIR"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Lock released" >> "$LOG_FILE"
}
trap cleanup EXIT

# Activate virtualenv if present
if [ -f ".venv/bin/activate" ]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Activated virtualenv" >> "$LOG_FILE"
fi

# Respect DRY_RUN_ONLY env var for safe testing
if [ "${DRY_RUN_ONLY:-0}" = "1" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] DRY_RUN_ONLY=1 set — running dry-run only" >> "$LOG_FILE"
  p3 fetch --dry-run >> "$LOG_FILE" 2>&1 || { echo "[$(date '+%Y-%m-%d %H:%M:%S')] fetch --dry-run failed" >> "$LOG_FILE"; exit 1; }
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Dry-run complete" >> "$LOG_FILE"
  exit 0
fi

# Run full pipeline
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running full pipeline" >> "$LOG_FILE"

# Fetch
if ! p3 fetch >> "$LOG_FILE" 2>&1; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] p3 fetch failed" >> "$LOG_FILE"
  exit 1
fi

# Determine number of workers: env var overrides config, default to 4
if [ -n "${TRANSCRIBE_WORKERS:-}" ]; then
  WORKERS="$TRANSCRIBE_WORKERS"
else
  WORKERS=4
  if [ -f "config/feeds.yaml" ]; then
    # Use Python to read YAML safely (virtualenv should provide PyYAML)
    WORKERS=$(python - <<'PY'
import yaml
import sys
try:
    cfg = yaml.safe_load(open('config/feeds.yaml')) or {}
    w = cfg.get('settings', {}).get('transcribe_workers', 4)
    print(int(w) if w else 4)
except Exception:
    print(4)
PY
)
  fi
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Transcribing with ${WORKERS} workers" >> "$LOG_FILE"
if ! p3 transcribe --workers "$WORKERS" >> "$LOG_FILE" 2>&1; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] p3 transcribe failed" >> "$LOG_FILE"
  exit 1
fi

# Digest
if ! p3 digest >> "$LOG_FILE" 2>&1; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] p3 digest failed" >> "$LOG_FILE"
  exit 1
fi

# Write (auto-generate blog posts from summaries)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Auto-generating blog posts" >> "$LOG_FILE"
if ! p3 write --auto >> "$LOG_FILE" 2>&1; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] p3 write --auto failed" >> "$LOG_FILE"
  exit 1
fi

# Export
if ! p3 export >> "$LOG_FILE" 2>&1; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] p3 export failed" >> "$LOG_FILE"
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Pipeline completed successfully" >> "$LOG_FILE"
exit 0
