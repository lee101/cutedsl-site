#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE=cutedsl-monitor.service
TIMER=cutedsl-monitor.timer

if [[ "${1:-}" == "--status" ]]; then
    systemctl --no-pager --full status "$TIMER" "$SERVICE" || true
    sudo journalctl -u "$SERVICE" -n 40 --no-pager || true
    exit 0
fi

mkdir -p "$SCRIPT_DIR/logs" "$SCRIPT_DIR/state"
chmod 0700 "$SCRIPT_DIR/logs" "$SCRIPT_DIR/state"
find "$SCRIPT_DIR/logs" "$SCRIPT_DIR/state" -maxdepth 1 -type f -writable -exec chmod 0600 {} +
chmod +x "$SCRIPT_DIR/check_frontend.mjs" "$SCRIPT_DIR/cutedsl_monitor.py" \
    "$SCRIPT_DIR/provision_canary.py" "$SCRIPT_DIR/install_systemd.sh"

if [[ "${1:-}" == "--provision-canary" ]]; then
    /usr/bin/python3 "$SCRIPT_DIR/provision_canary.py"
fi

sudo install -m 0644 "$SCRIPT_DIR/$SERVICE" "/etc/systemd/system/$SERVICE"
sudo install -m 0644 "$SCRIPT_DIR/$TIMER" "/etc/systemd/system/$TIMER"
sudo systemctl daemon-reload
sudo systemctl enable --now "$TIMER"
sudo systemctl start "$SERVICE"

systemctl --no-pager --full status "$TIMER" "$SERVICE" || true
