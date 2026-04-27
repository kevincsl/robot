# RUNBOOK

Operational runbook for `robot`.

## 1) Start / Stop

Canonical entrypoint:

```powershell
bootstrap_robot.bat
robotctl /h
robotctl run default         # Foreground
robotctl start default       # Background
robotctl stop default
```

### Multiple Robots

```bash
robotctl start robot1
robotctl start all
robotctl status
robotctl stop robot1
robotctl stop all
robotctl restart robot1
robotctl logs robot1 -f
```

Stop local process:

- **Single robot**: Use terminal stop signal or `robotctl stop default`.
- **Multi-robot**: Use `robotctl stop all` or `robotctl stop <config>`.
- Telegram-side restart command: `/restart` (managed by `teleapp` supervisor).
- Avoid direct `python -m robot`/`robot` unless `--standalone` is explicitly intended for local debug.

**Note**: Config name (e.g., `robot1`) is used for startup and log files. `ROBOT_ID` inside the config is used for runtime state files and Telegram commands.

## 2) Basic Health Check

In Telegram:

- `/status`
- `/doctor`
- `/queue`
- `/agentstatus`
- `/schedules`

For multi-robot setups:

- `/robots` - list all active robots
- `/robotstatus <robot_id>` - detailed status for specific robot

Expected healthy signs:

- running process exists
- `busy: no` when idle
- `queued_requests: 0` when idle
- no `last_error`
- `/status` shows:
  - `queued_jobs: 0` when no waiting agent jobs
  - `scheduled_jobs` matches expected scheduled count
  - `ui_flow: -` when no interactive flow is active

## 3) Common Issues

### A) Polling conflict

Symptom:

- Conflict error, bot does not receive updates.

Action:

1. Stop duplicate bot processes using the same token.
2. Start only one instance.
3. Verify `/status`.

### B) Job appears stuck

Symptom:

- Long-running task with no visible progress.

Action:

1. Check `/agentstatus` and `/queue`.
2. If needed, send stop intent (`stop`) or clear queue (`/clearqueue`).
3. If old schedules are no longer needed, clear them with `/clearschedule`.
4. Re-run with `/run <goal>` or `/agent <goal>`.

### C) Missing dependencies after bootstrap

Symptom:

- Import/runtime errors after install.

Action:

1. Re-run bootstrap script.
2. Ensure constraints-based install is used (`constraints.txt`).
3. Re-check with `/doctor`.

### D) Markdown/PDF import problems

Symptom:

- Document conversion errors.

Action:

1. Confirm `markitdown[pdf]` is installed in current venv.
2. Re-check dependency compatibility in `DEPENDENCY_STRATEGY.md`.

## 4) Recovery Steps

If behavior is inconsistent after crash/restart:

1. `/status`
2. `/agentstatus`
3. `/queue`
4. `/schedules`
5. If stale state is suspected:
   - `/reset` (clear thread state)
   - `/clearqueue` (if queue should be empty)
   - `/clearschedule` (if scheduled jobs should be empty)
6. Restart process and verify health commands again.

## 5) Pre-Release Checks

Before push/release:

1. `pytest -q`
2. `python scripts/check_release_consistency.py`
3. `python scripts/check_dependency_health.py`
4. Verify docs links in `README.md`
5. Confirm dependency constraints and strategy docs are current
6. Confirm quality gate status in `QUALITY_GATE_90.md`
