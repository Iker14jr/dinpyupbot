#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
export CONTROL_PANEL_PORT="${CONTROL_PANEL_PORT:-9876}"
fuser -k "${CONTROL_PANEL_PORT}/tcp" 2>/dev/null || true
sleep 1
nohup python3 -u control_panel.py > panel.log 2>&1 &
echo $! > panel.pid
echo "Panel arrancado en puerto $CONTROL_PANEL_PORT (PID $(cat panel.pid))"
