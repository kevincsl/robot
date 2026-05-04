# FEATURES GUIDE

完整指令參考。

## 一般操作

| 指令 | 說明 |
|---|---|
| `/help` | 完整指令表 |
| `/quick` | 一頁速查 |
| `/guide` | 文件入口 |
| `/menu` | 按鈕式主選單 |
| `/status` | 目前 provider / model / project / queue 狀態 |
| `/doctor` | 診斷資訊 |
| `/queue` | 目前任務佇列 |
| `/schedules` | 已排定任務 |
| `/agentstatus` | Agent 執行狀態 |
| `/agentprofiles` | Agent profile 資訊 |

## Provider 與模型

| 指令 | 說明 |
|---|---|
| `/provider [claude\|codex\|gemini]` | 切換 AI provider |
| `/models` | 列出可用模型 |
| `/model <name>` | 切換模型 |

## 專案與工作目錄

| 指令 | 說明 |
|---|---|
| `/projects` | 列出工作目錄 |
| `/project <key-or-label>` | 切換工作目錄 |

## Agent 與排程

| 指令 | 說明 |
|---|---|
| `/run <goal>` | 執行任務 |
| `/agent [--profile NAME] [--config PATH] [--commit] [--push] [--pr] [--no-post-run] <goal>` | 以選項執行 agent |
| `/agentresume [run_id_or_path] [options]` | 繼續上次 agent 執行 |
| `/schedule YYYY-MM-DD HH:MM [options] <goal>` | 新增排程任務 |

## 控制類

| 指令 | 說明 |
|---|---|
| `/reset` | 重置對話狀態 |
| `/newthread` | 開啟新對話執行緒 |
| `/restart` | 重啟 bot 程序 |
| `/panic` | 緊急停止所有任務 |
| `/clearqueue` | 清空任務佇列 |
| `/clearschedule` | 清空單一排程 |
| `/clearschedules` | 清空所有排程 |

## 第二大腦（Brain）

| 指令 | 說明 |
|---|---|
| `/brain` | Brain 功能選單 |
| `/brainread` | 讀取筆記 |
| `/braininbox <text>` | 新增筆記到收件匣 |
| `/brainweb <url>` | 匯入網頁到 brain |
| `/brainsearch <query>` | 搜尋筆記 |
| `/brainorganize` | 整理筆記 |
| `/brainbatch` | 批次處理收件匣 |
| `/brainbatchauto [limit]` | 自動批次整理 |
| `/brainproject <title>` | 建立專案筆記 |
| `/brainknowledge <title>` | 建立知識筆記 |
| `/brainresource <title>` | 建立資源筆記 |
| `/brainschedule <title-or-natural-language>` | 建立排程筆記 |
| `/braindecide <question>` | 決策分析 |
| `/brainsummary` | 產生摘要 |
| `/brainremind` | 顯示提醒 |
| `/braindaily` | 今日摘要 |
| `/brainweekly` | 每週摘要 |
| `/brainauto [on\|off\|status]` | 自動整理開關 |
| `/brainautodaily HH:MM` | 設定每日自動整理時間 |
| `/brainautoweekly <weekday 0-6> HH:MM` | 設定每週自動整理時間 |
| `/robotonly` | 切換為 robot-only 模式 |

## 多 Robot

| 指令 | 說明 |
|---|---|
| `/robots` | 列出所有活躍的 robot 實例 |
| `/robotstatus <robot_id>` | 顯示特定 robot 的詳細狀態 |

Shell 管理（背景執行）：

```bash
robotctl status
robotctl stop robot1
robotctl stop all
robotctl logs robot1 -f
```

## 常用流程

### 日常筆記整理

```
/braininbox <想法>
/brainbatchauto 5
/braindaily
```

### 快速交付任務

```
/project robot
/provider claude
/run <goal>
/queue        ← 追蹤進度
```

### 定時任務

```
/schedule 2026-05-10 09:30 <goal>
/schedules    ← 確認排程
/clearschedule ← 清除不需要的排程
```

## 重要行為說明

- 純文字訊息預設會送給 AI 當任務執行。
- 需要可重現的行為，請使用 slash commands 或按鈕。
- Semantic shortcut 已停用，避免誤判。

## 相關文件

| 檔案 | 說明 |
|---|---|
| [README.zh-TW.md](./README.zh-TW.md) | 安裝與啟動 |
| [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) | 一頁速查 |
| [MULTI_ROBOT.md](./MULTI_ROBOT.md) | 多 Robot 架構 |
| [RUNBOOK.md](./RUNBOOK.md) | 維運操作手冊 |
