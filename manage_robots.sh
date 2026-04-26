#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

COMMAND="${1:-}"

show_help() {
  echo "Robot Management Tool"
  echo ""
  echo "Usage: manage_robots.sh <command> [options]"
  echo ""
  echo "Commands:"
  echo "  status              - Show all running robots"
  echo "  stop <robot_id>     - Stop a specific robot"
  echo "  stopall             - Stop all running robots"
  echo "  logs <robot_id>     - Show logs for a specific robot"
  echo ""
  echo "Examples:"
  echo "  ./manage_robots.sh status"
  echo "  ./manage_robots.sh stop robot1"
  echo "  ./manage_robots.sh stopall"
  echo "  ./manage_robots.sh logs robot1"
}

show_status() {
  echo "Checking running robots..."
  echo ""

  # Find all robot processes
  local PIDS=$(pgrep -f "teleapp.*robot.py" || true)

  if [ -z "$PIDS" ]; then
    echo "No robots running."
    return
  fi

  echo "Running robot processes:"
  echo ""
  ps aux | grep "[t]eleapp.*robot.py" || true
  echo ""

  # Check state files
  echo "Robot states:"
  echo ""
  for f in .robot_state/robot_state_*.json; do
    [ -f "$f" ] || continue
    fname=$(basename "$f")
    robot_id="${fname#robot_state_}"
    robot_id="${robot_id%.json}"
    echo "  [$robot_id] State file: $f"
  done
}

stop_robot() {
  local ROBOT_ID="$1"
  echo "Stopping robot: $ROBOT_ID"

  # Find process by checking environment or command line
  local PIDS=$(pgrep -f "teleapp.*robot.py" || true)

  if [ -z "$PIDS" ]; then
    echo "No robot processes found."
    return
  fi

  local STOPPED=0
  for pid in $PIDS; do
    # Check if this process is for the specified robot
    local ENV_FILE=$(tr '\0' '\n' < /proc/$pid/environ 2>/dev/null | grep "ROBOT_ID=$ROBOT_ID" || true)
    if [ -n "$ENV_FILE" ]; then
      echo "Killing process: $pid"
      kill -TERM $pid 2>/dev/null || kill -KILL $pid 2>/dev/null || true
      STOPPED=1
    fi
  done

  if [ $STOPPED -eq 0 ]; then
    echo "Robot $ROBOT_ID not found in running processes."
  else
    echo "Robot $ROBOT_ID stopped."
  fi
}

stop_all() {
  echo "Stopping all robots..."
  echo ""

  local PIDS=$(pgrep -f "teleapp.*robot.py" || true)

  if [ -z "$PIDS" ]; then
    echo "No robots running."
    return
  fi

  local COUNT=0
  for pid in $PIDS; do
    echo "Killing process: $pid"
    kill -TERM $pid 2>/dev/null || kill -KILL $pid 2>/dev/null || true
    COUNT=$((COUNT + 1))
  done

  echo "Stopped $COUNT robot(s)."
}

show_logs() {
  local ROBOT_ID="${1:-}"

  if [ -z "$ROBOT_ID" ]; then
    echo "Available log files:"
    echo ""
    for f in .robot_state/*.log; do
      [ -f "$f" ] || continue
      echo "  $f"
    done
    echo ""
    echo "Usage: ./manage_robots.sh logs <robot_id>"
    return 1
  fi

  local LOG_FILE=".robot_state/${ROBOT_ID}.log"

  if [ ! -f "$LOG_FILE" ]; then
    echo "Error: Log file $LOG_FILE not found"
    return 1
  fi

  echo "Showing logs for robot: $ROBOT_ID"
  echo "Log file: $LOG_FILE"
  echo ""
  echo "========================================"
  tail -n 100 "$LOG_FILE"
}

# Main logic
case "$COMMAND" in
  status)
    show_status
    ;;
  stop)
    if [ $# -lt 2 ]; then
      echo "Error: Please specify robot ID"
      echo "Usage: ./manage_robots.sh stop <robot_id>"
      exit 1
    fi
    stop_robot "$2"
    ;;
  stopall)
    stop_all
    ;;
  logs)
    show_logs "${2:-}"
    ;;
  *)
    show_help
    ;;
esac
