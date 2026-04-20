#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Missing .venv. Run bootstrap_robot.sh first."
  exit 1
fi

source .venv/bin/activate
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
unset http_proxy https_proxy all_proxy
if [ -n "${PYTHONPATH:-}" ]; then
  export PYTHONPATH="$PWD:$PYTHONPATH"
else
  export PYTHONPATH="$PWD"
fi
teleapp robot.py --no-hot-reload
