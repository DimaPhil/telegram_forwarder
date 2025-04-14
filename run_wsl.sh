#!/bin/bash

# Telegram Forwarder WSL Runner
# This script runs the Telegram Forwarder and automatically restarts it if it crashes

# Configuration
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="main.py"
LOG_FILE="${APP_DIR}/logs/wsl_runner.log"
PID_FILE="${APP_DIR}/telegram_forwarder.pid"
MAX_RESTARTS=100
RESTART_DELAY=5

# Ensure log directory exists
mkdir -p "${APP_DIR}/logs"

# Function to log messages
log() {
    local timestamp=$(date "+%Y-%m-%d %H:%M:%S")
    echo "[${timestamp}] $1" | tee -a "$LOG_FILE"
}

# Function to check if the process is already running
is_running() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0  # Process is running
        fi
    fi
    return 1  # Process is not running
}

# Function to stop the process
stop_process() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        log "Stopping Telegram Forwarder (PID: $pid)..."
        kill -TERM "$pid" > /dev/null 2>&1 || kill -KILL "$pid" > /dev/null 2>&1
        rm -f "$PID_FILE"
        log "Telegram Forwarder stopped."
    else
        log "No PID file found. Process may not be running."
    fi
}

# Kill any existing process
if is_running; then
    log "Telegram Forwarder is already running. Stopping it first..."
    stop_process
fi

# Change to the application directory
cd "$APP_DIR" || { log "Failed to change to application directory: $APP_DIR"; exit 1; }

# Function to run the forwarder with auto-restart
run_with_restart() {
    local restart_count=0

    while [ $restart_count -lt $MAX_RESTARTS ]; do
        log "Starting Telegram Forwarder (Attempt $((restart_count + 1))/${MAX_RESTARTS})..."

        # Start the Python script and redirect output to log file
        python "$PYTHON_SCRIPT" 2>&1 | tee -a "$LOG_FILE" &
        local pid=$!
        echo $pid > "$PID_FILE"
        log "Telegram Forwarder started with PID: $pid"

        # Wait for the process to finish
        wait $pid
        local exit_code=$?

        # Check exit code
        if [ $exit_code -eq 0 ]; then
            log "Telegram Forwarder exited normally with code 0. Stopping."
            rm -f "$PID_FILE"
            break
        else
            log "Telegram Forwarder crashed with exit code $exit_code. Restarting in $RESTART_DELAY seconds..."
            sleep $RESTART_DELAY
            restart_count=$((restart_count + 1))
        fi
    done

    if [ $restart_count -ge $MAX_RESTARTS ]; then
        log "Maximum restart attempts ($MAX_RESTARTS) reached. Giving up."
    fi
}

# Run the forwarder in the background
run_with_restart &

# Save the monitor process ID
echo $! > "${APP_DIR}/monitor.pid"
log "Monitor process started with PID: $(cat ${APP_DIR}/monitor.pid)"
log "To stop everything, run: ./stop_wsl.sh"

# Create stop script if it doesn't exist
if [ ! -f "${APP_DIR}/stop_wsl.sh" ]; then
    cat > "${APP_DIR}/stop_wsl.sh" << 'EOF'
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
EOF
    chmod +x "${APP_DIR}/stop_wsl.sh"
    log "Created stop script: stop_wsl.sh"
fi

# Make the script executable
chmod +x "${APP_DIR}/stop_wsl.sh"

echo
echo "Telegram Forwarder has been started in the background."
echo "Check logs at: $LOG_FILE"
echo "To stop, run: ./stop_wsl.sh"
