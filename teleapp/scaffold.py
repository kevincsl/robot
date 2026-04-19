from __future__ import annotations

from pathlib import Path


APP_TEMPLATE = """from teleapp import TeleApp

app = TeleApp()


@app.message
async def handle_message(ctx):
    return f"echo: {ctx.text}"


if __name__ == "__main__":
    app.run()
"""


ENV_TEMPLATE = """TELEAPP_TOKEN=<telegram-bot-token>
TELEAPP_ALLOWED_USER_ID=<telegram-user-id>
"""


README_TEMPLATE = """# teleapp app

This app uses teleapp as the Telegram runtime.

## Setup

1. Create `.env` from `.env.example`
2. Fill in `TELEAPP_TOKEN` and `TELEAPP_ALLOWED_USER_ID`
3. Run:

```powershell
python app.py
```
"""


def create_project(target: str | Path) -> Path:
    base = Path(target).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    (base / "app.py").write_text(APP_TEMPLATE, encoding="utf-8")
    (base / ".env.example").write_text(ENV_TEMPLATE, encoding="utf-8")
    (base / "README.md").write_text(README_TEMPLATE, encoding="utf-8")
    return base
