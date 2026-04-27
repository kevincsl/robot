#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Missing .venv. Run bootstrap_robot.sh first."
  exit 1
fi

if [ $# -eq 0 ]; then
  ./.venv/bin/python robotctl.py /h
elif [ "$1" = "all" ]; then
  shift
  ./.venv/bin/python robotctl.py start all "$@"
else
  ./.venv/bin/python robotctl.py run "$@"
fi
