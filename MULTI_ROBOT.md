# Multi-Robot 架構說明

## 概述

本專案已升級為支援多 robot 並發執行的架構。每個 robot instance 擁有獨立的 state file，並可透過檔案系統進行相互通訊與監看。

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

### Windows

```bat
# 啟動第一個 robot (使用 .env 中的 token)
start_robot_multi.bat robot-1

# 啟動第二個 robot (指定不同的 bot token)
start_robot_multi.bat robot-2 YOUR_BOT_TOKEN_2

# 啟動第三個 robot
start_robot_multi.bat robot-3 YOUR_BOT_TOKEN_3
```

### Linux/macOS

```bash
# 啟動第一個 robot
./start_robot_multi.sh robot-1

# 啟動第二個 robot (指定不同的 bot token)
./start_robot_multi.sh robot-2 YOUR_BOT_TOKEN_2

# 啟動第三個 robot
./start_robot_multi.sh robot-3 YOUR_BOT_TOKEN_3
```

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

1. **Bot Token**: 每個 robot 需要不同的 Telegram bot token
2. **檔案鎖**: 原有的單實例鎖 (`robot.lock`) 仍然存在，但現在是針對每個 bot token
3. **State 隔離**: 每個 robot 的 chat state 完全獨立
4. **Address Book**: 通訊錄在所有 robot 間共享

## 向後相容

原有的啟動方式仍然可用：

```bat
# Windows
start_robot.bat

# Linux/macOS
./start_robot.sh
```

這會使用預設的 robot ID（基於 bot token 的 hash）。
