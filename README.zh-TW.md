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
mkdir .robots
copy .env.example .robots\default.env
```

至少填入：

- `TELEAPP_TOKEN`
- `TELEAPP_ALLOWED_USER_ID`
- `ROBOT_DEFAULT_PROVIDER`
- `ROBOT_DEFAULT_MODEL`

3. 啟動 bot

建議統一使用：

```bash
robotctl /h
```

### 單一 Robot

```bash
robotctl run default
# 或：python robotctl.py run default
```

### 多個 Robot（背景執行）

若要同時執行多個不同配置的 robot：

1. 建立配置檔：
```bash
copy .env.example .robots\robot1.env
copy .env.example .robots\robot2.env
```

2. 編輯每個配置檔，設定不同的：
   - `ROBOT_ID`（例如 `robot-claude`、`robot-codex`）
   - `TELEAPP_TOKEN`（每個 robot 使用不同的 bot token）
   - Provider/model 設定

3. 啟動 / 管理 robot：
```bash
robotctl start robot1
robotctl start all
robotctl status
robotctl stop robot1
robotctl restart robot1
robotctl logs robot1 -f
```

詳細的多 robot 設定請參考 [MULTI_ROBOT.md](./MULTI_ROBOT.md)。

**注意**：配置名稱會直接對應 `.robots/<name>.env`（例如 `robot1` => `.robots/robot1.env`）。配置檔內的 `ROBOT_ID` 用於執行時的狀態檔案。
舊的 `start_robot.*`、`manage_robots.*`、`start_all.*`、`stop_all.*` 仍可用，但現在都只是轉呼叫 `robotctl` 的相容 wrapper。
舊的設定檔命名如 `.env`、`.env.<name>` 已不再支援；請改成 `.robots/<name>.env`。

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

### 多 Robot 指令

當執行多個 robot 時：

- `/robots`：列出所有活躍的 robot 及其狀態
- `/robotstatus <robot_id>`：顯示特定 robot 的詳細狀態

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

- 主要入口建議使用 `robotctl run <config>` 或 `robotctl start <config|all>`。
- 預設模式為 `TELEAPP_HOT_RELOAD=0`（穩定模式，較少程序層級衝突）。
- 每個 robot 實例使用基於其 bot token 的單實例鎖來防止 polling 衝突。
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

專案版本定義於 [robot/config.py](./robot/config.py) 與 `pyproject.toml`（目前 `1.0.0`）。
