#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="${CONTROL_PANEL_PORT:-9876}"
mkdir -p tools
# Cloudflare tunnel (HTTPS)
if [[ -x tools/cloudflared ]]; then
  pkill -f "cloudflared tunnel --url" 2>/dev/null || true
  nohup ./tools/cloudflared tunnel --url "http://localhost:${PORT}" --no-autoupdate > tools/cf-tunnel.log 2>&1 &
  echo $! > tools/cf-tunnel.pid
  sleep 5
  grep -oE "https://[a-z0-9-]+\\.trycloudflare.com" tools/cf-tunnel.log | tail -1 || true
fi
# bore (HTTP alternativo)
if [[ -x tools/bore ]]; then
  pkill -f "bore local" 2>/dev/null || true
  nohup ./tools/bore local "$PORT" --to bore.pub > tools/bore.log 2>&1 &
  echo $! > tools/bore.pid
  sleep 3
  grep -oE "bore.pub:[0-9]+" tools/bore.log | tail -1 || true
fi
