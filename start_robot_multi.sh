#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ $# -eq 0 ]; then
  echo "Usage: start_robot_multi.sh <robot_id> [bot_token]"
  echo ""
  echo "Example:"
  echo "  ./start_robot_multi.sh robot-1"
  echo "  ./start_robot_multi.sh robot-2 YOUR_BOT_TOKEN_HERE"
  echo ""
  echo "This will start a robot instance with:"
  echo "  - ROBOT_ID=\$1"
  echo "  - State file: .robot_state/robot_state_\$1.json"
  echo "  - Optional: TELEAPP_TOKEN=\$2 (if provided)"
  exit 1
fi

if [ ! -f ".venv/bin/python" ]; then
  echo "Missing .venv. Run bootstrap_robot.sh first."
  exit 1
fi

source .venv/bin/activate

export HTTP_PROXY=""
export HTTPS_PROXY=""
export ALL_PROXY=""
export http_proxy=""
export https_proxy=""
export all_proxy=""
export TELEAPP_APP="robot.py"
export TELEAPP_PYTHON="$(pwd)/.venv/bin/python"
export TELEAPP_HOT_RELOAD="${TELEAPP_HOT_RELOAD:-0}"
export TELEAPP_WATCH_MODE="${TELEAPP_WATCH_MODE:-app-file-only}"
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"

export ROBOT_ID="$1"

if [ $# -ge 2 ]; then
  export TELEAPP_TOKEN="$2"
fi

echo "Starting robot with ID: $ROBOT_ID"
echo "State file: .robot_state/robot_state_$ROBOT_ID.json"
echo ""

"$TELEAPP_PYTHON" -m teleapp "$TELEAPP_APP" --python "$TELEAPP_PYTHON"
