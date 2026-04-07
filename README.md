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

2. Copy `.env.example` to `.env` and fill in the Telegram values.

3. Start the app.

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
- `/provider [codex|gemini|copilot]`
- `/model [name]`
- `/models`
- `/projects`
- `/project [workspace-key-or-label]`
- `/reset`
- `/newthread`
- `/restart`
- `/agent <goal>`

## Notes

- `Codex` is the best-supported provider because it keeps a resumable `thread_id`.
- `Gemini` and `Copilot` are executed as plain subprocess commands and currently do not preserve thread state.
- `teleapp` handles Telegram polling, filtering, and per-chat request queues.

