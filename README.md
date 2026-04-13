# robot

`robot` is a Telegram app built on top of `teleapp`.

It keeps Telegram transport and runtime behavior inside `teleapp`, while `robot` handles:

- deterministic bot commands
- per-chat provider/model/project state
- agent request routing
- subprocess execution for Codex/Gemini/Copilot style CLIs

## Request Classes

Each incoming request is classified before any model is called:

- `command request`
  deterministic commands such as `/provider`, `/model`, `/project`, `/projects`, `/status`
- `control request`
  state-changing commands such as `/reset`, `/newthread`, `/restart`
- `agent request`
  natural-language messages and explicit `/agent ...` calls

Only `agent request` goes to a provider runner.

## Quick Start

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

## Brain Features

- `menu`, `model`, and `brain` support Telegram button menus in addition to slash commands.
- `brain` supports second-brain capture, inbox, search, summaries, decision support, and schedule workflows.
- Natural-language schedule creation examples:
  - `提醒我今天 6 點開會`
  - `30 分鐘後叫我休息`
  - `明天早上 8 點提醒我交報告`
  - `4/20 下午 2 點提醒我和客戶確認需求`
- Schedule view phrases:
  - `今天行程`
  - `本週行程`
  - `下週行程`
  - `今天提醒`
  - `未來提醒`
- Schedule follow-up references:
  - `第一個行程改到 3 點`
- Schedule update/delete flows require confirmation before changing notes.
- Past-due archive only applies to one-time schedules and skips recurring reminders.

## Automation

- `/brainauto [on|off|status]`
- `/brainautodaily HH:MM`
- `/brainautoweekly <weekday 0-6> HH:MM`
- Daily briefs, weekly briefs, and schedule alerts can be pushed automatically.
- Long-running jobs emit heartbeat status updates while running.
- If the app restarts while a job is active, the job is recovered and resumed automatically on startup.

## Notes

- `Codex` is the best-supported provider because it keeps a resumable `thread_id`.
- `Gemini` and `Copilot` are executed as plain subprocess commands and currently do not preserve thread state.
- Auto-dev commands (`/agent`, `/agentresume`, `/agentprofiles`, `/schedule`) call `ROBOT_AUTO_DEV_CMD` in the selected project workspace.
- `teleapp` handles Telegram polling, filtering, per-chat request queues, `/restart`, and hot reload.
- Start scripts run `teleapp robot.py`.
- `teleapp` hot reload is enabled by default, but this project currently runs with hot reload disabled in `.env` until restart path is fully stabilized.
- To disable hot reload, use `teleapp robot.py --no-hot-reload`.
- Codex execution flags can be controlled with:
  - `ROBOT_CODEX_BYPASS_APPROVALS_AND_SANDBOX` (`1` or `0`)
  - `ROBOT_CODEX_SKIP_GIT_REPO_CHECK` (`1` or `0`)
  - default is `0` (disabled); enable only when you explicitly accept the risk.
  - when enabled, startup status emits `SECURITY WARNING` and `/status` shows `security_risk_mode: on`.
- You can tune reload behavior with:
  - `TELEAPP_RELOAD_QUIET_SECONDS`
  - `TELEAPP_RELOAD_POLL_SECONDS`
  - `TELEAPP_WATCH_MODE` (`app-dir` or `app-file-only`)
  - `--watch <path>` for explicit watch paths

## Documentation

- Semantic shortcut policy: `SEMANTIC_SHORTCUTS.md`
- Dependency strategy and compatibility: `DEPENDENCY_STRATEGY.md`
- Quality gate before new features: `QUALITY_GATE_90.md`
- Operations runbook and troubleshooting: `RUNBOOK.md`
