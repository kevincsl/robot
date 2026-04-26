# QUICK REFERENCE

`robot` Telegram 一頁速查。

## 1) 開機後先做這 5 件事

1. `/status`
2. `/provider claude`
3. `/models`
4. `/model claude-sonnet-4-6`
5. `/project robot`

## 2) 最常用 12 個指令

- `/help`
- `/quick`
- `/menu`
- `/status`
- `/doctor`
- `/queue`
- `/projects`
- `/project <key-or-label>`
- `/run <goal>`
- `/braininbox <text>`
- `/brainsearch <query>`
- `/brainbatchauto [limit]`

## 3) Brain 快速流程

1. 收集想法：`/braininbox 今天要整理租屋資料`
2. 批次整理：`/brainbatchauto 5`
3. 看今日摘要：`/braindaily`

## 4) 排程 / 控制

- 新增排程：`/schedule 2026-04-22 10:00 更新 README 並推送`
- 查排程：`/schedules`
- 清空排程：`/clearschedule` 或 `/clearschedules`
- 清空佇列：`/clearqueue`
- 緊急清理：`/panic`
- 重啟提示：`/restart`

## 5) 常見錯誤

- `Unknown command`：先輸入 `/help`，檢查拼字與參數。
- 任務卡住：先看 `/queue` 與 `/agentstatus`，必要時 `/panic`。
- Bot 衝突：通常是同一 token 有多個程序同時 polling，只保留單一實例。

## 6) 一句話原則

要穩定可重現就用 slash commands；純文字訊息預設會送給 AI 當任務執行。
