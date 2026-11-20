#!/usr/bin/env bash
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
while true; do
  if [[ -f dinpyupbot.pid ]] && kill -0 "$(cat dinpyupbot.pid)" 2>/dev/null; then
    sleep 30
    continue
  fi
  echo "$(date -Is) dinpyupbot no está activo, arrancando..." >> dinpyupbot-keepalive.log
  bash start.sh >> dinpyupbot-keepalive.log 2>&1
  sleep 15
done
