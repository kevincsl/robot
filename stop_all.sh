#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "Missing .venv. Run bootstrap_robot.sh first."
  exit 1
fi
./.venv/bin/python robotctl.py stop all "$@"
