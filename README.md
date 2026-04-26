# Robot

Teleapp-based Telegram task and agent router.

English | [Traditional Chinese](./README.zh-TW.md)

`robot` lets you control local coding/automation workflows from Telegram, route requests to different providers, and manage simple queue/brain/schedule flows in one bot process.

## Features

- Multi-provider routing: `claude`, `codex`, `gemini`
- Model switching per chat (`/provider`, `/model`, `/models`)
- Workspace selection (`/project`, `/projects`)
- Agent queue and status controls (`/queue`, `/agentstatus`, `/clearqueue`)
- Built-in "brain" commands for notes/search/schedule
- Document import via `markitdown` pipeline (configured in routing flow)
- Single-instance lock + polling conflict protection

## Requirements

- Python `>=3.11`
- Telegram bot token + allowed user id
- Teleapp runtime (installed via dependencies)
- Optional CLIs on PATH (depending on provider you use):
  - `claude`
  - `codex`
  - `gemini`

## Quick Start

1. Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

2. Configure env file

```bash
copy .env.example .env
```

Fill at least:

- `TELEAPP_TOKEN`
- `TELEAPP_ALLOWED_USER_ID`
- `ROBOT_DEFAULT_PROVIDER`
- `ROBOT_DEFAULT_MODEL`

3. Start bot

Windows:

```bat
start_robot.bat
```

Background mode (no interactive CMD window):

```bat
start_robot_bg.bat
```

Linux/macOS:

```bash
./start_robot.sh
```

Shutdown on Windows:

```bat
shutdown_robot.bat
```

## Common Commands

- `/help`: command list
- `/status`: current provider/model/project/queue summary
- `/contact list`, `/contact add <key> <email> <name>`
- `/provider <claude|codex|gemini>`
- `/model <model_name>`
- `/project <workspace>`
- `/queue`
- `/restart`
- `/brain`, `/brainsearch`, `/braininbox`, `/brainschedule`

## Important Env Vars

From `.env.example` and runtime config:

- `TELEAPP_TOKEN`
- `TELEAPP_ALLOWED_USER_ID`
- `TELEAPP_APP` (default `robot.py`)
- `ROBOT_DEFAULT_PROVIDER`
- `ROBOT_DEFAULT_MODEL`
- `ROBOT_CODEX_CMD`
- `ROBOT_CLAUDE_CMD`
- `ROBOT_CUSTOM_MODELS` (comma-separated custom model names)
- `ROBOT_GEMINI_CMD`
- `ROBOT_PROJECTS_ROOTS`
- `ROBOT_STATE_HOME`
- `ROBOT_GOOGLE_CALENDAR_ENABLED`
- `ROBOT_GOOGLE_CALENDAR_CREDENTIALS_PATH`
- `ROBOT_GOOGLE_CALENDAR_TOKEN_PATH`
- `ROBOT_GOOGLE_CALENDAR_ID`
- `ROBOT_GOOGLE_CALENDAR_SCOPES`

Security-related flags (default off):

- `ROBOT_CODEX_BYPASS_APPROVALS_AND_SANDBOX=0`
- `ROBOT_CODEX_SKIP_GIT_REPO_CHECK=0`
- `ROBOT_CLAUDE_SKIP_PERMISSIONS=0`

## Hot Reload / Conflict Notes

- Use `start_robot.bat` / `start_robot.sh` as primary entrypoint.
- If you want a background daemon style start on Windows, use `start_robot_bg.bat`.
- Default mode is `TELEAPP_HOT_RELOAD=0` (stable mode, fewer process layers/conflicts).
- If needed, temporarily enable hot reload with `set TELEAPP_HOT_RELOAD=1` before startup.
- The app has Telegram polling conflict handling and a single-instance lock in `.robot_state/robot.lock`.
- If you still see conflict crashes, ensure only one process is using the same bot token.

## Google Calendar Sync

- `/schedule ...` attempts to upsert a matching Google Calendar event when calendar sync is enabled.
- `/schedule sync [push|pull|both] [days] [limit]` triggers manual sync on demand.
- `/clearschedule` clears local schedules and also deletes linked Google events when available.
- Background sync runs every 5 minutes to keep `/schedule` and Google Calendar aligned.
- For write sync (`/schedule`, `/clearschedule` delete), use scope:
  - `ROBOT_GOOGLE_CALENDAR_SCOPES=https://www.googleapis.com/auth/calendar`
  - then re-authorize with `python scripts/google_calendar_auth.py`

## Address Book

- Manage reusable recipients by alias:
  - `/contact add <key> <email> <name>`
  - `/contact list`
  - `/contact show <key>`
  - `/contact remove <key>`
  - `/contact alias <key> add <alias>`
  - `/contact resolve <target1> [target2] ...`
- Mail commands can resolve aliases from address book:
  - `/mailcli -t <key_or_email> -s <subject> -bdy <body_or_file>`
  - `/mailjson <config.json>`
  - `/mailbatch <recipients.csv> <base_config.json>`
  - `/mailmcp`

## Development

Run tests:

```bash
pytest -q
```

Google Calendar one-time auth:

```bash
python scripts/google_calendar_auth.py
```

Project version is defined in [robot/config.py](./robot/config.py) and `pyproject.toml` (currently `0.1.1`).
