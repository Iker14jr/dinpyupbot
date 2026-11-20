#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "Falta TELEGRAM_BOT_TOKEN en el entorno o en .env" >&2
  exit 1
fi

mkdir -p downloads
setsid bash -c 'exec python3 bot.py' >> dinpyupbot.log 2>&1 < /dev/null &
echo "$!" > dinpyupbot.pid
echo "dinpyupbot arrancado con PID $(cat dinpyupbot.pid)"
