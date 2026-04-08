# robot

`robot` is a smaller Telegram app built on top of `teleapp`.

It keeps Telegram transport and runtime behavior inside `teleapp`, while `robot` only handles:

- deterministic bot commands
- per-chat provider/model/project state
- agent request routing
- subprocess execution for Codex/Gemini/Copilot style CLIs

## Request classes

Each incoming request is classified before any model is called:

- `command request`
  deterministic commands such as `/provider`, `/model`, `/project`, `/projects`, `/status`
- `control request`
  state-changing commands such as `/reset`, `/newthread`, `/restart`
- `agent request`
  natural-language messages and explicit `/agent ...` calls

Only `agent request` goes to a provider runner.

## Quick start

1. Bootstrap the environment.

Windows:

```powershell
bootstrap_robot.bat
```

Linux/macOS:

```bash
./bootstrap_robot.sh
```

`bootstrap_robot` will create/update `.env` and prompt for:
- `TELEAPP_TOKEN`
- `TELEAPP_ALLOWED_USER_ID`

2. Start the app.

Windows:

```powershell
start_robot.bat
```

Linux/macOS:

```bash
./start_robot.sh
```

## Commands

- `/start`
- `/help`
- `/status`
- `/doctor`
- `/provider [codex|gemini|copilot]`
- `/model [name]`
- `/models`
- `/projects`
- `/project [workspace-key-or-label]`
- `/queue`
- `/schedules`
- `/agentstatus`
- `/agentprofiles [--config PATH]`
- `/reset`
- `/newthread`
- `/restart`
- `/run <goal>`
- `/agent [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run] <goal>`
- `/agentresume [run_id_or_path] [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run]`
- `/schedule YYYY-MM-DD HH:MM [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run] <goal>`

## Notes

- `Codex` is the best-supported provider because it keeps a resumable `thread_id`.
- `Gemini` and `Copilot` are executed as plain subprocess commands and currently do not preserve thread state.
- Auto-dev commands (`/agent`, `/agentresume`, `/agentprofiles`, `/schedule`) call `ROBOT_AUTO_DEV_CMD` in the selected project workspace.
- `teleapp` handles Telegram polling, filtering, per-chat request queues, `/restart`, and hot reload.
- Start scripts run `teleapp robot.py`.
- `teleapp` hot reload is enabled by default.
- To disable hot reload, use `teleapp robot.py --no-hot-reload`.
- You can tune reload behavior with:
  - `TELEAPP_RELOAD_QUIET_SECONDS`
  - `TELEAPP_RELOAD_POLL_SECONDS`
  - `TELEAPP_WATCH_MODE` (`app-dir` or `app-file-only`)
  - `--watch <path>` for explicit watch paths
