#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

PORT="${SOPHYANE_EVOLUTION_LOCAL_PORT:-8767}"
PID_FILE="${HOME}/sophyane-evolution-analyst-${PORT}.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "EVOLUTION_LOCAL_ANALYST=NOT_RUNNING"
    exit 0
fi

PID="$(
    cat "$PID_FILE" 2>/dev/null || true
)"

if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null || true
fi

rm -f "$PID_FILE"

echo "EVOLUTION_LOCAL_ANALYST=STOPPED"
