# teleapp

`teleapp` is a Telegram-hosted Python app runtime with a decorator-based application model.

The project lets you write local Python apps that behave like Telegram services without teaching those apps about the Telegram Bot API directly.

At this stage, `teleapp` supports:

- subprocess-hosted apps over `stdin/stdout`
- in-process handlers and decorators
- per-chat request queues
- hot reload with debounce
- crash auto-restart
- first media batch: photo, document, location, sticker, and buttons/callbacks
- `.env`-based configuration
- a small public API surface designed for reuse

## Quick start

### 1. Install from GitHub

Windows:

```powershell
python -m venv .venv
.venv\Scripts\pip install "git+https://github.com/kevincsl/teleapp.git@main"
```

Linux/macOS:

```bash
python -m venv .venv
.venv/bin/pip install "git+https://github.com/kevincsl/teleapp.git@main"
```

To pin a version, prefer a tag:

```powershell
.venv\Scripts\pip install "git+https://github.com/kevincsl/teleapp.git@v0.1.0"
```

### 2. Create your app or install from source

Create a starter app with the installed CLI:

```powershell
.venv\Scripts\teleapp init my_teleapp_app
```

If you are developing `teleapp` itself from this repository, bootstrap the local project instead:

Windows:

```powershell
bootstrap_teleapp.bat
```

Linux/macOS:

```bash
./bootstrap_teleapp.sh
```

### 3. Create `.env`

Start from [`.env.example`](/C:/Users/kevin/codex/tgrobot/teleapp/.env.example) and fill at least:

```env
TELEAPP_TOKEN=<telegram-bot-token>
TELEAPP_ALLOWED_USER_ID=<telegram-user-id>
TELEAPP_APP=examples/hello_app.py
```

### 4. Run the bundled example

Windows:

```powershell
start_teleapp.bat
```

Linux/macOS:

```bash
./start_teleapp.sh
```

The bot will start polling Telegram and forward text into the hosted app.

Example files:

- [`examples/hello_app.py`](/C:/Users/kevin/codex/tgrobot/teleapp/examples/hello_app.py)
  recommended starting point for learning teleapp
- [`examples/echo_app.py`](/C:/Users/kevin/codex/tgrobot/teleapp/examples/echo_app.py)
  subprocess-contract example
- [`examples/media_app.py`](/C:/Users/kevin/codex/tgrobot/teleapp/examples/media_app.py)
  first media-enabled example
- [`examples/media_audio_app.py`](/C:/Users/kevin/codex/tgrobot/teleapp/examples/media_audio_app.py)
  second media batch example for voice, audio, and sticker
- [`examples/media_misc_app.py`](/C:/Users/kevin/codex/tgrobot/teleapp/examples/media_misc_app.py)
  third media batch example for video, poll, and contact
- [`examples/media_ai_app.py`](/C:/Users/kevin/codex/tgrobot/teleapp/examples/media_ai_app.py)
  AI-focused example for animation and venue
- [`examples/callback_app.py`](/C:/Users/kevin/codex/tgrobot/teleapp/examples/callback_app.py)
  callback query / inline button example

## Packaging

`teleapp` can be built as a standard Python source distribution and wheel, then installed into a fresh virtual environment with `pip`.

If you do not want to publish to PyPI, users can install straight from GitHub because the project already exposes standard Python package metadata in [`pyproject.toml`](/C:/Users/kevin/codex/tgrobot/teleapp/pyproject.toml).

For maintainers, the GitHub tag and release flow is documented in [`RELEASE.md`](/C:/Users/kevin/codex/tgrobot/teleapp/RELEASE.md).

Build artifacts:

- `dist/teleapp-<version>.tar.gz`
- `dist/teleapp-<version>-py3-none-any.whl`

Build from this repo:

Windows:

```powershell
build_teleapp.bat
```

Linux/macOS:

```bash
./build_teleapp.sh
```

Manual equivalent:

```powershell
python -m pip install --upgrade build
python -m build
```

Install into a new virtual environment from the built wheel:

```powershell
python -m venv .venv
.venv\Scripts\pip install .\dist\teleapp-0.1.0-py3-none-any.whl
```

You can also install directly from the project directory without building a wheel first:

```powershell
python -m venv .venv
.venv\Scripts\pip install C:\path\to\teleapp
```

Install directly from GitHub:

```powershell
python -m venv .venv
.venv\Scripts\pip install "git+https://github.com/kevincsl/teleapp.git@main"
```

Install a specific tag or commit:

```powershell
.venv\Scripts\pip install "git+https://github.com/kevincsl/teleapp.git@v0.1.0"
.venv\Scripts\pip install "git+https://github.com/kevincsl/teleapp.git@<commit-sha>"
```

For a private repository, use SSH instead:

```powershell
.venv\Scripts\pip install "git+ssh://git@github.com/kevincsl/teleapp.git@main"
```

After installation, the `teleapp` CLI is available inside that environment:

```powershell
.venv\Scripts\teleapp init my_teleapp_app
```

## Core idea

There are two supported hosting modes.

### Subprocess mode

`teleapp` launches a Python file as a subprocess and talks to it over JSONL:

- input: `stdin`
- output: `stdout`
- errors: `stderr`

Example input:

```json
{"type":"input","chat_id":123,"request_id":"123-1","text":"hello"}
```

Example output:

```json
{"type":"output","chat_id":123,"request_id":"123-1","text":"echo: hello"}
```

### In-process mode

Instead of launching a subprocess, you attach Python callables or handler objects directly to `TeleApp`.

This is the mode that gives teleapp its decorator-based application style.

## App usage

### Minimal app

```python
from teleapp import TeleApp

app = TeleApp()


@app.message
async def handle_message(ctx):
    return f"echo: {ctx.text}"


if __name__ == "__main__":
    app.run()
```

### Command handlers

```python
from teleapp import TeleApp

app = TeleApp()


@app.command("/hello")
async def hello(ctx):
    return f"hello {ctx.text}"


if __name__ == "__main__":
    app.run()
```

### Route handlers

```python
from teleapp import TeleApp

app = TeleApp()


@app.route(lambda ctx: ctx.text.startswith("ping"))
async def ping_route(ctx):
    return "pong"


@app.message
async def fallback(ctx):
    return f"default: {ctx.text}"


if __name__ == "__main__":
    app.run()
```

### Handler object

```python
from teleapp import TeleApp


class MyHandler:
    async def on_text(self, ctx):
        return f"handled: {ctx.text}"


app = TeleApp()
app.attach_handler(MyHandler())


if __name__ == "__main__":
    app.run()
```

## Hooks

The current hook surface:

- `@app.before_message`
- `@app.after_message`
- `@app.on_error`
- `@app.on_startup`
- `@app.on_shutdown`

Example:

```python
from teleapp import TeleApp

app = TeleApp()


@app.on_startup
async def startup():
    print("starting")


@app.before_message
async def before(ctx):
    print("before", ctx.text)


@app.after_message
async def after(ctx, response):
    print("after", response.text)


@app.on_error
async def on_error(ctx, exc):
    print("error", exc)


@app.message
async def handler(ctx):
    return f"echo: {ctx.text}"
```

## Response model

Handlers may return:

- plain `str`
- `None`
- [`Response`](/C:/Users/kevin/codex/tgrobot/teleapp/teleapp/response.py)
- [`TextResponse`](/C:/Users/kevin/codex/tgrobot/teleapp/teleapp/response.py)
- [`StatusResponse`](/C:/Users/kevin/codex/tgrobot/teleapp/teleapp/response.py)
- [`ErrorResponse`](/C:/Users/kevin/codex/tgrobot/teleapp/teleapp/response.py)
- [`PhotoResponse`](/C:/Users/kevin/codex/tgrobot/teleapp/teleapp/response.py)
- [`DocumentResponse`](/C:/Users/kevin/codex/tgrobot/teleapp/teleapp/response.py)
- [`LocationResponse`](/C:/Users/kevin/codex/tgrobot/teleapp/teleapp/response.py)
- [`StickerResponse`](/C:/Users/kevin/codex/tgrobot/teleapp/teleapp/response.py)
- [`ButtonResponse`](/C:/Users/kevin/codex/tgrobot/teleapp/teleapp/response.py)
- [`AnimationResponse`](/C:/Users/kevin/codex/tgrobot/teleapp/teleapp/response.py)
- [`VenueResponse`](/C:/Users/kevin/codex/tgrobot/teleapp/teleapp/response.py)
- [`AppEvent`](/C:/Users/kevin/codex/tgrobot/teleapp/teleapp/protocol.py)

Examples:

```python
from teleapp import ErrorResponse, StatusResponse, TeleApp, TextResponse

app = TeleApp()


@app.command("/ping")
async def ping(ctx):
    return TextResponse("pong")


@app.command("/noop")
async def noop(ctx):
    return StatusResponse("nothing to do")


@app.command("/fail")
async def fail(ctx):
    return ErrorResponse("something failed")
```

Media examples:

```python
from teleapp import Button, ButtonResponse, LocationResponse, PhotoResponse

@app.command("/where")
async def where(ctx):
    return LocationResponse(text="Taipei", latitude=25.0330, longitude=121.5654)

@app.command("/menu")
async def menu(ctx):
    return ButtonResponse("Choose one", buttons=[Button("A", "choice:a"), Button("B", "choice:b")])

@app.command("/image")
async def image(ctx):
    return PhotoResponse(text="", file_path="output/demo.png", caption="demo")
```

## First media batch

The first integrated Telegram-native I/O batch now includes:

- photo input/output
- document input/output
- location input/output
- sticker input/output
- callback buttons output

Current context fields added for this batch:

- `photos`
- `document`
- `sticker`
- `location`
- `callback_query`

## Second media batch

The second integrated Telegram-native I/O batch now includes:

- voice input/output
- audio input/output
- sticker output as a first-class response type

Current context fields relevant for this batch:

- `voice`
- `audio`
- `sticker`

Current response types relevant for this batch:

- `VoiceResponse`
- `AudioResponse`
- `StickerResponse`

## Third media batch

The third integrated Telegram-native I/O batch now includes:

- video input/output
- poll input/output
- contact input/output

Current context fields relevant for this batch:

- `video`
- `poll`
- `contact`

Current response types relevant for this batch:

- `VideoResponse`
- `PollResponse`
- `ContactResponse`

## Additional AI-relevant types

Additional Telegram-native types now included because they are practical for AI app workflows:

- `animation`
- `venue`

Current context fields:

- `animation`
- `venue`

Current response types:

- `AnimationResponse`
- `VenueResponse`

## Configuration

`teleapp` should be configured primarily through `.env`.

Important variables:

- `TELEAPP_TOKEN`
- `TELEAPP_ALLOWED_USER_ID`
- `TELEAPP_CHAT_ID`
- `TELEAPP_APP`
- `TELEAPP_PYTHON`
- `TELEAPP_HOT_RELOAD`
- `TELEAPP_AUTO_RESTART_ON_CRASH`
- `TELEAPP_RELOAD_QUIET_SECONDS`
- `TELEAPP_RELOAD_POLL_SECONDS`
- `TELEAPP_RESTART_BACKOFF_SECONDS`
- `TELEAPP_WATCH_MODE`

The full template lives in [`.env.example`](/C:/Users/kevin/codex/tgrobot/teleapp/.env.example).

## Dispatch priority

Current in-process dispatch order is fixed:

1. command handler
2. route handler
3. default message handler

Before and after that:

- all `before_message` hooks run before the selected handler
- all `after_message` hooks run after the handler response is normalized
- `on_error` hooks run if dispatch raises

## Hot reload watch mode

The hosted app process that gets restarted is always `TELEAPP_APP`.

The watched files that trigger that restart are configurable:

- `app-dir`
  default mode; watch the hosted app directory
- `app-file-only`
  watch only the hosted app file itself

Current default:

- `TELEAPP_WATCH_MODE=app-dir`

This means:

- `teleapp myapp.py` restarts `myapp.py`
- file changes are watched in the app directory by default
- `teleapp` framework files are not watched unless you explicitly add them

## Queue and session model

The current runtime uses:

- one global execution lane
- one queue per chat
- preserved ordering within each chat
- serialized dispatch across all chats

This means:

- chat A cannot overtake its own earlier messages
- chat B can queue while chat A is active
- requests are completed one at a time

The current session state is runtime-only and not persisted across restarts.

## Status output

`/status` currently reports:

- running state
- current pid
- configured app path
- busy state
- active chat id
- active request id
- total queued request count
- last restart reason
- last error
- per-chat queue summary

## Stability behavior

Implemented:

- stale exit event protection
- per-chat queue ordering
- deferred reload while requests are active
- crash auto-restart with backoff

Still pending:

- real Telegram integration stress testing
- long-running soak tests outside unit tests
- repeated real filesystem hot reload under live edits

## Public API

Public modules:

- `teleapp`
- `teleapp.app`
- `teleapp.config`
- `teleapp.context`
- `teleapp.protocol`
- `teleapp.response`

Public objects:

- `TeleApp`
- `TeleappConfig`
- `MessageContext`
- `AppEvent`
- `Response`
- `TextResponse`
- `StatusResponse`
- `ErrorResponse`
- `build_parser`
- `build_runtime_config`
- `load_config`
- `encode_input_event`
- `decode_output_line`

Internal runtime modules that should not be imported unless you are extending internals:

- `teleapp.runner`
- `teleapp.supervisor`
- `teleapp.telegram_gateway`
- `teleapp.hot_reload`
- `teleapp.state`
- `teleapp.scaffold`

## Scaffold command

Create a starter app:

```powershell
python -m teleapp init my_teleapp_app
```

This generates:

- `app.py`
- `.env.example`
- `README.md`

## Stability scripts

These scripts are intended for manual or semi-automated stability checks:

- [`scripts/run_soak.py`](/C:/Users/kevin/codex/tgrobot/teleapp/scripts/run_soak.py)
  Runs a larger multi-chat request batch and verifies response ordering.

- [`scripts/run_reload_probe.py`](/C:/Users/kevin/codex/tgrobot/teleapp/scripts/run_reload_probe.py)
  Confirms that a restart changes the hosted process pid.

- [`scripts/run_telegram_smoke.py`](/C:/Users/kevin/codex/tgrobot/teleapp/scripts/run_telegram_smoke.py)
  Verifies `.env` prerequisites before doing a manual Telegram smoke test.

Example:

```powershell
python scripts/run_soak.py --requests 200 --chats 5 --report-dir reports
python scripts/run_reload_probe.py --app examples/echo_app.py
python scripts/run_telegram_smoke.py
python scripts/build_report_index.py
```

`run_soak.py` writes both:

- a JSON report
- a Markdown report

This is intended to support both machine-readable review and human-readable review.

Use [`scripts/build_report_index.py`](/C:/Users/kevin/codex/tgrobot/teleapp/scripts/build_report_index.py) to rebuild:

- `reports/index.json`
- `reports/README.md`

## Project layout

```text
teleapp/
  .env.example
  bootstrap_teleapp.bat
  bootstrap_teleapp.sh
  build_teleapp.bat
  build_teleapp.sh
  PLAN.md
  RELEASE.md
  pyproject.toml
  README.md
  scripts/
    build_report_index.py
    run_reload_probe.py
    run_soak.py
    run_telegram_smoke.py
  start_teleapp.bat
  start_teleapp.sh
  examples/
    echo_app.py
  teleapp/
    __init__.py
    __main__.py
    app.py
    cli.py
    config.py
    context.py
    handlers.py
    hot_reload.py
    protocol.py
    response.py
    runner.py
    scaffold.py
    state.py
    supervisor.py
    telegram_gateway.py
  tests/
    test_app.py
    test_config.py
    test_gateway.py
    test_protocol.py
    test_supervisor.py
```

## Testing

Run all tests:

```powershell
python -m unittest discover -s tests -v
```

Current automated coverage includes:

- public facade construction
- config loading and env defaults
- protocol encode/decode
- gateway rendering and status output
- command/route/hook registration
- in-process dispatch behavior
- per-chat queue ordering
- stale exit handling
- crash auto-restart
- reload deferral under in-flight requests
- repeated multi-request stability checks

Manual helper coverage now also exists for:

- soak runs
- restart probes
- Telegram prerequisite smoke checks

## Limitations

Current limitations still worth keeping in mind:

- only one hosted app per runtime process
- only one allowed Telegram user
- media support is implemented in batches and not every Telegram type is covered yet
- no persistent request replay
- hot reload is still polling-based
- no real-world Telegram soak test has been completed yet

## Read next

- High-level architecture and maintenance memory: [`LLM_MEMORY.md`](/C:/Users/kevin/codex/tgrobot/teleapp/LLM_MEMORY.md)
- Runtime architecture: [`ARCHITECTURE.md`](/C:/Users/kevin/codex/tgrobot/teleapp/ARCHITECTURE.md)
- Operational runbook: [`OPERATIONS.md`](/C:/Users/kevin/codex/tgrobot/teleapp/OPERATIONS.md)
- Historical design direction: [`PLAN.md`](/C:/Users/kevin/codex/tgrobot/teleapp/PLAN.md)
