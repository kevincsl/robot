# RUNBOOK

Operational runbook for `robot`.

## 1) Start / Stop

Windows:

```powershell
bootstrap_robot.bat
start_robot.bat
start_robot_bg.bat
shutdown_robot.bat
```

Linux/macOS:

```bash
./bootstrap_robot.sh
./start_robot.sh
```

Start script behavior:

- `start_robot.bat` runs `%CD%\.venv\Scripts\python.exe -m teleapp` with explicit `--python`.
- `start_robot_bg.bat` runs `start_robot.bat` in hidden background mode and writes logs to `robot.bg.stderr.log` / `robot.bg.stdout.log`.
- `start_robot.sh` runs `.venv/bin/python -m teleapp robot.py --python .venv/bin/python` with default `TELEAPP_HOT_RELOAD=0`.
- Both scripts clear proxy env vars and prepend repo root to `PYTHONPATH`.

Stop local process:

- Use your terminal stop signal, or platform process tools.
- On Windows, prefer `shutdown_robot.bat` (or `killall.bat`, now mapped to shutdown script) to stop only this repo's robot processes.
- Telegram-side restart command: `/restart` (managed by `teleapp` supervisor).
- Avoid direct `python -m robot`/`robot` unless `--standalone` is explicitly intended for local debug.

## 2) Basic Health Check

In Telegram:

- `/status`
- `/doctor`
- `/queue`
- `/agentstatus`
- `/schedules`

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
