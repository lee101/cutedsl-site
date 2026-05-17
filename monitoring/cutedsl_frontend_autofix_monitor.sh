#!/bin/bash
set -euo pipefail

PROJECT_DIR="/nvme0n1-disk/code/cutedsl-site"
RELATED_DIR="/nvme0n1-disk/code/cutedsl"
LOG="$PROJECT_DIR/monitoring/cutedsl_frontend_autofix_monitor.log"
LOCKFILE="/tmp/cutedsl_frontend_autofix_monitor.lock"
ERROR_LOG="${FRONTEND_ERROR_LOG_PATH:-/nvme0n1-disk/tmp/cutedsl-frontend-errors.jsonl}"
STATE_FILE="${FRONTEND_CODEXEXEC_STATE:-/nvme0n1-disk/tmp/cutedsl-frontend-codexexec-autofix.state}"
LAST_RUN_FILE="${FRONTEND_CODEXEXEC_LAST_RUN_STATE:-/nvme0n1-disk/tmp/cutedsl-frontend-codexexec-autofix-last-run}"
CHECK_INTERVAL="${FRONTEND_CODEXEXEC_CHECK_INTERVAL:-60}"
COOLDOWN_SECONDS="${FRONTEND_CODEXEXEC_COOLDOWN_SECONDS:-10800}"
MODEL="${CODEXEXEC_MODEL:-gpt-5.5}"
REASONING="${CODEXEXEC_REASONING:-high}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

if [ -f "$LOCKFILE" ]; then
    pid=$(cat "$LOCKFILE" 2>/dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "Already running (PID $pid)"
        exit 1
    fi
    rm -f "$LOCKFILE"
fi

echo $$ > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

cd "$PROJECT_DIR"

cmd=(codex exec
    -C "$PROJECT_DIR"
    -m "$MODEL"
    -c "model_reasoning_effort=$REASONING"
    -s danger-full-access
    --dangerously-bypass-approvals-and-sandbox
    -)

if [ -d "$RELATED_DIR" ]; then
    cmd=(codex exec
        -C "$PROJECT_DIR"
        --add-dir "$RELATED_DIR"
        -m "$MODEL"
        -c "model_reasoning_effort=$REASONING"
        -s danger-full-access
        --dangerously-bypass-approvals-and-sandbox
        -)
fi

export CODEXEXEC_CMD="${cmd[*]}"
export CODEXEXEC_COOLDOWN_SECONDS="$COOLDOWN_SECONDS"

log "Starting CuteDSL frontend autofix monitor"
log "error_log=$ERROR_LOG interval=${CHECK_INTERVAL}s cooldown=${COOLDOWN_SECONDS}s model=$MODEL reasoning=$REASONING"
log "command=$CODEXEXEC_CMD"

exec /nvme0n1-disk/code/.venv/bin/python "$PROJECT_DIR/scripts/codexexec_autofix.py" \
    --kind frontend \
    --error-log "$ERROR_LOG" \
    --state "$STATE_FILE" \
    --last-run-state "$LAST_RUN_FILE" \
    --interval "$CHECK_INTERVAL" \
    --cooldown-seconds "$COOLDOWN_SECONDS" \
    >> "$LOG" 2>&1
