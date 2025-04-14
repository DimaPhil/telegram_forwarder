#!/bin/bash
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${APP_DIR}/telegram_forwarder.pid"
MONITOR_PID_FILE="${APP_DIR}/monitor.pid"
LOG_FILE="${APP_DIR}/logs/wsl_runner.log"

# Function to log messages
log() {
    local timestamp=$(date "+%Y-%m-%d %H:%M:%S")
    echo "[${timestamp}] $1" | tee -a "$LOG_FILE"
}

# Stop the forwarder process
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    log "Stopping Telegram Forwarder (PID: $PID)..."
    kill -TERM $PID > /dev/null 2>&1 || kill -KILL $PID > /dev/null 2>&1
    rm -f "$PID_FILE"
    log "Telegram Forwarder stopped."
else
    log "No PID file found for forwarder."
fi

# Stop the monitor process
if [ -f "$MONITOR_PID_FILE" ]; then
    MONITOR_PID=$(cat "$MONITOR_PID_FILE")
    log "Stopping monitor process (PID: $MONITOR_PID)..."
    kill -TERM $MONITOR_PID > /dev/null 2>&1 || kill -KILL $MONITOR_PID > /dev/null 2>&1
    rm -f "$MONITOR_PID_FILE"
    log "Monitor process stopped."
else
    log "No PID file found for monitor."
fi

log "All processes stopped."
