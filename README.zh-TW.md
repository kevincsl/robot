# Robot

以 Teleapp 為基礎的 Telegram 任務與 Agent 路由器。

[English](./README.md) | 繁體中文

> **⚠️ 警告**
> 本專案建議具備**資訊／軟體工程背景**的人員安裝使用。
> 本系統對 AI Agent 的執行限制非常少，操作不當可能導致檔案或目錄被刪除。
> **因設定錯誤或操作不當造成的任何資料損失，請自行負責。**

`robot` 讓你透過 Telegram 控制本機開發與自動化流程——將請求路由到不同 AI Provider、管理任務佇列、排程，以及第二大腦筆記系統，全部整合在一個 bot 程序中。

## 功能

- 多 Provider AI 路由：`claude`、`codex`、`gemini`
- 每個 chat 可切換模型（`/provider`、`/model`、`/models`）
- 工作目錄切換（`/project`、`/projects`）
- Agent 任務佇列與狀態管理（`/queue`、`/agentstatus`、`/clearqueue`）
- 第二大腦指令（筆記、搜尋、排程）
- 文件匯入支援 `markitdown` 流程
- Google Calendar 同步
- 通訊錄（郵件收件人管理）
- 多 Robot 支援（同時執行多個 bot 實例）
- 單實例鎖與 Telegram polling conflict 保護

## 需求

- Python `>=3.11`
- Telegram bot token 與允許的 user ID
- Teleapp runtime（bootstrap 安裝）
- AI Provider CLI（只需安裝你要用的）：
  - `claude` — Claude provider
  - `codex` — Codex provider
  - `gemini` — Gemini provider

## 快速開始

### 1. 安裝依賴

```bash
# Windows
bootstrap_robot.bat

# Linux / macOS
./bootstrap_robot.sh
```

### 2. 建立設定檔

```bash
mkdir .robots
copy .env.example .robots\default.env
```

編輯 `.robots/default.env`，至少填入：

| 變數 | 說明 |
|---|---|
| `TELEAPP_TOKEN` | Telegram bot token |
| `TELEAPP_ALLOWED_USER_ID` | 你的 Telegram user ID |
| `ROBOT_DEFAULT_PROVIDER` | `claude` / `codex` / `gemini` |
| `ROBOT_DEFAULT_MODEL` | 例如 `claude-sonnet-4-6` |

### 3. 啟動 bot

```bash
robotctl run default        # 前景執行
robotctl start default      # 背景執行
robotctl /h                 # 顯示所有指令
```

## 多 Robot

同時執行多個不同設定的 bot 實例：

```bash
copy .env.example .robots\robot1.env
copy .env.example .robots\robot2.env
# 編輯每個檔案，設定不同的 ROBOT_ID 與 TELEAPP_TOKEN
robotctl start all
robotctl status
robotctl stop robot1
robotctl restart robot1
robotctl logs robot1 -f
```

- 配置名稱（例如 `robot1`）對應 `.robots/robot1.env`
- env 檔內的 `ROBOT_ID` 用於執行時的狀態檔案
- 詳細說明請參考 [MULTI_ROBOT.md](./MULTI_ROBOT.md)

## 常用指令

### 一般操作

| 指令 | 說明 |
|---|---|
| `/help` | 完整指令表 |
| `/menu` | 按鈕式主選單 |
| `/status` | 目前 provider / model / project / queue 狀態 |
| `/doctor` | 診斷資訊 |
| `/quick` | 一頁速查 |

### Provider 與模型

| 指令 | 說明 |
|---|---|
| `/provider <claude\|codex\|gemini>` | 切換 AI provider |
| `/models` | 列出可用模型 |
| `/model <name>` | 切換模型 |

### 專案與 Agent

| 指令 | 說明 |
|---|---|
| `/projects` | 列出工作目錄 |
| `/project <key>` | 切換工作目錄 |
| `/run <goal>` | 執行任務 |
| `/agent [options] <goal>` | 以選項執行 agent |
| `/queue` | 顯示任務佇列 |
| `/agentstatus` | 顯示 agent 狀態 |
| `/schedules` | 顯示已排程任務 |
| `/schedule YYYY-MM-DD HH:MM <goal>` | 新增排程任務 |

### 第二大腦（Brain）

| 指令 | 說明 |
|---|---|
| `/braininbox <text>` | 新增筆記到收件匣 |
| `/brainsearch <query>` | 搜尋筆記 |
| `/brainbatchauto [limit]` | 自動批次整理收件匣 |
| `/braindaily` | 今日摘要 |
| `/brainweekly` | 每週摘要 |

### 控制類

| 指令 | 說明 |
|---|---|
| `/clearqueue` | 清空任務佇列 |
| `/clearschedule` | 清空所有排程 |
| `/reset` | 重置對話狀態 |
| `/panic` | 緊急停止所有任務 |
| `/restart` | 重啟 bot 程序 |

### 多 Robot

| 指令 | 說明 |
|---|---|
| `/robots` | 列出所有活躍的 robot 實例 |
| `/robotstatus <robot_id>` | 顯示特定 robot 的詳細狀態 |

## 環境變數

### 必填

| 變數 | 說明 |
|---|---|
| `TELEAPP_TOKEN` | Telegram bot token |
| `TELEAPP_ALLOWED_USER_ID` | 允許的 Telegram user ID |
| `ROBOT_DEFAULT_PROVIDER` | 預設 provider（`claude` / `codex` / `gemini`） |
| `ROBOT_DEFAULT_MODEL` | 預設模型名稱 |

### 選填

| 變數 | 說明 |
|---|---|
| `TELEAPP_APP` | 入口程式（預設：`robot.py`） |
| `ROBOT_ID` | Robot 實例 ID |
| `ROBOT_CODEX_CMD` | 自訂 codex CLI 指令 |
| `ROBOT_CLAUDE_CMD` | 自訂 claude CLI 指令 |
| `ROBOT_GEMINI_CMD` | 自訂 gemini CLI 指令 |
| `ROBOT_CUSTOM_MODELS` | 逗號分隔的自訂模型名稱 |
| `ROBOT_PROJECTS_ROOTS` | 分號分隔的工作目錄根路徑 |
| `ROBOT_STATE_HOME` | 狀態目錄（預設：`.robot_state`） |

### Google Calendar

| 變數 | 說明 |
|---|---|
| `ROBOT_GOOGLE_CALENDAR_ENABLED` | `1` 以啟用 |
| `ROBOT_GOOGLE_CALENDAR_CREDENTIALS_PATH` | OAuth 憑證 JSON 路徑 |
| `ROBOT_GOOGLE_CALENDAR_TOKEN_PATH` | Token 快取路徑 |
| `ROBOT_GOOGLE_CALENDAR_ID` | 行事曆 ID（預設：`primary`） |
| `ROBOT_GOOGLE_CALENDAR_SCOPES` | OAuth scopes（逗號或分號分隔） |

### 安全旗標（預設關閉）

| 變數 | 預設 | 說明 |
|---|---|---|
| `ROBOT_CODEX_BYPASS_APPROVALS_AND_SANDBOX` | `0` | 略過 Codex 沙盒機制 |
| `ROBOT_CODEX_SKIP_GIT_REPO_CHECK` | `0` | 略過 Codex git repo 檢查 |
| `ROBOT_CLAUDE_SKIP_PERMISSIONS` | `0` | 略過 Claude 權限確認 |

## Google Calendar 同步

1. 啟用：設定 `ROBOT_GOOGLE_CALENDAR_ENABLED=1`
2. 授權：`python scripts/google_calendar_auth.py`
3. 如需寫入權限（建立/刪除事件），設定：
   ```
   ROBOT_GOOGLE_CALENDAR_SCOPES=https://www.googleapis.com/auth/calendar
   ```
   然後重新執行授權腳本。

背景同步每 5 分鐘執行一次。手動同步：`/schedule sync [push|pull|both] [days] [limit]`

## 通訊錄

以 alias 管理常用郵件收件人：

```
/contact add <key> <email> <name>
/contact list
/contact show <key>
/contact remove <key>
/contact resolve <key>
```

寄信指令可使用 alias：

```
/mailcli -t <key_or_email> -s <subject> -bdy <body>
/mailjson <config.json>
/mailbatch <recipients.csv> <base_config.json>
```

## 疑難排解

| 症狀 | 處理方式 |
|---|---|
| Polling conflict 錯誤 | 終止使用同一 token 的重複程序，只保留單一實例 |
| 任務卡住 | 查看 `/queue` 與 `/agentstatus`；必要時用 `/panic` |
| 安裝後 import 錯誤 | 重新執行 bootstrap；檢查 `constraints.txt` |
| Bot 無回應 | 執行 `/doctor`；用 `robotctl logs default -f` 查看日誌 |

## 開發

```bash
pytest -q                                    # 執行測試
python scripts/google_calendar_auth.py       # 一次性行事曆授權
python scripts/check_release_consistency.py  # 發布前檢查
```

專案版本定義於 [`robot/config.py`](./robot/config.py) 與 `pyproject.toml`。

## 相關文件

| 檔案 | 說明 |
|---|---|
| [MULTI_ROBOT.md](./MULTI_ROBOT.md) | 多 Robot 架構與設定 |
| [FEATURES_GUIDE.md](./FEATURES_GUIDE.md) | 完整指令參考 |
| [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) | 一頁速查表 |
| [RUNBOOK.md](./RUNBOOK.md) | 維運操作手冊 |
| [ROLLBACK.md](./ROLLBACK.md) | 回滾程序 |
| [DEPENDENCY_STRATEGY.md](./DEPENDENCY_STRATEGY.md) | 依賴升級策略 |
