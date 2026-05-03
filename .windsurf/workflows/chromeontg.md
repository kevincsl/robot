---
description: Drive headless Chrome and send screenshots to Telegram for remote web operation
---

Full docs: see `AGENTS.md` → **chromeontg** section.

```
python scripts/skills/chrome_tg_runner.py --steps <steps.json> --out-dir files
python scripts/skills/send_tg_file.py --file <path> --caption "<desc>"
```
