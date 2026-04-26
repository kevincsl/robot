#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f ".venv/bin/python" ]; then
  echo "Missing .venv. Run bootstrap_robot.sh first."
  exit 1
fi

source .venv/bin/activate

# Load environment from .env.robot3
if [ -f ".env.robot3" ]; then
  set -a
  source .env.robot3
  set +a
else
  echo "Missing .env.robot3 configuration file"
  exit 1
fi

export HTTP_PROXY=""
export HTTPS_PROXY=""
export ALL_PROXY=""
export http_proxy=""
export https_proxy=""
export all_proxy=""
export TELEAPP_PYTHON="$(pwd)/.venv/bin/python"
export TELEAPP_HOT_RELOAD="${TELEAPP_HOT_RELOAD:-0}"
export TELEAPP_WATCH_MODE="${TELEAPP_WATCH_MODE:-app-file-only}"
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"

echo "Starting Robot ID: $ROBOT_ID"
echo "State file: .robot_state/robot_state_$ROBOT_ID.json"
echo ""

"$TELEAPP_PYTHON" -m teleapp "$TELEAPP_APP" --python "$TELEAPP_PYTHON"
