# Robot

Teleapp-based Telegram task and agent router.

English | [繁體中文](./README.zh-TW.md)

> **⚠️ WARNING**
> This project is intended for users with an **IT / software engineering background**.
> It imposes very few restrictions on what AI agents can execute on your machine.
> Improper use may result in unintended file or directory deletion.
> **You are solely responsible for any data loss caused by misconfiguration or misuse.**

`robot` lets you control local coding/automation workflows from Telegram — route requests to different AI providers, manage task queues, schedules, and a second-brain note system, all in one bot process.

## Features

- Multi-provider AI routing: `claude`, `codex`, `gemini`
- Per-chat model switching (`/provider`, `/model`, `/models`)
- Workspace selection (`/project`, `/projects`)
- Agent task queue and status (`/queue`, `/agentstatus`, `/clearqueue`)
- Second-brain commands for notes, search, and scheduling
- Document import via `markitdown` pipeline
- Google Calendar sync
- Address book for mail recipients
- Multi-robot support (run multiple bot instances simultaneously)
- Single-instance lock and Telegram polling conflict protection

## Requirements

- Python `>=3.11`
- Telegram bot token and allowed user ID
- Teleapp runtime (installed via bootstrap)
- AI provider CLIs on PATH (install only what you use):
  - `claude` — for Claude provider
  - `codex` — for Codex provider
  - `gemini` — for Gemini provider

## Quick Start

### 1. Install dependencies

```bash
# Windows
bootstrap_robot.bat

# Linux / macOS
./bootstrap_robot.sh
```

### 2. Configure env file

```bash
mkdir .robots
copy .env.example .robots\default.env
```

Edit `.robots/default.env` and fill in at minimum:

| Variable | Description |
|---|---|
| `TELEAPP_TOKEN` | Telegram bot token |
| `TELEAPP_ALLOWED_USER_ID` | Your Telegram user ID |
| `ROBOT_DEFAULT_PROVIDER` | `claude` / `codex` / `gemini` |
| `ROBOT_DEFAULT_MODEL` | e.g. `claude-sonnet-4-6` |

### 3. Start the bot

```bash
robotctl run default        # foreground
robotctl start default      # background
robotctl /h                 # show all commands
```

## Multiple Robots

To run multiple bot instances with different configs:

```bash
copy .env.example .robots\robot1.env
copy .env.example .robots\robot2.env
# edit each file, set unique ROBOT_ID and TELEAPP_TOKEN
robotctl start all
robotctl status
robotctl stop robot1
robotctl restart robot1
robotctl logs robot1 -f
```

- Config name (e.g. `robot1`) maps to `.robots/robot1.env`
- `ROBOT_ID` inside the env file is used for runtime state files
- See [MULTI_ROBOT.md](./MULTI_ROBOT.md) for full details

## Common Commands

### General

| Command | Description |
|---|---|
| `/help` | Full command list |
| `/menu` | Button-based main menu |
| `/status` | Current provider / model / project / queue |
| `/doctor` | Diagnostics |
| `/quick` | One-page quick reference |

### Provider & Model

| Command | Description |
|---|---|
| `/provider <claude\|codex\|gemini>` | Switch AI provider |
| `/models` | List available models |
| `/model <name>` | Switch model |

### Project & Agent

| Command | Description |
|---|---|
| `/projects` | List workspaces |
| `/project <key>` | Switch workspace |
| `/run <goal>` | Run a task |
| `/agent [options] <goal>` | Run agent with options |
| `/queue` | Show task queue |
| `/agentstatus` | Show agent status |
| `/schedules` | Show scheduled tasks |
| `/schedule YYYY-MM-DD HH:MM <goal>` | Schedule a task |

### Brain (Second Brain)

| Command | Description |
|---|---|
| `/braininbox <text>` | Add note to inbox |
| `/brainsearch <query>` | Search notes |
| `/brainbatchauto [limit]` | Auto-process inbox |
| `/braindaily` | Today's summary |
| `/brainweekly` | Weekly summary |

### Control

| Command | Description |
|---|---|
| `/clearqueue` | Clear task queue |
| `/clearschedule` | Clear all schedules |
| `/reset` | Reset thread state |
| `/panic` | Emergency stop all tasks |
| `/restart` | Restart bot process |

### Multi-Robot

| Command | Description |
|---|---|
| `/robots` | List all active robot instances |
| `/robotstatus <robot_id>` | Detailed status for a specific robot |

## Environment Variables

### Required

| Variable | Description |
|---|---|
| `TELEAPP_TOKEN` | Telegram bot token |
| `TELEAPP_ALLOWED_USER_ID` | Allowed Telegram user ID |
| `ROBOT_DEFAULT_PROVIDER` | Default provider (`claude` / `codex` / `gemini`) |
| `ROBOT_DEFAULT_MODEL` | Default model name |

### Optional

| Variable | Description |
|---|---|
| `TELEAPP_APP` | Entry point (default: `robot.py`) |
| `ROBOT_ID` | Robot instance ID |
| `ROBOT_CODEX_CMD` | Custom codex CLI command |
| `ROBOT_CLAUDE_CMD` | Custom claude CLI command |
| `ROBOT_GEMINI_CMD` | Custom gemini CLI command |
| `ROBOT_CUSTOM_MODELS` | Comma-separated extra model names |
| `ROBOT_PROJECTS_ROOTS` | Semicolon-separated workspace root paths |
| `ROBOT_STATE_HOME` | State directory (default: `.robot_state`) |

### Google Calendar

| Variable | Description |
|---|---|
| `ROBOT_GOOGLE_CALENDAR_ENABLED` | `1` to enable |
| `ROBOT_GOOGLE_CALENDAR_CREDENTIALS_PATH` | OAuth credentials JSON path |
| `ROBOT_GOOGLE_CALENDAR_TOKEN_PATH` | Token cache path |
| `ROBOT_GOOGLE_CALENDAR_ID` | Calendar ID (default: `primary`) |
| `ROBOT_GOOGLE_CALENDAR_SCOPES` | OAuth scopes (comma or semicolon separated) |

### Security Flags (default: off)

| Variable | Default | Description |
|---|---|---|
| `ROBOT_CODEX_BYPASS_APPROVALS_AND_SANDBOX` | `0` | Bypass Codex sandboxing |
| `ROBOT_CODEX_SKIP_GIT_REPO_CHECK` | `0` | Skip git repo check for Codex |
| `ROBOT_CLAUDE_SKIP_PERMISSIONS` | `0` | Skip Claude permission prompts |

## Google Calendar Sync

1. Enable: set `ROBOT_GOOGLE_CALENDAR_ENABLED=1`
2. Authorize: `python scripts/google_calendar_auth.py`
3. For write access (create/delete events), set:
   ```
   ROBOT_GOOGLE_CALENDAR_SCOPES=https://www.googleapis.com/auth/calendar
   ```
   Then re-run the auth script.

Background sync runs every 5 minutes. Manual sync: `/schedule sync [push|pull|both] [days] [limit]`

## Address Book

Manage reusable mail recipients by alias:

```
/contact add <key> <email> <name>
/contact list
/contact show <key>
/contact remove <key>
/contact resolve <key>
```

Mail commands accept alias keys:

```
/mailcli -t <key_or_email> -s <subject> -bdy <body>
/mailjson <config.json>
/mailbatch <recipients.csv> <base_config.json>
```

## Troubleshooting

| Symptom | Action |
|---|---|
| Polling conflict error | Kill duplicate processes using the same token; keep only one instance |
| Task appears stuck | Check `/queue` and `/agentstatus`; use `/panic` if needed |
| Import errors after install | Re-run bootstrap; check `constraints.txt` |
| Bot not responding | Run `/doctor`; check logs with `robotctl logs default -f` |

## Development

```bash
pytest -q                                    # run tests
python scripts/google_calendar_auth.py       # one-time calendar auth
python scripts/check_release_consistency.py  # pre-release check
```

Project version: defined in [`robot/config.py`](./robot/config.py) and `pyproject.toml`.

## Related Docs

| File | Description |
|---|---|
| [MULTI_ROBOT.md](./MULTI_ROBOT.md) | Multi-robot setup and architecture |
| [FEATURES_GUIDE.md](./FEATURES_GUIDE.md) | Full command reference |
| [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) | One-page cheat sheet |
| [RUNBOOK.md](./RUNBOOK.md) | Operations runbook |
| [ROLLBACK.md](./ROLLBACK.md) | Rollback procedures |
| [DEPENDENCY_STRATEGY.md](./DEPENDENCY_STRATEGY.md) | Dependency upgrade policy |
