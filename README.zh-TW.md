# Robot

以 Teleapp 為基礎的 Telegram 任務與 Agent 路由器。

[English](./README.md) | 繁體中文

`robot` 可以讓你在 Telegram 中控制本機開發/自動化流程，依需求切換不同 provider，並統一管理 queue、排程與第二大腦流程。

## 功能

- 多 provider 路由：`codex`、`gemini`、`copilot`
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
  - `codex`
  - `gemini`
  - `copilot`

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
- `/provider <codex|gemini|copilot>`
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
- `ROBOT_GEMINI_CMD`
- `ROBOT_COPILOT_CMD`
- `ROBOT_PROJECTS_ROOTS`
- `ROBOT_STATE_HOME`

安全相關旗標（預設關閉）：

- `ROBOT_CODEX_BYPASS_APPROVALS_AND_SANDBOX=0`
- `ROBOT_CODEX_SKIP_GIT_REPO_CHECK=0`

## Hot Reload / 衝突備註

- 主要入口建議使用 `start_robot.bat` / `start_robot.sh`。
- `start_robot.bat` 預設 `TELEAPP_WATCH_MODE=app-file-only`，可降低重啟衝突。
- 應用程式有 Telegram polling conflict 處理，並使用 `.robot_state/robot.lock` 做單實例保護。
- 若仍發生 conflict crash，請確認同一 token 只有一個 bot 程序在跑。

## 開發

執行測試：

```bash
pytest -q
```

專案版本定義於 [robot/config.py](./robot/config.py) 與 `pyproject.toml`（目前 `0.1.1`）。
