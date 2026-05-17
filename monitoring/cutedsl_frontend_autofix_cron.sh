#!/bin/bash
set -euo pipefail

PROJECT_DIR="/nvme0n1-disk/code/cutedsl-site"
RELATED_DIR="/nvme0n1-disk/code/cutedsl"
ERROR_LOG="${FRONTEND_ERROR_LOG_PATH:-/nvme0n1-disk/tmp/cutedsl-frontend-errors.jsonl}"
STATE_FILE="${FRONTEND_CODEXEXEC_STATE:-/nvme0n1-disk/tmp/cutedsl-frontend-codexexec-autofix.state}"
LAST_RUN_FILE="${FRONTEND_CODEXEXEC_LAST_RUN_STATE:-/nvme0n1-disk/tmp/cutedsl-frontend-codexexec-autofix-last-run}"
COOLDOWN_SECONDS="${FRONTEND_CODEXEXEC_COOLDOWN_SECONDS:-10800}"
MODEL="${CODEXEXEC_MODEL:-gpt-5.5}"
REASONING="${CODEXEXEC_REASONING:-high}"
LOG="$PROJECT_DIR/monitoring/cutedsl_frontend_autofix_cron.log"

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

CODEXEXEC_CMD="${cmd[*]}" /nvme0n1-disk/code/.venv/bin/python "$PROJECT_DIR/scripts/codexexec_autofix.py" \
    --kind frontend \
    --once \
    --error-log "$ERROR_LOG" \
    --state "$STATE_FILE" \
    --last-run-state "$LAST_RUN_FILE" \
    --cooldown-seconds "$COOLDOWN_SECONDS" \
    >> "$LOG" 2>&1
