#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -f dinpyupbot.pid ]]; then
  pid="$(cat dinpyupbot.pid)"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "dinpyupbot detenido: $pid"
  else
    echo "El proceso $pid ya no existe."
  fi

  rm -f dinpyupbot.pid
else
  echo "No hay PID guardado."
fi

if [[ -f telegram-bot-api.pid ]]; then
  ./stop-bot-api.sh
fi
