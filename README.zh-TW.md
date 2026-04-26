# Robot

以 Teleapp 為基礎的 Telegram 任務與 Agent 路由器。

[English](./README.md) | 繁體中文

`robot` 可以讓你在 Telegram 中控制本機開發/自動化流程，依需求切換不同 provider，並統一管理 queue、排程與第二大腦流程。

## 功能

- 多 provider 路由：`claude`、`codex`、`gemini`
- 每個 chat 可切換模型（`/provider`、`/model`、`/models`）
- 可選擇工作目錄（`/project`、`/projects`）
- Agent 佇列與狀態控制（`/queue`、`/agentstatus`、`/clearqueue`）
- 內建第二大腦指令（筆記、搜尋、行程）
- 文件匯入支援 `markitdown` 流程
- 內建單實例鎖與 Telegram polling conflict 保護

## 需求

- Python `>=3.11`
- Telegram bot token 與允許的 user id
- Teleapp runtime（依賴安裝後可用）
- 依 provider 需求，PATH 上可選擇安裝：
  - `claude`
  - `codex`
  - `gemini`

## 快速開始

1. 安裝依賴

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

2. 建立設定檔

```bash
copy .env.example .env
```

至少填入：

- `TELEAPP_TOKEN`
- `TELEAPP_ALLOWED_USER_ID`
- `ROBOT_DEFAULT_PROVIDER`
- `ROBOT_DEFAULT_MODEL`

3. 啟動 bot

Windows:

```bat
start_robot.bat
```

Linux/macOS:

```bash
./start_robot.sh
```

## 常用指令

- `/help`：指令總覽
- `/status`：目前 provider/model/project/queue 狀態
- `/contact list`、`/contact add <key> <email> <name>`
- `/provider <claude|codex|gemini>`
- `/model <model_name>`
- `/project <workspace>`
- `/queue`
- `/restart`
- `/brain`、`/brainsearch`、`/braininbox`、`/brainschedule`

## 重要環境變數

對照 `.env.example` 與 runtime 設定：

- `TELEAPP_TOKEN`
- `TELEAPP_ALLOWED_USER_ID`
- `TELEAPP_APP`（預設 `robot.py`）
- `ROBOT_DEFAULT_PROVIDER`
- `ROBOT_DEFAULT_MODEL`
- `ROBOT_CODEX_CMD`
- `ROBOT_CLAUDE_CMD`
- `ROBOT_CUSTOM_MODELS`（逗號分隔的自訂模型名稱）
- `ROBOT_GEMINI_CMD`
- `ROBOT_PROJECTS_ROOTS`
- `ROBOT_STATE_HOME`
- `ROBOT_GOOGLE_CALENDAR_ENABLED`
- `ROBOT_GOOGLE_CALENDAR_CREDENTIALS_PATH`
- `ROBOT_GOOGLE_CALENDAR_TOKEN_PATH`
- `ROBOT_GOOGLE_CALENDAR_ID`
- `ROBOT_GOOGLE_CALENDAR_SCOPES`

安全相關旗標（預設關閉）：

- `ROBOT_CODEX_BYPASS_APPROVALS_AND_SANDBOX=0`
- `ROBOT_CODEX_SKIP_GIT_REPO_CHECK=0`
- `ROBOT_CLAUDE_SKIP_PERMISSIONS=0`

## Hot Reload / 衝突備註

- 主要入口建議使用 `start_robot.bat` / `start_robot.sh`。
- `start_robot.bat` 預設 `TELEAPP_WATCH_MODE=app-file-only`，可降低重啟衝突。
- 應用程式有 Telegram polling conflict 處理，並使用 `.robot_state/robot.lock` 做單實例保護。
- 若仍發生 conflict crash，請確認同一 token 只有一個 bot 程序在跑。

## Google Calendar 同步

- `/schedule ...` 在啟用 Google Calendar 後，會嘗試同步建立/更新對應事件。
- `/schedule sync [push|pull|both] [days] [limit]` 可手動立即觸發同步。
- `/clearschedule` 會清空本地排程，且會嘗試刪除已綁定的 Google 事件。
- 背景同步每 5 分鐘執行一次，維持 `/schedule` 與 Google 行事曆一致。
- 若要使用可寫入同步（`/schedule`、`/clearschedule` 刪除）：
  - `ROBOT_GOOGLE_CALENDAR_SCOPES=https://www.googleapis.com/auth/calendar`
  - 重新執行 `python scripts/google_calendar_auth.py` 完成授權。

## 通訊錄

- 可用 alias 管理常用收件人：
  - `/contact add <key> <email> <name>`
  - `/contact list`
  - `/contact show <key>`
  - `/contact remove <key>`
  - `/contact alias <key> add <alias>`
  - `/contact resolve <target1> [target2] ...`
- 寄信指令可直接使用通訊錄 alias：
  - `/mailcli -t <key_or_email> -s <subject> -bdy <body_or_file>`
  - `/mailjson <config.json>`
  - `/mailbatch <recipients.csv> <base_config.json>`
  - `/mailmcp`

## 開發

執行測試：

```bash
pytest -q
```

Google Calendar 一次性授權：

```bash
python scripts/google_calendar_auth.py
```

專案版本定義於 [robot/config.py](./robot/config.py) 與 `pyproject.toml`（目前 `0.1.1`）。
