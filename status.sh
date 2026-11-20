#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -f dinpyupbot.pid ]] && kill -0 "$(cat dinpyupbot.pid)" 2>/dev/null; then
  echo "dinpyupbot activo con PID $(cat dinpyupbot.pid)"
else
  echo "dinpyupbot no está activo"
fi

