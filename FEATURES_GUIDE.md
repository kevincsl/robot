# FEATURES GUIDE

`robot` 是一個以 Telegram 為入口的工作路由器，核心目標是把「聊天指令」、「AI 任務」、「第二大腦整理」整合在同一個 bot。

## 1. 功能定位

- 在 Telegram 內切換 provider / model / project。
- 把一般訊息送進 AI provider 執行。
- 用 deterministic slash commands 做穩定操作（狀態、排程、清理、第二大腦）。
- 透過 queue/schedule 管理長任務，降低手動操作成本。

## 2. 指令分層

### 2.1 一般操作

- `/help`: 完整指令表
- `/quick`: 一頁速查
- `/guide`: 文件入口
- `/menu`: 按鈕式主選單
- `/status`: 目前 provider/model/project/queue 狀態
- `/doctor`: 診斷資訊
- `/queue`: 目前任務佇列
- `/schedules`: 已排定任務
- `/agentstatus`: agent 執行狀態
- `/agentprofiles`: agent profile 資訊

### 2.1.1 多 Robot 操作

當執行多個 robot 實例時：

- `/robots`: 列出所有活躍的 robot 及其狀態
- `/robotstatus <robot_id>`: 顯示特定 robot 的詳細狀態

Shell 管理工具（用於背景執行的多 robot）：

```bat
# Windows
manage_robots.bat status      # 查看所有運行中的 robot
manage_robots.bat stop robot1 # 停止特定 robot
manage_robots.bat stopall     # 停止所有 robot
manage_robots.bat logs robot1 # 查看 robot 日誌

# Linux/macOS
./manage_robots.sh status
./manage_robots.sh stop robot1
./manage_robots.sh stopall
./manage_robots.sh logs robot1
```

詳細說明請參考 [MULTI_ROBOT.md](./MULTI_ROBOT.md)。

### 2.2 Workspace / Provider

- `/provider [claude|codex|gemini]`
- `/models`
- `/model <name>`
- `/projects`
- `/project <key-or-label>`

### 2.3 第二大腦（Brain）

- `/brain`: 進入 brain 功能選單
- `/brainread`
- `/braininbox <text>`
- `/brainweb <url>`
- `/brainsearch <query>`
- `/brainorganize`
- `/brainbatch`
- `/brainbatchauto [limit]`
- `/brainproject <title>`
- `/brainknowledge <title>`
- `/brainresource <title>`
- `/brainschedule <title-or-natural-language>`
- `/braindecide <question>`
- `/brainsummary`
- `/brainremind`
- `/braindaily`
- `/brainweekly`
- `/brainauto [on|off|status]`
- `/brainautodaily HH:MM`
- `/brainautoweekly <weekday 0-6> HH:MM`
- `/robotonly`

### 2.4 控制類指令

- `/reset`
- `/newthread`
- `/restart`
- `/panic`
- `/clearqueue`
- `/clearschedule`
- `/clearschedules`
- `/run <goal>`
- `/agent [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run] <goal>`
- `/agentresume [run_id_or_path] [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run]`
- `/schedule YYYY-MM-DD HH:MM [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run] <goal>`

## 3. 三個常用流程

### A. 日常筆記整理

1. `/braininbox <想法>`
2. `/brainbatchauto 5`
3. `/braindaily`

### B. 快速交付任務

1. `/project robot`
2. `/provider claude`
3. `/run <goal>`
4. `/queue` / `/agentstatus` 追蹤進度

### C. 定時任務

1. `/schedule 2026-04-22 09:30 <goal>`
2. `/schedules` 確認排程
3. 需要清理時用 `/clearschedule` 或 `/clearschedules`

## 4. 重要行為規則

- 一般純文字訊息會被視為 agent request（送進 AI）。
- 想要可預期、可重現行為，請用 slash commands 或按鈕。
- `semantic shortcut` 目前停用，避免誤判造成錯誤操作。
- `/restart` 由 teleapp supervisor 管理，不建議手動多開同 token bot。

## 5. 相關文件

- `README.md`: 安裝與啟動
- `QUICK_REFERENCE.md`: 一頁速查
- `RUNBOOK.md`: 營運操作手冊
- `QUALITY_GATE_90.md`: 品質門檻
- `DEPENDENCY_STRATEGY.md`: 相依套件策略
