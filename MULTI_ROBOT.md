# Multi-Robot 架構說明

## 概述

本專案已升級為支援多 robot 並發執行的架構。每個 robot instance 擁有獨立的 state file，並可透過檔案系統進行相互通訊與監看。

> 目前建議只記一套指令：`robotctl`。舊的 `start_robot.*`、`manage_robots.*`、`start_all.*`、`stop_all.*` 都只是相容 wrapper。

## 核心改動

### 1. 獨立 State 管理

- **原本**: 單一 `robot_state.json` 存所有狀態
- **現在**: 每個 robot 有獨立 state file: `robot_state_{robot_id}.json`
- **設定**: 透過 `ROBOT_ID` 環境變數指定 robot ID

### 2. Robot 間通訊層 (`robot/coordinator.py`)

提供以下功能：

- **狀態更新**: 每個 robot 定期更新自己的狀態（心跳機制）
- **狀態查詢**: 查詢所有 robot 或特定 robot 的狀態
- **訊息廣播**: robot 間可以廣播訊息
- **訊息訂閱**: 可以訂閱特定 topic 的訊息

### 3. 監看指令

新增兩個 Telegram 指令：

- `/robots` - 列出所有活躍的 robot 及其狀態
- `/robotstatus [robot_id]` - 查看特定 robot 的詳細狀態

## 啟動多個 Robot

### 配置檔準備

每個 robot 需要獨立的配置檔：

```bash
mkdir .robots
copy .env.example .robots\robot1.env
copy .env.example .robots\robot2.env
copy .env.example .robots\robot3.env
```

編輯每個配置檔，至少設定：
- `ROBOT_ID` - robot 識別碼（如 robot-1, robot-2, robot-3）
- `TELEAPP_TOKEN` - 該 robot 專用的 Telegram bot token
- `TELEAPP_ALLOWED_USER_ID` - 允許的使用者 ID
- 其他 provider 和 model 設定

### 啟動方式

使用統一的 `robotctl` CLI：

#### 1. 啟動單一 Robot

```bash
robotctl run robot1
robotctl run robot2
robotctl run mybot
```

#### 2. 啟動所有 Robot（背景執行）

```bash
robotctl start robot1
robotctl start all
robotctl status
robotctl logs robot1 -f
```

這會自動掃描所有 `.robots/*.env` 檔案，並在背景程序中啟動每個 robot。所有輸出會記錄到 `.robot_state/<config>.log`。

#### 3. 查看可用配置

```bash
robotctl list
robotctl /h
```

### 擴展性

這個設計支援任意數量的 robot：
- 需要 5 個 robot？建立 `.robots/robot1.env` 到 `.robots/robot5.env`
- 需要 10 個？建立 `.robots/robot1.env` 到 `.robots/robot10.env`
- 配置檔可以任意命名：`.robots/prod.env`、`.robots/dev.env`、`.robots/backup.env` 等

**安全提示**: 所有敏感資訊（bot token、API keys）都存放在配置檔中，不透過命令列參數傳遞，避免在 process list 或 shell history 中洩漏。

## Robot 管理工具

### 查看運行狀態

```bash
robotctl status
```

顯示所有運行中的 robot 程序和狀態檔案。

### 停止特定 Robot

```bash
robotctl stop robot1
```

### 停止所有 Robot

```bash
robotctl stop all
```

### 查看 Robot 日誌

```bash
robotctl logs robot1 -f
```

顯示特定 robot 的最近日誌（最後 100 行）。

### 相容 Wrapper

為了向後相容，仍保留以下 wrapper，但都會直接轉呼叫 `robotctl`：

- `start_robot.*`
- `manage_robots.*`
- `start_all.*`
- `stop_all.*`

## State 檔案結構

所有 state 檔案存放在 `.robot_state/` 目錄：

```
.robot_state/
├── robot_state_robot-1.json    # robot-1 的狀態
├── robot_state_robot-2.json    # robot-2 的狀態
├── robot_state_robot-3.json    # robot-3 的狀態
├── status/                      # robot 狀態檔案
│   ├── robot-1.json
│   ├── robot-2.json
│   └── robot-3.json
└── messages/                    # robot 間訊息
    └── *.json
```

## 使用範例

### 查看所有 robot

在 Telegram 中輸入：

```
/robots
```

輸出範例：

```
Active robots: 3

🟢 robot-1
  status: running
  provider: claude
  model: claude-sonnet-4-6
  chats: 2 | queue: 0
  last_seen: 5s ago

🟢 robot-2
  status: running
  provider: codex
  model: gpt-5.3-codex
  chats: 1 | queue: 1
  last_seen: 8s ago

🟡 robot-3
  status: idle
  provider: gemini
  model: gemini-2.5-pro
  chats: 0 | queue: 0
  last_seen: 45s ago
```

### 查看特定 robot 狀態

```
/robotstatus robot-2
```

輸出範例：

```
🟢 Robot Status: robot-2
status: running
provider: codex
model: gpt-5.3-codex
active_chats: 1
queue_size: 1
last_heartbeat: 8s ago
```

## 狀態指示器

- 🟢 綠色：最近 30 秒內有心跳（正常運行）
- 🟡 黃色：30-60 秒內有心跳（可能延遲）
- 🔴 紅色：超過 60 秒無心跳（可能已停止）

## 技術細節

### 心跳機制

每個 robot 每 15 秒更新一次狀態，包含：

- robot_id
- 當前狀態 (running/idle/stopped)
- 當前使用的 provider 和 model
- 活躍 chat 數量
- 佇列大小
- 最後心跳時間

### 訊息通訊

Robot 間可以透過檔案系統交換訊息：

```python
from robot.coordinator import RobotCoordinator

coordinator = RobotCoordinator(state_home, robot_id)

# 廣播訊息
coordinator.broadcast_message("task_complete", {"task_id": "123"})

# 接收訊息
messages = coordinator.get_messages(since=timestamp, topic="task_complete")
```

### 清理機制

舊訊息會自動清理（預設保留 1 小時）：

```python
coordinator.cleanup_old_messages(max_age_seconds=3600)
```

## 注意事項

1. **Bot Token**: 每個 robot 需要不同的 Telegram bot token，設定在各自的 `.robots/<name>.env` 檔案中
2. **配置檔安全**: `.robots/*.env` 檔案包含敏感資訊，已加入 `.gitignore`，請勿提交到版本控制
3. **Config Name vs ROBOT_ID**: 
   - **Config name**（如 `robot1`）用於啟動腳本和日誌檔案（`.robot_state/robot1.log`）
   - **ROBOT_ID**（配置檔內設定）用於執行時狀態檔案（`.robot_state/robot_state_<ROBOT_ID>.json`）和 Telegram 指令
   - `robotctl` 使用 config name 來操作
4. **單實例鎖**: 目前實作使用固定路徑 `.robot_state/robot.lock`。多 robot 並行執行依賴不同的 bot token 來區分實例。若遇到鎖衝突，請確認每個 robot 使用不同的 `TELEAPP_TOKEN`。
5. **State 隔離**: 每個 robot 的 chat state 完全獨立
6. **Address Book**: 通訊錄在所有 robot 間共享

## 向後相容

原有的啟動方式仍然可用，但只是相容 wrapper：

```bat
robotctl run default
```

這會使用預設的 robot ID（基於 bot token 的 hash）。
