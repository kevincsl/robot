#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Check if .venv exists
if [ ! -x ".venv/bin/python" ]; then
  echo "Missing .venv. Run bootstrap_robot.sh first."
  exit 1
fi

# Function to start a single robot
start_single_robot() {
  local CONFIG_NAME="$1"
  local ENV_FILE=".env.${CONFIG_NAME}"

  if [ ! -f "$ENV_FILE" ]; then
    echo "Error: Configuration file $ENV_FILE not found"
    echo ""
    echo "Available configurations:"
    for f in .env.robot*; do
      [ -f "$f" ] || continue
      fname="${f#.env.}"
      echo "  - $fname"
    done
    exit 1
  fi

  echo "Starting robot with config: $CONFIG_NAME"
  echo "Loading: $ENV_FILE"
  echo ""

  source .venv/bin/activate

  # Load environment from config file
  set -a
  source "$ENV_FILE"
  set +a

  # Clear proxy settings
  unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
  unset http_proxy https_proxy all_proxy

  # Set teleapp environment
  export TELEAPP_PYTHON="$PWD/.venv/bin/python"
  export TELEAPP_HOT_RELOAD="${TELEAPP_HOT_RELOAD:-0}"
  export TELEAPP_WATCH_MODE="${TELEAPP_WATCH_MODE:-app-file-only}"
  if [ -n "${PYTHONPATH:-}" ]; then
    export PYTHONPATH="$PWD:$PYTHONPATH"
  else
    export PYTHONPATH="$PWD"
  fi

  echo "Robot ID: $ROBOT_ID"
  echo "State file: .robot_state/robot_state_${ROBOT_ID}.json"
  echo ""

  "$TELEAPP_PYTHON" -m teleapp "$TELEAPP_APP" --python "$TELEAPP_PYTHON"
}

# Start all robots
start_all_robots() {
  echo "Starting all robots in background..."
  echo ""

  # Create log directory if not exists
  mkdir -p .robot_state

  local COUNT=0
  for f in .env.robot*; do
    [ -f "$f" ] || continue

    # Skip .example files
    [[ "$f" == *.example ]] && continue

    fname="${f#.env.}"
    echo "Starting robot: $fname"

    # Start in background with nohup
    nohup bash "$0" "$fname" > ".robot_state/${fname}.log" 2>&1 &
    local PID=$!
    echo "  PID: $PID"

    COUNT=$((COUNT + 1))
    sleep 2
  done

  echo ""
  echo "Started $COUNT robot(s) in background"
  echo ""
  echo "Management commands:"
  echo "  ./manage_robots.sh status    - Check running robots"
  echo "  ./manage_robots.sh stop <id>  - Stop specific robot"
  echo "  ./manage_robots.sh stopall   - Stop all robots"
  echo "  ./manage_robots.sh logs <id>  - View robot logs"
}

# Show help
show_help() {
  echo "Usage: start_robot.sh [config_name|all]"
  echo ""
  echo "Examples:"
  echo "  start_robot.sh robot1    - Start robot with .env.robot1 config"
  echo "  start_robot.sh robot2    - Start robot with .env.robot2 config"
  echo "  start_robot.sh mybot     - Start robot with .env.mybot config"
  echo "  start_robot.sh all       - Start all robots (scan .env.robot* files)"
  echo ""
  echo "Available configurations:"
  for f in .env.robot*; do
    [ -f "$f" ] || continue
    fname="${f#.env.}"
    echo "  - $fname"
  done
  echo ""
  echo "To create a new robot:"
  echo "  1. Copy .env.robot1.example to .env.robotN"
  echo "  2. Edit .env.robotN and set ROBOT_ID, TELEAPP_TOKEN, etc."
  echo "  3. Run: ./start_robot.sh robotN"
}

# Main logic
if [ $# -eq 0 ]; then
  show_help
elif [ "$1" = "all" ]; then
  start_all_robots
else
  start_single_robot "$1"
fi
