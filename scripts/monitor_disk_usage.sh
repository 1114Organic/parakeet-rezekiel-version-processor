#!/bin/bash
# Monitor disk usage of P³ data directory
# Run weekly: 0 0 * * 0 cd /path/to/parakeet-youtube-processor && bash scripts/monitor_disk_usage.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
DATA_DIR="$PROJECT_DIR/data"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Get disk usage
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
TOTAL_SIZE=$(du -sh "$DATA_DIR" | awk '{print $1}')

# Get breakdown by subdirectory
AUDIO_SIZE=$(du -sh "$DATA_DIR/audio" 2>/dev/null | awk '{print $1}' || echo "0")
DB_SIZE=$(du -sh "$DATA_DIR/p3.duckdb" 2>/dev/null | awk '{print $1}' || echo "0")

# Log the information
LOG_FILE="$LOG_DIR/disk_usage.log"
{
    echo "[$TIMESTAMP] Disk Usage Report"
    echo "  Total data directory: $TOTAL_SIZE"
    echo "  Audio files: $AUDIO_SIZE"
    echo "  Database: $DB_SIZE"
    echo ""
} >> "$LOG_FILE"

# Also print to console
echo "[$TIMESTAMP] Disk Usage Report:"
echo "  Total data directory: $TOTAL_SIZE"
echo "  Audio files: $AUDIO_SIZE"
echo "  Database: $DB_SIZE"

# Alert if data directory exceeds 100GB
TOTAL_SIZE_NUM=$(du -s "$DATA_DIR" | awk '{print $1}')
LIMIT_KB=$((100 * 1024 * 1024))  # 100GB in KB

if [ "$TOTAL_SIZE_NUM" -gt "$LIMIT_KB" ]; then
    echo "⚠️  WARNING: Data directory exceeds 100GB!"
    echo "Consider running 'p3 fetch --force' with cleanup_days set to a lower value"
fi
